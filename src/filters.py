"""Cheap pre-filter on role/location/experience, applied before a job is
stored. Filter values come from db.get_filters() — editable from the UI's
Filters page."""
from __future__ import annotations

from .experience import within_experience_range


def _matches_any(haystack: str, needles: list[str]) -> bool:
    haystack = haystack.lower()
    return any(n.lower() in haystack for n in needles)


def passes_filters(job: dict, filters_cfg: dict) -> bool:
    keywords = [*(filters_cfg.get("roles") or []), *(filters_cfg.get("experience_terms") or [])]
    locations = filters_cfg.get("locations") or []
    exclude_terms = filters_cfg.get("exclude_terms") or []
    always_allow_remote = filters_cfg.get("always_allow_remote", True)

    # Checked on the title only — a description mentioning "collaborate with
    # senior engineers" shouldn't reject an otherwise-matching junior role.
    if exclude_terms and _matches_any(job.get("title", ""), exclude_terms):
        return False

    if keywords:
        # Title only. Matching the description too let any role through whose
        # blurb happened to say "software engineering" — "Network Development
        # Engineer" and "Corporate Network Engineering" both passed that way.
        # A job's role is its title; the description describes the work.
        if not _matches_any(job.get("title", ""), keywords):
            return False

    # Experience ceiling. Titles lie about level -- a plain "Software
    # Engineer" at Stripe can want 8+ years -- so this reads the stated
    # minimum out of the description. Postings that don't state one are
    # kept: missing a real match is worse than showing one extra.
    max_years = filters_cfg.get("max_experience_years")
    if max_years:
        if not within_experience_range(job.get("description", ""), int(max_years)):
            return False

    if locations:
        location = (job.get("location") or "").lower()
        if always_allow_remote and "remote" in location:
            return True
        if not _matches_any(location, locations):
            return False

    return True


def filter_jobs(jobs: list[dict], filters_cfg: dict) -> list[dict]:
    return [j for j in jobs if passes_filters(j, filters_cfg)]
