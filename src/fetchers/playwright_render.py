"""Tier 3+4: render the page once with a real headless browser — following
pagination and opening each job's detail page for its full description —
then try structured-data extraction against the rendered DOM, falling
through to AI reading of the rendered visible text.

Structured-data extraction exists because some career portals (e.g.
Stripe's) are client-rendered React/SPA apps: the raw HTTP response
jsonld_sitemap.py fetches is just an empty shell, and the job data (and any
JobPosting markup) is injected by JavaScript after load.

The AI fallback exists for sites like Google's careers portal: a fully
custom app with zero schema.org JobPosting markup anywhere, even after full
rendering — no amount of retrying structured-data extraction finds what
isn't there, even though the page visibly, obviously lists real postings to
a human. This is different in kind from the AI usage elsewhere in this
project (Gemini finding a *candidate* URL, or reranking search results) —
there, the output is validated by an independent mechanism (actually
fetching and checking for real postings). Here AI extraction IS the
mechanism, so it only runs after structured-data extraction has already
failed, and costs against the shared daily AI call budget.
"""
from __future__ import annotations

import concurrent.futures as _cf
import json
import logging
import re
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

from .. import db
from .base import FetchError
from .jsonld_sitemap import _extract_jobpostings_from_html

logger = logging.getLogger("job_alert.fetchers.playwright_render")

MAX_PAGE_TEXT_CHARS = 28000
MAX_PAGINATION_ROUNDS = 8
MAX_DETAIL_PAGES = 15
DETAIL_CONCURRENCY = 5

EXTRACTION_PROMPT = """The following is the visible text of a company careers/jobs page,
possibly spanning multiple pages/scroll-loads (separated by "--- PAGE BREAK ---").
Identify every distinct, currently-open job posting mentioned. Respond with
ONLY a JSON array (no markdown fences, no commentary) where each element has
exactly these keys: "title", "location", "url".

For "url": the plain text above has no links in it, so a list of (link text
-> URL) pairs actually found on the page follows below. For each job, find
the entry whose link text matches that job's title (or is clearly the
"view"/"apply"/"details" link right next to it) and use ITS url. Only use
"{page_url}" if truly nothing in the list corresponds to that job — do not
invent a URL.

If you find no real job postings (e.g. this is a generic marketing page, or
explicitly says there are no open roles), return an empty JSON array: []

Page URL: {page_url}

Page text:
---
{page_text}
---

Links on the page (text -> url):
---
{links_text}
---
"""

# Matches both "load more"/infinite-scroll triggers and explicit "next
# page" pagination controls — both are handled the same way (click, wait,
# capture, compare to detect when nothing new loads).
_PAGINATION_CONTROL_RE = re.compile(
    r"^(load more|show more|next|next page|view more|see more|\d{1,4}|›|»|→)$",
    re.IGNORECASE,
)


def _launch_chromium(p):
    """Launch Chromium, allowing a caller-supplied binary.

    Playwright normally insists on a browser build matching its own
    version, downloaded from cdn.playwright.dev. Some sandboxes (the Claude
    Code cloud runner among them) block that CDN outright while shipping
    their own Chromium at a different build number — so the bundled binary
    exists but launch() rejects it on version grounds, leaving no usable
    browser at all. PLAYWRIGHT_CHROMIUM_EXECUTABLE points us straight at a
    binary and skips that check; unset, behaviour is unchanged."""
    import os

    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if executable:
        logger.info("launching chromium from PLAYWRIGHT_CHROMIUM_EXECUTABLE=%s", executable)
        return p.chromium.launch(headless=True, executable_path=executable)
    return p.chromium.launch(headless=True)


def _click_pagination_control(page) -> bool:
    """Tries buttons first, then links with rel="next" or a matching label
    — covers both <button onClick> "Load more" patterns and <a href> numbered
    pagination. Returns True if something was clicked."""
    for role in ("button", "link"):
        for el in page.get_by_role(role).all()[:40]:
            try:
                if not el.is_visible():
                    continue
                label = (el.inner_text() or "").strip()
                rel = (el.get_attribute("rel") or "")
                aria = (el.get_attribute("aria-label") or "").lower()
            except Exception:
                continue
            if "next" in rel.lower() or "next" in aria or _PAGINATION_CONTROL_RE.match(label):
                try:
                    el.click(timeout=1500)
                    page.wait_for_timeout(800)
                    return True
                except Exception:
                    continue
    return False


