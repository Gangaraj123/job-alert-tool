"""One-hop link discovery: a careers landing page (e.g. stripe.com/careers)
often has zero job postings itself — the real listing is behind a button
like "Search open roles" (e.g. stripe.com/careers/search). Rather than guess
more URL patterns, this reads the actual page and follows links that look
job-related, so discovery generalizes to arbitrary site structures instead
of a fixed guess list.

Every link found here is still validated the same way as any other
candidate in pipeline.discover_career_url — we never trust that a link
"looks right", only that fetching it actually returns real postings.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .fetchers.base import FetchError, http_get

# Matched against the link's PATH only (not query string) — a bare "search"
# or "job" hint matched against the whole href+text used to sweep up
# unrelated links on large sites (Microsoft's homepage: site search, Bing
# translate, news search all contain "search" somewhere). Path segments are
# far more specific than loose substrings.
_PATH_HINT = re.compile(r"/(jobs?|careers?|openings?|vacanc\w*)(/|$)", re.IGNORECASE)

# Matched against the visible link TEXT — multi-word phrases only, so a
# generic "Search" button elsewhere on the page can't match.
_TEXT_HINT = re.compile(
    r"(open roles?|open positions?|search jobs?|job search|view openings?|"
    r"see openings?|current openings?|job openings?|browse jobs?|all jobs?|"
    # "find jobs" was missing and is what Amazon's portal actually uses —
    # 48 links were collected from its homepage and every one was rejected
    # purely because the phrase list didn't cover the wording they chose.
    r"find jobs?|view jobs?|explore jobs?|see jobs?|apply now)",
    re.IGNORECASE,
)


def filter_job_related_links(
    links: list[tuple[str, str]], page_url: str, limit: int = 8
) -> list[str]:
    """Applies the same job-link heuristics as find_job_related_links, but
    to (text, href) pairs already collected elsewhere — specifically from a
    Playwright-rendered DOM. A plain-HTTP re-fetch of a JS-rendered careers
    portal returns a shell with no navigation, so for those sites this is
    the only way the "real listing is one click away" case is reachable."""
    base_domain = urlparse(page_url).netloc
    out: list[str] = []
    seen: set[str] = {page_url}

    for text, href in links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(page_url, href)
        if not (_PATH_HINT.search(urlparse(absolute).path) or _TEXT_HINT.search(text or "")):
            continue
        if urlparse(absolute).netloc != base_domain and not _is_known_ats(absolute):
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
            if len(out) >= limit:
                break
    return out


def _is_known_ats(url: str) -> bool:
    return any(h in url for h in (
        "ashbyhq", "greenhouse", "lever.co", "workable",
        "smartrecruiters", "myworkdayjobs", "recruitee",
    ))


def find_job_related_links(page_url: str, limit: int = 8) -> list[str]:
    try:
        resp = http_get(page_url)
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    base_domain = urlparse(page_url).netloc

    candidates: list[str] = []
    seen: set[str] = {page_url}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        text = a.get_text(" ", strip=True)
        path = urlparse(urljoin(page_url, href)).path
        if not (_PATH_HINT.search(path) or _TEXT_HINT.search(text)):
            continue

        absolute = urljoin(page_url, href)
        # Stay on the same company's domain (or a known ATS domain it might
        # link out to) — don't follow unrelated outbound links.
        if urlparse(absolute).netloc != base_domain and "ashbyhq" not in absolute \
                and "greenhouse" not in absolute and "lever.co" not in absolute \
                and "workable" not in absolute and "smartrecruiters" not in absolute \
                and "myworkdayjobs" not in absolute and "recruitee" not in absolute:
            continue

        if absolute not in seen:
            seen.add(absolute)
            candidates.append(absolute)
            if len(candidates) >= limit:
                break

    return candidates
