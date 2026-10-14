"""Tier 3 (last resort): render the page with Playwright, hand the visible
text to Claude, and ask it to extract structured job postings.

This is the most expensive tier (headless browser + an LLM call) so it's only
reached when a company has no detected ATS AND no JSON-LD/sitemap postings.
"""
from __future__ import annotations

import json
import logging
import re

import anthropic
from playwright.sync_api import sync_playwright

from ..config import load_config, load_settings
from .base import FetchError

logger = logging.getLogger("job_alert.fetchers.playwright_ai")

_cfg = load_config().get("fetch", {})
MODEL = _cfg.get("model", "claude-haiku-5-5")
MAX_TOKENS = _cfg.get("max_tokens", 4096)
MAX_PAGE_TEXT_CHARS = _cfg.get("max_page_text_chars", 15000)

EXTRACTION_PROMPT = """You are extracting job postings from the text of a careers page.
The raw visible text of the page follows. Identify every distinct job opening
mentioned and return ONLY a JSON array (no markdown fences, no commentary) where
each element has exactly these keys: "title", "location", "url", "description".

Rules:
- "url" should be the specific link for that job if one is visible in the text,
  otherwise reuse the page url given below.
- "description" should be a short 1-3 sentence summary of the role if any
  detail is available in the text, otherwise an empty string.
- If you find no job postings at all, return an empty JSON array: []

Page URL: {page_url}

Page text:
---
{page_text}
---
"""


def _render_page_text(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            text = page.inner_text("body")
        finally:
            browser.close()
    return text[:MAX_PAGE_TEXT_CHARS]


def _extract_jobs_with_claude(page_url: str, page_text: str) -> list[dict]:
    settings = load_settings()
    if not settings.anthropic_api_key:
        raise FetchError("playwright_ai: ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": EXTRACTION_PROMPT.format(page_url=page_url, page_text=page_text),
        }],
    )
    raw_text = "".join(block.text for block in message.content if block.type == "text")
    raw_text = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    try:
        jobs = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise FetchError(f"playwright_ai: could not parse model output as JSON: {e}") from e

    if not isinstance(jobs, list):
        raise FetchError("playwright_ai: model output was not a JSON array")
    return jobs


def fetch(career_page_url: str, **_) -> list[dict]:
    try:
        page_text = _render_page_text(career_page_url)
    except Exception as e:
        raise FetchError(f"playwright_ai: render failed for {career_page_url}: {e}") from e

    jobs = _extract_jobs_with_claude(career_page_url, page_text)
    logger.info("playwright_ai: extracted %d job(s) from %s", len(jobs), career_page_url)
    return [
        {
            "title": j.get("title", ""),
            "location": j.get("location") or None,
            "url": j.get("url") or career_page_url,
            "description": j.get("description", ""),
        }
        for j in jobs
    ]
