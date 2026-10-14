"""Cheap pre-filter on role/location, applied before a job is stored. Filter
values come from db.get_filters() — editable from the UI's Filters page."""
from __future__ import annotations


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
        text = f"{job.get('title', '')} {job.get('description', '')}"
        if not _matches_any(text, keywords):
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
