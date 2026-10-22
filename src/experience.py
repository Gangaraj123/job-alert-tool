"""Deterministic years-of-experience parsing from a job description.

Replaces the AI-based level check, which has been inert since the API keys
were removed. Job postings state their requirement in a small number of
recognisable shapes ("5+ years", "3-7 years", "minimum of 4 years"), so a
parser handles the common cases without a model, an API key, or a bill.

The guiding rule is to fall open: a posting whose requirement cannot be read
is kept, not dropped. Missing a relevant job is far worse than showing one
extra, and plenty of good postings never state a number at all.
"""
from __future__ import annotations

import html
import re

# "5+ years", "3-7 years", "3 to 7 years", "2–12+ years"
_RANGE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:\+|-|–|—|to)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)

# Phrases that introduce a requirement, as opposed to incidental numbers like
# "5 years ago we launched" or "7 years of double-digit growth".
_REQUIREMENT_CONTEXT = re.compile(
    r"(experience|exp\b|background|minimum|at least|requires?|required|"
    r"qualification|proficiency|working|professional|industry|hands[- ]on|"
    r"track record|practice|practising|practicing)",
    re.IGNORECASE,
)

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _plain(text: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", text or "")))


def min_years_required(description: str) -> int | None:
    """The smallest number of years the posting asks for, or None if it
    doesn't say.

    The *smallest* is deliberate. A posting commonly lists a basic
    qualification ("2+ years") and a preferred one ("8+ years"); the basic
    requirement is the bar to clear, so taking the minimum avoids rejecting a
    role for a nice-to-have. A range like "3-7 years" is likewise read as 3.
    """
    text = _plain(description)
    if not text:
        return None

    candidates: list[int] = []
    for m in _RANGE.finditer(text):
        # Only count a number that sits near requirement language; otherwise
        # "founded 10 years ago" would read as a 10-year requirement.
        window = text[max(0, m.start() - 90):m.end() + 60]
        if not _REQUIREMENT_CONTEXT.search(window):
            continue
        low = int(m.group(1))
        # Implausible values are almost always something else (a year, a
        # headcount, a percentage) that happened to sit beside "years".
        if 0 < low <= 25:
            candidates.append(low)

    return min(candidates) if candidates else None


def within_experience_range(description: str, max_years: int) -> bool:
    """True if the posting is plausibly open to someone with `max_years` of
    experience. Unparseable or unstated requirements return True."""
    required = min_years_required(description)
    if required is None:
        return True
    return required <= max_years