def _collect_links(page, base_url: str) -> list[tuple[str, str]]:
    """(visible text, absolute href) for every link with non-trivial text —
    used to give the AI extraction prompt real hrefs to match job titles
    against, since page.inner_text() strips href attributes entirely and an
    LLM working from text alone has no way to know a job's actual URL."""
    pairs = []
    for a in page.locator("a[href]").all()[:400]:
        try:
            text = (a.inner_text() or "").strip()
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        if text and len(text) > 3 and href and not href.startswith(("#", "javascript:", "mailto:")):
            pairs.append((text, urljoin(base_url, href)))
    return pairs


def _render(url: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Returns (first_page_html, accumulated_visible_text, links) from a
    single browser session.

    Many job boards (Google's, Microsoft's, ...) only render a first batch
    by default — the rest is behind infinite scroll, a "Load more" button,
    or numbered pagination, and a single unscrolled snapshot only ever sees
    that first batch regardless of how many postings actually exist. This
    scrolls, clicks pagination/load-more controls, and accumulates the text
    from each resulting state, stopping once a round produces no new
    content (reached the end) or MAX_PAGINATION_ROUNDS is hit — bounded so
    a page with a truly endless feed can't hang the fetch."""
    with sync_playwright() as p:
        browser = _launch_chromium(p)
        try:
            page = browser.new_page()
            # "networkidle" waits for ALL background network activity to
            # quiet down, which can stall for a long time on sites with
            # constant polling/analytics beacons. "domcontentloaded" is
            # enough for a React/SPA app's initial render + hydration.
            page.goto(url, wait_until="domcontentloaded", timeout=12000)
            page.wait_for_timeout(1500)  # brief settle for post-load JS rendering

            first_html = page.content()
            texts = [page.inner_text("body")]

            for _ in range(MAX_PAGINATION_ROUNDS):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(500)
                _click_pagination_control(page)

                current = page.inner_text("body")
                if current == texts[-1]:
                    break  # no change — reached the end
                texts.append(current)

            links = _collect_links(page, url)
            return first_html, "\n--- PAGE BREAK ---\n".join(texts), links
        finally:
            browser.close()


def _fetch_detail_descriptions(urls: list[str], page_url: str) -> dict[str, str]:
    """Opens each job's own detail page (bounded by MAX_DETAIL_PAGES) in one
    shared browser session and grabs its visible text as the full
    description — the AI extraction pass only sees the listing page, which
    rarely includes full descriptions. Reuses one browser across all of them
    rather than relaunching per job. A failing detail page is skipped, never
    fatal to the whole fetch."""
    distinct = [u for u in dict.fromkeys(urls) if u and u != page_url][:MAX_DETAIL_PAGES]
    if not distinct:
        return {}

    out: dict[str, str] = {}
    with sync_playwright() as p:
        browser = _launch_chromium(p)
        try:
            # Several pages open in parallel tabs in the one browser —
            # loading 15 detail pages one after another was adding ~15x a
            # single page load to every fetch, and they're independent.
            contexts = [browser.new_page() for _ in range(min(DETAIL_CONCURRENCY, len(distinct)))]

            def _load(args):
                page, url = args
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=8000)
                    page.wait_for_timeout(600)
                    return url, page.inner_text("body")[:4000]
                except Exception as e:
                    logger.debug("detail page fetch failed for %s: %s", url, e)
                    return url, None

            # Round-robin URLs across the open tabs; each tab is used by at
            # most one thread at a time (Playwright pages aren't reentrant).
            for batch_start in range(0, len(distinct), len(contexts)):
                batch = distinct[batch_start:batch_start + len(contexts)]
                with _cf.ThreadPoolExecutor(max_workers=len(batch)) as pool:
                    for url, text in pool.map(_load, zip(contexts, batch)):
                        if text:
                            out[url] = text
        finally:
            browser.close()
    return out


# A link pointing at an individual posting: ".../jobs/<something>", not a
# category/landing page. Requires the slash so "/job_categories" and
# "/job-categories" (nav links) don't match.
_JOB_DETAIL_PATH = re.compile(r"/(?:jobs?|positions?|openings?|vacanc\w*)/(?=[^/]{2,})", re.IGNORECASE)

# Link text that's a generic affordance rather than a job title.
_GENERIC_LINK_TEXT = re.compile(
    r"^(\.{0,3}\s*(read more|learn more|view|view job|apply|apply now|details|see more|more)\s*\.{0,3})$",
    re.IGNORECASE,
)


