"""Small helpers for finding and displaying a company: Clearbit's
autocomplete endpoint for name -> domain search (free, no key — verified
live), Google's public favicon endpoint for the logo image (Clearbit's own
logo CDN has been decommissioned), and Gemini (with Google Search grounding)
for actually finding a company's real careers page, replacing naive
URL-pattern guessing.

Note: an LLM finding a *candidate* URL is only half the story — we never
trust its answer on faith. Every candidate (from here or from plain
pattern-guessing) still goes through pipeline.preview_detect_and_fetch,
which actually fetches the page and checks for real job postings. That
fetch-and-verify step, not the LLM, is what decides "found" — it's ground
truth, so a wrong/stale guess just fails validation and we move on.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import requests

from .config import load_config, load_settings

logger = logging.getLogger("job_alert.webutil")

CLEARBIT_AUTOCOMPLETE_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"
GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")


def domain_from_url(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.removeprefix("www.")


def favicon_url(url: str, size: int = 64) -> str:
    domain = domain_from_url(url)
    return f"https://www.google.com/s2/favicons?domain={domain}&sz={size}"


def search_companies(query: str, limit: int = 8) -> list[dict]:
    """Returns [{name, domain, logo_url}] for a free-text company name
    search. Used by the Add Company UI so the user never has to know or
    paste a URL — just type a name and pick from real suggestions."""
    query = query.strip()
    if len(query) < 2:
        return []
    try:
        resp = requests.get(CLEARBIT_AUTOCOMPLETE_URL, params={"query": query}, timeout=5)
        resp.raise_for_status()
        results = resp.json()
    except Exception:
        return []

    out = []
    for r in results[:limit]:
        domain = r.get("domain")
        if not domain:
            continue
        out.append({"name": r.get("name") or domain, "domain": domain, "logo_url": favicon_url(domain)})
    return out


def rerank_company_matches(query: str, results: list[dict]) -> list[dict]:
    """Clearbit's autocomplete matches on substrings, so searching "Google"
    also surfaces unrelated product/spin-off sites (Chrome Enterprise,
    Google Domains, ...) that nobody means when adding a company to track
    for job postings. Asks Gemini (no search grounding needed — this is pure
    reasoning over a list we already have, not a factual lookup, so there's
    no hallucination-about-the-world risk) which of the already-fetched
    results is/are the actual company meant.

    This only affects what's shown to pick from — it's not relied on for
    correctness. If it fails, is rate-limited, or isn't configured, the
    original unfiltered list is returned as-is."""
    settings = load_settings()
    if not settings.gemini_api_key or len(results) <= 1:
        return results

    numbered = "\n".join(f"{i}. {r['name']} ({r['domain']})" for i, r in enumerate(results))
    prompt = (
        f"A user searched for the company \"{query}\" to track its job postings. "
        f"Here are name-matching results from a fuzzy company search:\n{numbered}\n\n"
        f"Some of these may be unrelated sub-brands, product pages, or spin-offs that "
        f"nobody means when they say they want to track \"{query}\" for jobs (e.g. searching "
        f"\"Google\" shouldn't also suggest Chrome Enterprise or Google Domains as separate "
        f"companies to track). Respond with ONLY the numbers (from the list above) of the "
        f"result(s) that are genuinely the company \"{query}\" itself or its main job-postings "
        f"entity, comma-separated, most likely first. No commentary."
    )

    model = load_config().get("discovery", {}).get("gemini_model", "gemini-3.8-flash")
    try:
        resp = requests.post(
            GEMINI_URL_TEMPLATE.format(model=model),
            params={"key": settings.gemini_api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=10,
        )
        if resp.status_code != 200:
            return results
        data = resp.json()
        text = "".join(
            part.get("text", "")
            for candidate in data.get("candidates", [])
            for part in candidate.get("content", {}).get("parts", [])
        )
        indices = [int(n) for n in re.findall(r"\d+", text)]
    except Exception as e:
        logger.warning("Gemini result reranking failed (showing unfiltered list): %s", e)
        return results

    picked = [results[i] for i in indices if 0 <= i < len(results)]
    return picked or results


def find_career_urls_via_gemini(company_name: str, domain: str, count: int = 3) -> dict:
    """Asks Gemini (with Google Search grounding, so it's actually looking
    at live web results, not guessing from training data) for likely
    careers-page URLs.

    Returns {"status": ..., "urls": [...]}. status is one of:
    - "ok"             — got a response (urls may still be empty if genuinely none found)
    - "not_configured" — no GEMINI_API_KEY set
    - "rate_limited"    — quota/rate limit hit (HTTP 429) — surfaced in the UI so the
                          user knows AI discovery is temporarily unavailable, not silently
                          skipped
    - "unavailable"    — model overloaded (503) or any other request failure

    Callers should fall back to pattern-guessing on anything but "ok", but the
    UI can show *why* using `status`."""
    settings = load_settings()
    if not settings.gemini_api_key:
        return {"status": "not_configured", "urls": []}

    model = load_config().get("discovery", {}).get("gemini_model", "gemini-3.8-flash")
    prompt = (
        f"Find the official, current careers/jobs listing page for the company "
        f"\"{company_name}\" (website: {domain}). Respond with ONLY a list of up to "
        f"{count} candidate URLs, one per line, most likely first. No commentary, "
        f"no markdown, just the URLs."
    )

    try:
        resp = requests.post(
            GEMINI_URL_TEMPLATE.format(model=model),
            params={"key": settings.gemini_api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
            },
            timeout=15,
        )
        if resp.status_code == 429:
            logger.warning("Gemini rate limit/quota hit for %s", company_name)
            return {"status": "rate_limited", "urls": []}
        if resp.status_code == 503:
            logger.warning("Gemini model overloaded for %s", company_name)
            return {"status": "unavailable", "urls": []}
        resp.raise_for_status()
        data = resp.json()
        text = "".join(
            part.get("text", "")
            for candidate in data.get("candidates", [])
            for part in candidate.get("content", {}).get("parts", [])
        )
    except Exception as e:
        logger.warning("Gemini career-page search failed (falling back to pattern guessing): %s", e)
        return {"status": "unavailable", "urls": []}

    urls = _URL_RE.findall(text)
    # de-dupe while preserving order
    seen = set()
    out = []
    for u in urls:
        u = u.rstrip(".,")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return {"status": "ok", "urls": out[:count]}
