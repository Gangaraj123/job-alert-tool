"""Tier 3+4: render the page once with a real headless browser, then try
structured-data extraction against the rendered DOM, falling through to AI
reading of the rendered visible text — without launching a second browser
for the AI pass (they used to be separate tiers, each re-rendering the same
page from scratch).

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

import json
import logging
import re

from playwright.sync_api import sync_playwright

from .. import db
from .base import FetchError
from .jsonld_sitemap import _extract_jobpostings_from_html

logger = logging.getLogger("job_alert.fetchers.playwright_render")

MAX_PAGE_TEXT_CHARS = 12000
AI_DAILY_CALL_LIMIT = 50

EXTRACTION_PROMPT = """The following is the visible text of a company careers/jobs page.
Identify every distinct, currently-open job posting mentioned. Respond with
ONLY a JSON array (no markdown fences, no commentary) where each element has
exactly these keys: "title", "location", "url". If the exact URL for a
specific posting isn't visible in the text, use "{page_url}" for that entry.
If you find no real job postings (e.g. this is a generic marketing page, or
explicitly says there are no open roles), return an empty JSON array: []

Page URL: {page_url}

Page text:
---
{page_text}
---
"""


def _render(url: str) -> tuple[str, str]:
    """Returns (rendered_html, visible_text) from a single browser session."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            # "networkidle" waits for ALL background network activity to
            # quiet down, which can stall for a long time on sites with
            # constant polling/analytics beacons. "domcontentloaded" is
            # enough for a React/SPA app's initial render + hydration.
            page.goto(url, wait_until="domcontentloaded", timeout=12000)
            page.wait_for_timeout(1500)  # brief settle for post-load JS rendering
            return page.content(), page.inner_text("body")
        finally:
            browser.close()


def _extract_via_ai(page_text: str, page_url: str) -> list[dict]:
    from ..webutil import _call_gemini, _extract_text  # local import avoids a cycle at module load

    if not page_text.strip():
        return []
    if not db.check_and_increment_ai_budget(AI_DAILY_CALL_LIMIT):
        logger.warning("AI daily call budget (%d) exhausted — skipping AI text extraction", AI_DAILY_CALL_LIMIT)
        return []

    prompt = EXTRACTION_PROMPT.format(page_url=page_url, page_text=page_text[:MAX_PAGE_TEXT_CHARS])
    # Measured: successful calls typically take 17-21s for a ~12k char page,
    # so a 20s timeout was cutting it right at the edge — any minor latency
    # spike caused an intermittent, hard-to-reproduce failure. One retry on
    # top of the longer timeout, since content extraction itself has proven
    # reliable (verified 3/3 against Google's page) — it's specifically
    # transient network timeouts worth retrying, not a real failure mode.
    status, data = _call_gemini(prompt, use_search_grounding=False, timeout=45)
    if status != 200:
        logger.info("ai_extract: first attempt failed (status %s), retrying once", status)
        status, data = _call_gemini(prompt, use_search_grounding=False, timeout=45)
    if status != 200:
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
        html, text = _render(career_page_url)
    except Exception as e:
        raise FetchError(f"playwright_render: could not render {career_page_url}: {e}") from e

    jobs = _extract_jobpostings_from_html(html, career_page_url)
    if jobs:
        logger.info("playwright_render: found %d JobPosting entries after rendering", len(jobs))
        return jobs

    jobs = _extract_via_ai(text, career_page_url)
    if jobs:
        logger.info("playwright_render: AI identified %d job(s) from rendered page text", len(jobs))
        return jobs

    raise FetchError("playwright_render: no structured job data, and AI found no postings in the page text")
