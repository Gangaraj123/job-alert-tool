"""Tier 3 (last resort): render the page with a real headless browser and
re-run the same JSON-LD extraction against the RENDERED DOM.

This is purely browser rendering — no AI/LLM call. It exists because some
career portals (e.g. Stripe's) are client-rendered React/SPA apps: the raw
HTTP response jsonld_sitemap.py fetches is just an empty shell, and the job
data (and any JobPosting markup) is injected by JavaScript after load. This
tier executes that JavaScript, then hands the fully-rendered HTML to the
exact same parser jsonld_sitemap.py uses, so a listing only counts as found
here under the same rule as every other tier: real JobPosting data, not a
guess.
"""
from __future__ import annotations

import logging

from playwright.sync_api import sync_playwright

from .base import FetchError
from .jsonld_sitemap import _extract_jobpostings_from_html

logger = logging.getLogger("job_alert.fetchers.playwright_render")


def fetch(career_page_url: str, **_) -> list[dict]:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(career_page_url, wait_until="networkidle", timeout=30000)
                html = page.content()
            finally:
                browser.close()
    except Exception as e:
        raise FetchError(f"playwright_render: could not render {career_page_url}: {e}") from e

    jobs = _extract_jobpostings_from_html(html, career_page_url)
    if not jobs:
        raise FetchError("playwright_render: no JobPosting data found even after rendering")

    logger.info("playwright_render: found %d JobPosting entries after rendering", len(jobs))
    return jobs
