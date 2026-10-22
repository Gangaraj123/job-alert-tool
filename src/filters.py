"""Cheap pre-filter on role/location/experience, applied before a job is
stored. Filter values come from db.get_filters() — editable from the UI's
Filters page."""
from __future__ import annotations

import re

from .experience import within_experience_range

# Words that qualify "remote" without restricting it to a country.
_GLOBAL_REMOTE_WORDS = {
    "global", "worldwide", "anywhere", "work from home", "wfh",
    "fully", "fully remote", "remote first", "distributed",
}


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
        location = job.get("location") or ""
        if always_allow_remote and _remote_open_to(location, locations):
            return True
        # "remote" is excluded from the plain substring match below: it is
        # handled by _remote_open_to above, and leaving it in let a rejected
        # "Remote, Canada" pass anyway just by containing the word.
        place_terms = [l for l in locations if l.strip().lower() != "remote"]
        if not _matches_any(location, place_terms):
            return False

    return True


def _remote_open_to(location: str, allowed: list[str]) -> bool:
    """True only for remote roles someone in the allowed locations could take.

    "Remote" alone is open to anyone. "Remote, Canada; Remote, Israel;
    Remote, United Kingdom" is not — it is three country-restricted roles,
    none of them hiring from India, and treating it as remote put jobs in
    the digest that could never be applied for.

    Each semicolon-separated option is judged on its own; one option that
    works is enough.
    """
    for option in location.split(";"):
        option = option.strip()
        if not option:
            continue

        if "remote" not in option.lower():
            # A concrete office location, e.g. "Bengaluru, India".
            if _matches_any(option, allowed):
                return True
            continue

        # Strip the word itself and any separators around it; whatever is
        # left is the restriction, e.g. "Remote, Canada" -> "Canada".
        rest = re.sub(r"\bremote\b", " ", option, flags=re.IGNORECASE)
        rest = re.sub(r"[\s,\-–—/()]+", " ", rest).strip()

        # Unqualified remote: no country named, so no restriction implied.
        if not rest or rest.lower() in _GLOBAL_REMOTE_WORDS:
            return True

        if _matches_any(rest, allowed):
            return True

    return False


def filter_jobs(jobs: list[dict], filters_cfg: dict) -> list[dict]:
    return [j for j in jobs if passes_filters(j, filters_cfg)]