def _extract_jobs_from_links(links: list[tuple[str, str]], page_url: str) -> list[dict]:
    """Deterministic, zero-AI extraction: on most job boards each posting
    on the listing page is a real anchor whose text IS the job title and
    whose href IS the application URL (verified on Amazon's portal, where
    every posting appears as '<title>' -> '/en/jobs/<id>/<slug>').

    Running this before the AI tier means the common case costs no AI call
    at all — which matters both for the daily budget and because AI
    extraction is the slowest step by far. It's also strictly more accurate
    when it applies: titles and URLs are read straight from the DOM rather
    than re-derived by a model from flattened page text."""
    by_url: dict[str, str] = {}
    for text, href in links:
        if not href or not _JOB_DETAIL_PATH.search(urlparse(href).path):
            continue
        text = (text or "").strip()
        if not text or len(text) < 4 or _GENERIC_LINK_TEXT.match(text):
            continue
        # Several anchors can point at one posting (title + "Read more");
        # keep the longest text, which is the real title.
        if len(text) > len(by_url.get(href, "")):
            by_url[href] = text

    return [
        {"title": title, "location": None, "url": url, "description": ""}
        for url, title in by_url.items()
    ]


def _extract_via_ai(page_text: str, page_url: str, links: list[tuple[str, str]]) -> list[dict]:
    from ..webutil import _call_gemini, _extract_text  # local import avoids a cycle at module load

    if not page_text.strip():
        return []
    if not db.check_and_increment_ai_budget(ai_daily_limit()):
        logger.warning("AI daily call budget (%d) exhausted — skipping AI text extraction", ai_daily_limit())
        return []

    # Capped — a page can have hundreds of nav/footer links; most aren't
    # relevant, and this only needs to be enough for the model to match job
    # titles against their detail-page URLs.
    links_text = "\n".join(f"{t} -> {u}" for t, u in links[:200]) or "(none found)"
    prompt = EXTRACTION_PROMPT.format(
        page_url=page_url, page_text=page_text[:MAX_PAGE_TEXT_CHARS], links_text=links_text[:6000],
    )
    # Measured: successful calls take 17-21s for a ~12k char page, so the
    # default 45s timeout leaves real headroom. _call_gemini handles its
    # own backoff-retry and cross-backend failover on top of that.
    status, data = _call_gemini(prompt, use_search_grounding=False)
    if status != 200:
        logger.info("ai_extract: all AI backends failed (status %s)", status)
        return []

    raw_text = _extract_text(data).strip()
    raw_text = re.sub(r"^```(?:json)?|```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        jobs = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(jobs, list):
        return []

    return [
        {
            "title": j.get("title", ""),
            "location": j.get("location") or None,
            "url": j.get("url") or page_url,
            "description": "",
        }
        for j in jobs
        if isinstance(j, dict) and (j.get("title") or "").strip()
    ]


def fetch(career_page_url: str, **_) -> list[dict]:
    try:
        html, text, links = _render(career_page_url)
    except Exception as e:
        raise FetchError(f"playwright_render: could not render {career_page_url}: {e}") from e

    jobs = _extract_jobpostings_from_html(html, career_page_url)
    tier_used = "structured"

    if not jobs:
        # Zero-AI structural pass before spending an AI call — most boards
        # render each posting as a plain anchor we can read directly.
        jobs = _extract_jobs_from_links(links, career_page_url)
        tier_used = "links"

    if not jobs:
        jobs = _extract_via_ai(text, career_page_url, links)
        tier_used = "ai"
        if not jobs:
            # Attach the links we already collected from the RENDERED DOM.
            # The caller's link-crawl fallback otherwise re-fetches the page
            # over plain HTTP, which on a JS-rendered portal (Amazon's,
            # Google's) sees no nav links at all — so the real listing page
            # one click away was unreachable. These cost nothing extra.
            err = FetchError(
                "playwright_render: no structured job data, and AI found no postings in the page text"
            )
            err.rendered_links = links
            raise err

    # Fill in full descriptions from each job's own detail page — neither
    # structured-data nor AI extraction reliably gets more than a snippet
    # from the listing page alone.
    descriptions = _fetch_detail_descriptions([j["url"] for j in jobs], career_page_url)
    for j in jobs:
        if j["url"] in descriptions:
            j["description"] = descriptions[j["url"]]

    logger.info(
        "playwright_render: found %d job(s) via %s extraction (%d with full descriptions)",
        len(jobs), tier_used, len(descriptions),
    )
    return jobs
