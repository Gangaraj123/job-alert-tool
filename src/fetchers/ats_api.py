"""Tier 1: direct JSON APIs for each supported ATS.

Every function takes a board identifier/slug (from detector.detect_ats) and
returns a list of RAW job dicts with keys: title, location, url, description.
Normalization into the final {id, company, title, location, url, description}
shape happens in normalize.py.

Workday has no stable public API contract across tenants, so it's best-effort:
on any failure it raises FetchError, and the pipeline falls through to the
next tier rather than treating it as fatal.
"""
from __future__ import annotations

import logging

from .base import FetchError, http_get_json

logger = logging.getLogger("job_alert.fetchers.ats_api")

SUPPORTED = {
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
    "workday",
    "recruitee",
}

# ATS types with a direct, guessable "company-slug -> board" API — tried
# without ever touching the company's own domain. This matters: a company
# can have active bot-protection (Akamai/Cloudflare WAF) blocking both plain
# HTTP and headless-browser fetches of their own site, while their ATS board
# (hosted on Greenhouse/Lever/etc.'s infrastructure, not theirs) is wide
# open. Workday and Recruitee are excluded — their URLs need a site/tenant
# host variant that can't be guessed from a slug alone.
_GUESSABLE_ATS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters")

_BOARD_URL_TEMPLATES = {
    "greenhouse": "https://boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "workable": "https://apply.workable.com/{slug}",
    "smartrecruiters": "https://careers.smartrecruiters.com/{slug}",
}


def _slug_candidates(company_name: str, domain: str) -> list[str]:
    import re as _re

    candidates = []
    name_clean = _re.sub(r"[^a-z0-9\s-]", "", company_name.lower()).strip()
    if name_clean:
        candidates.append(name_clean.replace(" ", ""))
        candidates.append(name_clean.replace(" ", "-"))

    domain_label = domain.split(".")[0].lower()
    if domain_label:
        candidates.append(domain_label)

    seen = set()
    out = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def probe_board(company_name: str, domain: str, timeout_each: float = 6.0) -> dict | None:
    """Fast, parallel variant of guess_board for interactive use.

    guess_board walks slug x ATS combinations one at a time, which is fine
    inside a background pipeline run but far too slow to call while someone
    waits on a search box. This fires every combination at once and takes
    the first real hit, so the Add-a-company list can show "Greenhouse ·
    144 roles" against each result before anything is selected.

    Returns {ats_type, slug, board_url, job_count} or None. Never raises —
    a probe failing just means "no answer yet", not an error worth showing."""
    combos = [(ats, slug) for slug in _slug_candidates(company_name, domain) for ats in _GUESSABLE_ATS]
    if not combos:
        return None

    def _one(combo):
        ats_type, slug = combo
        try:
            jobs = fetch(ats_type, slug)
        except Exception:
            return None
        if not jobs:
            return None
        return {
            "ats_type": ats_type,
            "slug": slug,
            "board_url": _BOARD_URL_TEMPLATES[ats_type].format(slug=slug),
            "job_count": len(jobs),
        }

    import concurrent.futures as _cf

    try:
        with _cf.ThreadPoolExecutor(max_workers=min(10, len(combos))) as pool:
            for result in pool.map(_one, combos, timeout=timeout_each * 2):
                if result:
                    return result
    except Exception:
        return None
    return None


def guess_board(company_name: str, domain: str) -> tuple[str, str, str, list[dict]] | None:
    """Tries obvious slug variants of the company name/domain against every
    directly-guessable ATS. Returns (ats_type, slug, board_url, jobs) on the
    first one that actually has jobs, or None. Pure API calls — no
    rendering, no AI, and crucially no request to the company's own domain
    at all, so it works even when that domain has bot-protection blocking
    every other tier."""
    for slug in _slug_candidates(company_name, domain):
        for ats_type in _GUESSABLE_ATS:
            try:
                jobs = fetch(ats_type, slug)
            except FetchError:
                continue
            if jobs:
                return ats_type, slug, _BOARD_URL_TEMPLATES[ats_type].format(slug=slug), jobs
    return None


def fetch(ats_type: str, identifier: str, **kwargs) -> list[dict]:
    fn = {
        "greenhouse": fetch_greenhouse,
        "lever": fetch_lever,
        "ashby": fetch_ashby,
        "workable": fetch_workable,
        "smartrecruiters": fetch_smartrecruiters,
        "workday": fetch_workday,
        "recruitee": fetch_recruitee,
    }.get(ats_type)
    if fn is None:
        raise FetchError(f"Unsupported ATS type: {ats_type}")
    return fn(identifier, **kwargs)


