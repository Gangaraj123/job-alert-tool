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
