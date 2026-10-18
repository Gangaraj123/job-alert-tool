"""Small helpers for finding and displaying a company: Clearbit's
autocomplete endpoint for name -> domain search (free, no key — verified
live), Google's public favicon endpoint for the logo image (Clearbit's own
logo CDN has been decommissioned), and Gemini (with Google Search grounding)
for actually finding a company's real careers page, replacing naive
URL-pattern guessing.

Gemini is reachable through two backends, tried in this order:
1. Vertex AI (if GOOGLE_VERTEX_CREDENTIALS_JSON + VERTEX_PROJECT are set) —
   bills against a GCP project's billing account (e.g. free trial credits)
   instead of the AI Studio key's thin free-tier quota.
2. The plain AI Studio API key (GEMINI_API_KEY) — simpler to set up, smaller
   free quota.
_call_gemini() abstracts over both so callers don't care which is active.

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

from . import db
from .config import load_config, load_settings

AI_DAILY_CALL_LIMIT = 50

logger = logging.getLogger("job_alert.webutil")

CLEARBIT_AUTOCOMPLETE_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"
AI_STUDIO_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VERTEX_URL_TEMPLATE = (
    "https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
    "/locations/{location}/publishers/google/models/{model}:generateContent"
)

_URL_RE = re.compile(r"https?://[^\s\"'`<>\)\]]+")

_vertex_credentials = None  # lazily created, cached across calls in this process


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


def _vertex_access_token() -> str | None:
    """Cached OAuth2 bearer token for the Vertex AI service account.
    Refreshed automatically when expired. Returns None if Vertex isn't
    configured or the credentials fail to load — callers fall back to the
    AI Studio key in that case."""
    global _vertex_credentials
    settings = load_settings()
    if not settings.google_vertex_credentials_json or not settings.vertex_project:
        return None

    try:
        import json as _json

        from google.auth.transport.requests import Request as _Request
        from google.oauth2 import service_account as _service_account

        if _vertex_credentials is None:
            info = _json.loads(settings.google_vertex_credentials_json)
            _vertex_credentials = _service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        if not _vertex_credentials.valid:
            _vertex_credentials.refresh(_Request())
        return _vertex_credentials.token
    except Exception as e:
        logger.warning("Could not get a Vertex AI access token (falling back to AI Studio key): %s", e)
        return None


def _call_gemini(prompt: str, use_search_grounding: bool, timeout: int = 15) -> tuple[int, dict]:
    """Calls Gemini via Vertex AI if configured, else the AI Studio key.
    Returns (http_status_code, parsed_json_body) — 0 as the status means the
    request itself failed to even complete (network error, bad credentials,
    etc.), distinct from a real HTTP error status."""
    settings = load_settings()
    model = load_config().get("discovery", {}).get("gemini_model", "gemini-2.5-flash")
    tools = [{"googleSearch": {}}] if use_search_grounding else None

    token = _vertex_access_token()
    if token:
        url = VERTEX_URL_TEMPLATE.format(
            location=settings.vertex_location, project=settings.vertex_project, model=model
        )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        params = {}
    elif settings.gemini_api_key:
        url = AI_STUDIO_URL_TEMPLATE.format(model=model)
        headers = {}
        params = {"key": settings.gemini_api_key}
        # AI Studio's tool schema uses snake_case, unlike Vertex's camelCase.
        tools = [{"google_search": {}}] if use_search_grounding else None
    else:
        return 0, {}

    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if tools:
        body["tools"] = tools

    try:
        resp = requests.post(url, headers=headers, params=params, json=body, timeout=timeout)
        if resp.status_code == 429 and db.claim_ai_limit_alert():
            from .digest import send_ai_limit_alert
            backend = "Vertex AI" if token else "the AI Studio key"
            send_ai_limit_alert(f"{backend} returned HTTP 429 (rate limit/quota exceeded).")
        return resp.status_code, (resp.json() if resp.content else {})
    except Exception as e:
        logger.warning("Gemini request failed: %s", e)
        return 0, {}


def _extract_text(data: dict) -> str:
    return "".join(
        part.get("text", "")
        for candidate in data.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
    )


def matches_experience_level(title: str, description: str, min_years: int = 2, max_years: int = 4) -> bool:
    """AI-judges whether a job's ACTUAL requirements correspond to roughly
    min_years-max_years of professional software/IT experience (SDE-2
    equivalent) — based on the description content, not the job title and
    explicitly NOT the specific tech stack (a "Cloud Engineer" or "Platform
    Engineer" role with 2-4 years required should match just as well as a
    "Software Engineer" one; keyword/title filtering already narrowed the
    candidates down to engineering roles before this ever runs).

    Returns True — i.e. doesn't reject the job — whenever it can't actually
    determine an answer (no description to evaluate, AI unavailable, budget
    exhausted, call failed). The deterministic filters in filters.py already
    did the real narrowing; this is a secondary refinement, not the primary
    gate, so an AI hiccup should never silently drop an otherwise-matching
    job."""
    if not description or not description.strip():
        return True
    if not db.check_and_increment_ai_budget(AI_DAILY_CALL_LIMIT):
        logger.warning("AI daily call budget (%d) exhausted — skipping experience-level check", AI_DAILY_CALL_LIMIT)
        return True

    prompt = (
        f"You are screening a job posting to check its REQUIRED experience level — "
        f"specifically whether it needs roughly {min_years}-{max_years} years of "
        f"professional software/IT engineering experience (an \"SDE-2\"/\"Software "
        f"Engineer II\" equivalent level).\n\n"
        f"Judge ONLY by the experience-level requirement and whether this is a "
        f"software/IT engineering role in general — titles like Cloud Engineer, "
        f"Backend Engineer, Platform Engineer, DevOps Engineer, Infrastructure "
        f"Engineer all count equally. Do NOT judge by the specific technology "
        f"stack (language, framework, cloud provider) and do NOT judge by exact "
        f"title wording.\n\n"
        f"Job title: {title}\n"
        f"Job description:\n---\n{description[:3000]}\n---\n\n"
        f"Does this role's required experience fall roughly within {min_years}-{max_years} "
        f"years (not entry-level/0-1 years, not senior/staff/5+ years)? "
        f"Respond with ONLY \"yes\" or \"no\" as the first word."
    )

    status, data = _call_gemini(prompt, use_search_grounding=False, timeout=25)
    if status != 200:
        return True

    answer = _extract_text(data).strip().lower()
    return answer.startswith("yes")


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
    if len(results) <= 1:
        return results
    if not settings.gemini_api_key and not (settings.google_vertex_credentials_json and settings.vertex_project):
        return results
    if not db.check_and_increment_ai_budget(AI_DAILY_CALL_LIMIT):
        logger.warning("AI daily call budget (%d) exhausted — skipping reranking", AI_DAILY_CALL_LIMIT)
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

    status, data = _call_gemini(prompt, use_search_grounding=False, timeout=10)
    if status != 200:
        return results

    indices = [int(n) for n in re.findall(r"\d+", _extract_text(data))]
    picked = [results[i] for i in indices if 0 <= i < len(results)]
    return picked or results


def find_career_urls_via_gemini(company_name: str, domain: str, count: int = 3) -> dict:
    """Asks Gemini (with Google Search grounding, so it's actually looking
    at live web results, not guessing from training data) for likely
    careers-page URLs.

    Returns {"status": ..., "urls": [...]}. status is one of:
    - "ok"              — got a response (urls may still be empty if genuinely none found)
    - "not_configured"  — neither Vertex AI nor GEMINI_API_KEY is set
    - "rate_limited"    — quota/rate limit hit (HTTP 429) — surfaced in the UI so the
                          user knows AI discovery is temporarily unavailable, not silently
                          skipped
    - "budget_exceeded" — this app's own daily call cap was hit (independent of any
                          provider-side quota)
    - "unavailable"     — model overloaded (503) or any other request failure

    Callers should fall back to pattern-guessing on anything but "ok", but the
    UI can show *why* using `status`."""
    settings = load_settings()
    if not settings.gemini_api_key and not (settings.google_vertex_credentials_json and settings.vertex_project):
        return {"status": "not_configured", "urls": []}
    if not db.check_and_increment_ai_budget(AI_DAILY_CALL_LIMIT):
        logger.warning("AI daily call budget (%d) exhausted — skipping Gemini discovery", AI_DAILY_CALL_LIMIT)
        return {"status": "budget_exceeded", "urls": []}

    prompt = (
        f"Find the official, current careers/jobs listing page for the company "
        f"\"{company_name}\" (website: {domain}). Respond with ONLY a list of up to "
        f"{count} candidate URLs, one per line, most likely first. No commentary, "
        f"no markdown, just the URLs."
    )

    status, data = _call_gemini(prompt, use_search_grounding=True, timeout=25)
    if status == 429:
        logger.warning("Gemini rate limit/quota hit for %s", company_name)
        return {"status": "rate_limited", "urls": []}
    if status != 200:
        if status != 0:
            logger.warning("Gemini request for %s returned HTTP %s", company_name, status)
        return {"status": "unavailable", "urls": []}

    urls = _URL_RE.findall(_extract_text(data))
    # de-dupe while preserving order
    seen = set()
    out = []
    for u in urls:
        u = u.rstrip(".,*_)")  # trailing markdown/punctuation the regex can't exclude mid-URL
        if u not in seen:
            seen.add(u)
            out.append(u)
    return {"status": "ok", "urls": out[:count]}