def fetch_greenhouse(slug: str, **_) -> list[dict]:
    try:
        data = http_get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        )
    except Exception as e:
        raise FetchError(f"greenhouse: {e}") from e

    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name"),
            "url": j.get("absolute_url", ""),
            "description": j.get("content", ""),
        })
    return jobs


def fetch_lever(slug: str, **_) -> list[dict]:
    try:
        data = http_get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    except Exception as e:
        raise FetchError(f"lever: {e}") from e

    jobs = []
    for j in data:
        categories = j.get("categories", {}) or {}
        jobs.append({
            "title": j.get("text", ""),
            "location": categories.get("location"),
            "url": j.get("hostedUrl", ""),
            "description": j.get("descriptionPlain") or j.get("description", ""),
        })
    return jobs


def fetch_ashby(slug: str, **_) -> list[dict]:
    try:
        data = http_get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false"
        )
    except Exception as e:
        raise FetchError(f"ashby: {e}") from e

    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "title": j.get("title", ""),
            "location": j.get("location"),
            "url": j.get("jobUrl", ""),
            "description": j.get("descriptionHtml") or j.get("descriptionPlain", ""),
        })
    return jobs


def fetch_workable(slug: str, **_) -> list[dict]:
    try:
        data = http_get_json(
            f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
        )
    except Exception as e:
        raise FetchError(f"workable: {e}") from e

    jobs = []
    for j in data.get("jobs", []):
        loc = j.get("location") or {}
        location = ", ".join(
            filter(None, [loc.get("city"), loc.get("region"), loc.get("country")])
        )
        jobs.append({
            "title": j.get("title", ""),
            "location": location or None,
            "url": j.get("url", ""),
            "description": j.get("description", ""),
        })
    return jobs


def fetch_smartrecruiters(slug: str, **_) -> list[dict]:
    try:
        data = http_get_json(
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        )
    except Exception as e:
        raise FetchError(f"smartrecruiters: {e}") from e

    jobs = []
    for j in data.get("content", []):
        loc = j.get("location") or {}
        location = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
        jobs.append({
            "title": j.get("name", ""),
            "location": location or None,
            "url": j.get("ref") or j.get("applyUrl", ""),
            "description": j.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", ""),
        })
    return jobs


def fetch_workday(identifier: str, site: str | None = None, **_) -> list[dict]:
    """Best-effort: Workday's CXS API shape is not officially public and
    varies by tenant, so any failure here just surfaces as a FetchError and
    the pipeline falls through to the next tier for this company.

    `identifier` is "tenant:site:host" as encoded by detector.py (host is
    the wd1/wd3/... variant actually seen in this company's URL — hardcoding
    wd1 for every tenant was wrong, since Workday assigns different regional
    host numbers per tenant). Falls back to plain-tenant + "External"/"wd1"
    defaults if an older, pre-migration identifier (just the tenant) is
    passed in."""
    if ":" in identifier:
        tenant, site_from_id, host = identifier.split(":", 2)
        site = site or site_from_id
    else:
        tenant = identifier
        host = "wd1"
    site = site or "External"
    url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    try:
        data = http_get_json(
            url, headers={"Content-Type": "application/json"},
            json={"appliedFacets": {}, "limit": 50, "offset": 0, "searchText": ""},
        )
    except Exception as e:
        raise FetchError(f"workday: {e}") from e

    jobs = []
    for j in data.get("jobPostings", []):
        jobs.append({
            "title": j.get("title", ""),
            "location": j.get("locationsText"),
            "url": f"https://{tenant}.{host}.myworkdayjobs.com/{site}{j.get('externalPath', '')}",
            "description": "",  # requires a per-job detail call; skipped for cost
        })
    return jobs


def fetch_recruitee(slug: str, **_) -> list[dict]:
    try:
        data = http_get_json(f"https://{slug}.recruitee.com/api/offers/")
    except Exception as e:
        raise FetchError(f"recruitee: {e}") from e

    jobs = []
    for j in data.get("offers", []):
        jobs.append({
            "title": j.get("title", ""),
            "location": j.get("location"),
            "url": j.get("careers_url", ""),
            "description": j.get("description", ""),
        })
    return jobs
