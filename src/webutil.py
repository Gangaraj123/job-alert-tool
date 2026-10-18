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
import time
from urllib.parse import urlparse

import requests

from . import db
from .config import load_config, load_settings

logger = logging.getLogger("job_alert.webutil")


def ai_daily_limit() -> int:
    """Read at call time, not import time, so editing config.yaml takes
    effect without restarting the app."""
    return load_config().get("ai", {}).get("daily_call_limit", 400)


def ai_status() -> tuple[bool, str]:
    """(is_ai_usable, human-readable reason). Lets the UI say plainly when
    an AI-backed feature is degraded instead of silently returning worse
    results — the failure mode that made company search look broken."""
    settings = load_settings()
    if not settings.gemini_api_key and not (
        settings.google_vertex_credentials_json and settings.vertex_project
    ):
        return False, "No AI backend is configured."

    used = db.ai_calls_used_today()
    limit = ai_daily_limit()
    if used >= limit:
        return False, f"Daily AI call limit reached ({used}/{limit}). Resets at 00:00 UTC."

    now = time.monotonic()
    if _rate_limited_until and all(t > now for t in _rate_limited_until.values()):
        return False, "All AI backends are rate-limited right now. Retrying shortly."

    return True, f"{used}/{limit} AI calls used today."

CLEARBIT_AUTOCOMPLETE_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"
AI_STUDIO_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VERTEX_URL_TEMPLATE = (
    "https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
    "/locations/{location}/publishers/google/models/{model}:generateContent"
)

_URL_RE = re.compile(r"https?://[^\s\"'`<>\)\]]+")

_vertex_credentials = None  # lazily created, cached across calls in this process

# backend name -> time.monotonic() deadline until which it's considered
# rate-limited. A 429 on the AI Studio free tier is a per-minute cap, so
# re-probing it on every subsequent call just burns a request plus a
# backoff sleep before failing over anyway; this skips it until the window
# has plausibly reset.
_rate_limited_until: dict[str, float] = {}
RATE_LIMIT_COOLDOWN_SECONDS = 60


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
    return rank_company_matches(query, out)


# Country-code and vanity TLDs that, for a query like "Amazon", almost
# always indicate a regional storefront rather than the hiring entity.
_REGIONAL_TLDS = {
    "it", "fi", "de", "fr", "es", "nl", "se", "no", "dk", "pl", "br",
    "mx", "jp", "cn", "in", "au", "ca", "uk", "ie", "ch", "at", "be",
}


def rank_company_matches(query: str, results: list[dict]) -> list[dict]:
    """Order fuzzy name matches so the real hiring entity comes first,
    using only the name and domain — no AI, no network.

    Clearbit matches on substrings, so "Amazon" also returns Mechanical
    Turk, aboutamazon.com and amazon.it. Previously only an AI call
    separated those, which meant search quality collapsed whenever AI was
    unavailable. This is deterministic, instant, and free, so the AI rerank
    becomes a refinement rather than a dependency."""
    q = query.strip().lower()
    q_compact = re.sub(r"[^a-z0-9]", "", q)

    def score(r: dict) -> tuple:
        name = (r.get("name") or "").lower()
        domain = (r.get("domain") or "").lower()
        label = domain.split(".")[0]
        tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
        extra_words = max(0, len(name.split()) - len(q.split()))

        s = 0
        if name == q:
            s += 100                      # exact company name
        elif name.startswith(q):
            s += 40
        if label == q_compact:
            s += 60                       # domain label is exactly the query
        elif label.startswith(q_compact):
            s += 20

        # "Amazon Mechanical Turk" / "Google for Creators": the more words
        # bolted on beyond the query, the more likely it's a sub-brand.
        s -= extra_words * 18

        if tld in _REGIONAL_TLDS:
            s -= 30                       # amazon.it, airbnb.fi
        if label.startswith("about") or label.startswith("blog"):
            s -= 40                       # aboutamazon.com
        if tld in ("com", "org", "net"):
            s += 8
        if tld == "jobs" or "careers" in domain or "jobs" in label:
            s += 45                       # amazon.jobs — the hiring entity

        return (-s, len(name))

    return sorted(results, key=score)


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


