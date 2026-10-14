"""Cheap pre-filter applied before any AI scoring, to avoid spending Claude
tokens on obviously irrelevant postings."""
from __future__ import annotations


def _matches_any(haystack: str, needles: list[str]) -> bool:
    haystack = haystack.lower()
    return any(n.lower() in haystack for n in needles)


def passes_filters(job: dict, filters_cfg: dict) -> bool:
    keywords = filters_cfg.get("keywords") or []
    locations = filters_cfg.get("locations") or []
    always_allow_remote = filters_cfg.get("always_allow_remote", True)

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