def _build_backends(use_search_grounding: bool) -> list[dict]:
    """Every usable Gemini backend, in preference order: the AI Studio key
    first, Vertex AI second. Returns [] if neither is configured.

    Two backends matter because the AI Studio free tier enforces a
    per-MINUTE request cap — a short burst of calls (which this app does
    constantly: discovery, reranking, extraction, experience checks) trips
    a 429 that clears within seconds, while Vertex (billed against GCP
    credits) has far more headroom. Having only one backend meant one
    transient 429 silently degraded every AI feature at once."""
    settings = load_settings()
    discovery_cfg = load_config().get("discovery", {})
    # Deliberately separate: the same model name is NOT valid on both
    # backends (see config.yaml) — sharing one silently 404'd every failover.
    ai_studio_model = discovery_cfg.get("gemini_model", "gemini-3.8-flash")
    vertex_model = discovery_cfg.get("vertex_model", "gemini-2.5-flash")
    backends = []

    if settings.gemini_api_key:
        backends.append({
            "name": "AI Studio",
            "url": AI_STUDIO_URL_TEMPLATE.format(model=ai_studio_model),
            "headers": {},
            "params": {"key": settings.gemini_api_key},
            # AI Studio's tool schema uses snake_case, unlike Vertex's camelCase.
            "tools": [{"google_search": {}}] if use_search_grounding else None,
        })

    if settings.google_vertex_credentials_json and settings.vertex_project:
        token = _vertex_access_token()
        if token:
            backends.append({
                "name": "Vertex AI",
                "url": VERTEX_URL_TEMPLATE.format(
                    location=settings.vertex_location, project=settings.vertex_project, model=vertex_model
                ),
                "headers": {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                "params": {},
                "tools": [{"googleSearch": {}}] if use_search_grounding else None,
            })

    # Skip any backend currently in rate-limit cooldown, but never return an
    # empty list just because everything is cooling down — in that case fall
    # through and let the calls actually be attempted.
    now = time.monotonic()
    available = [b for b in backends if _rate_limited_until.get(b["name"], 0) <= now]
    return available or backends


def _call_gemini(prompt: str, use_search_grounding: bool, timeout: int = 45) -> tuple[int, dict]:
    """Calls Gemini, transparently handling transient rate limits.

    Strategy per backend: try, and on a 429 (per-minute rate cap) wait
    briefly and retry once — these clear in seconds. If the backend is
    still rate-limited or errors, fail over to the next backend entirely.
    Only when EVERY backend is exhausted does this report failure, and only
    then does it send the user a "limit reached" alert — previously a
    single transient 429 both degraded the feature and fired an alarm.

    Returns (http_status_code, parsed_json_body) — 0 as the status means
    the request failed to complete at all (network error, bad credentials),
    distinct from a real HTTP error status."""
    backends = _build_backends(use_search_grounding)
    if not backends:
        return 0, {}

    last_status, last_data = 0, {}
    saw_rate_limit = False

    for backend in backends:
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if backend["tools"]:
            body["tools"] = backend["tools"]

        for attempt in range(2):  # one immediate try, one after backoff
            try:
                resp = requests.post(
                    backend["url"], headers=backend["headers"],
                    params=backend["params"], json=body, timeout=timeout,
                )
                status = resp.status_code
                data = resp.json() if resp.content else {}
            except Exception as e:
                logger.warning("%s request failed: %s", backend["name"], e)
                last_status, last_data = 0, {}
                break  # network-level failure: go straight to the next backend

            if status == 200:
                _rate_limited_until.pop(backend["name"], None)  # recovered
                return status, data

            last_status, last_data = status, data
            if status == 429:
                saw_rate_limit = True
                if attempt == 0:
                    logger.info("%s rate-limited (429); backing off before retry", backend["name"])
                    time.sleep(3)
                    continue
                # Still limited after a backoff: stop re-probing this
                # backend for a while so later calls fail over immediately
                # instead of each paying a wasted request + sleep.
                _rate_limited_until[backend["name"]] = time.monotonic() + RATE_LIMIT_COOLDOWN_SECONDS
                logger.warning(
                    "%s still rate-limited after backoff; skipping it for %ds and failing over",
                    backend["name"], RATE_LIMIT_COOLDOWN_SECONDS,
                )
            else:
                logger.warning("%s returned HTTP %s", backend["name"], status)
            break  # non-200 and out of retries for this backend

    # Every backend exhausted. Only alert for a genuine capacity problem
    # (a 429 somewhere), not for e.g. a malformed-request 400.
    if saw_rate_limit and db.claim_ai_limit_alert():
        from .digest import send_ai_limit_alert
        names = " and ".join(b["name"] for b in backends)
        send_ai_limit_alert(f"All AI backends ({names}) returned HTTP 429 (rate limit/quota exceeded).")

    return last_status, last_data


def _extract_text(data: dict) -> str:
    return "".join(
        part.get("text", "")
        for candidate in data.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
    )


def matches_experience_level(
    title: str,
    description: str,
    min_years: int = 2,
    max_years: int = 4,
    degree: str = "Bachelor's degree in Computer Science",
) -> bool:
    """AI-judges a job against two things ONLY, from the description content:

    1. Required experience falls roughly within min_years-max_years of
       professional software/IT experience (SDE-2 equivalent) — not the job
       title, explicitly not the specific tech stack (a "Cloud Engineer" or
       "Platform Engineer" posting requiring 2-4 years matches just as well
       as a "Software Engineer" one; keyword/title filtering already
       narrowed candidates to engineering roles before this ever runs).
    2. The required EDUCATION LEVEL is satisfied by `degree` — e.g. a
       posting requiring a Master's or PhD is rejected, one requiring "a
       Bachelor's degree" or "equivalent practical experience" is not. This
       is a degree-LEVEL check only — never match against specific skills,
       projects, or work history; that's out of scope by design.

    Returns True — i.e. doesn't reject the job — whenever it can't actually
    determine an answer (no description to evaluate, AI unavailable, budget
    exhausted, call failed). The deterministic filters in filters.py already
    did the real narrowing; this is a secondary refinement, not the primary
    gate, so an AI hiccup should never silently drop an otherwise-matching
    job."""
    if not description or not description.strip():
        return True
    if not db.check_and_increment_ai_budget(ai_daily_limit()):
        logger.warning("AI daily call budget (%d) exhausted — skipping experience-level check", ai_daily_limit())
        return True

    prompt = (
        f"You are screening a job posting against a candidate with a {degree}, "
        f"checking TWO things only from the description below:\n\n"
        f"1. REQUIRED EXPERIENCE: does the role need roughly {min_years}-{max_years} years "
        f"of professional software/IT engineering experience (an \"SDE-2\"/\"Software "
        f"Engineer II\" equivalent level)? Judge by the stated requirement, not the job "
        f"title — Cloud Engineer, Backend Engineer, Platform Engineer, DevOps Engineer, "
        f"Infrastructure Engineer all count equally if this is an engineering/IT role. "
        f"Do NOT judge by the specific technology stack (language, framework, cloud "
        f"provider) or exact title wording.\n\n"
        f"2. REQUIRED EDUCATION LEVEL: is a {degree} (or \"Bachelor's or equivalent "
        f"practical experience\") sufficient per the posting's stated minimum "
        f"qualifications? Reject only if the posting explicitly requires a Master's or "
        f"PhD/doctoral degree as a minimum (not just \"preferred\"). Do NOT compare "
        f"against any specific skills, projects, or work history — only the degree level "
        f"stated as a requirement.\n\n"
        f"Job title: {title}\n"
        f"Job description:\n---\n{description[:3000]}\n---\n\n"
        f"Does this job pass BOTH checks? Respond with ONLY \"yes\" or \"no\" as the "
        f"first word."
    )

    # _call_gemini handles its own backoff-retry and cross-backend failover.
    status, data = _call_gemini(prompt, use_search_grounding=False)
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
    if not db.check_and_increment_ai_budget(ai_daily_limit()):
        logger.warning("AI daily call budget (%d) exhausted — skipping reranking", ai_daily_limit())
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

    # _call_gemini handles its own backoff-retry and cross-backend failover.
    status, data = _call_gemini(prompt, use_search_grounding=False)
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
    if not db.check_and_increment_ai_budget(ai_daily_limit()):
        logger.warning("AI daily call budget (%d) exhausted — skipping Gemini discovery", ai_daily_limit())
        return {"status": "budget_exceeded", "urls": []}

    prompt = (
        f"Find the official, current careers/jobs listing page for the company "
        f"\"{company_name}\" (website: {domain}). Respond with ONLY a list of up to "
        f"{count} candidate URLs, one per line, most likely first. No commentary, "
        f"no markdown, just the URLs."
    )

    # _call_gemini handles its own backoff-retry and cross-backend failover,
    # so a 429 surfacing here means EVERY backend is genuinely rate-limited.
    status, data = _call_gemini(prompt, use_search_grounding=True)
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
