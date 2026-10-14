"""Identifies which ATS (if any) serves a company's career page.

Strategy: first try to match known ATS URL patterns against the career page
URL itself. If that fails (most companies put jobs on their own domain and
only embed/link to the ATS), fetch the page HTML and search it for the same
patterns in links/iframes/scripts. Detection is best-effort: if nothing
matches, callers simply skip the ATS-API fetch tier and fall through to
JSON-LD/sitemap or Playwright — a failed detection is never fatal.
"""
from __future__ import annotations

import logging
import re

from .fetchers.base import FetchError, http_get

logger = logging.getLogger("job_alert.detector")

# (ats_type, regex with a named group `slug` capturing the board identifier)
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:boards\.greenhouse\.io|job-boards\.greenhouse\.io)/(?P<slug>[\w-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/(?P<slug>[\w-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/(?P<slug>[\w-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/(?P<slug>[\w-]+)")),
    ("smartrecruiters", re.compile(r"careers\.smartrecruiters\.com/(?P<slug>[\w-]+)")),
    ("workday", re.compile(r"(?P<slug>[\w-]+)\.(?:wd\d+|myworkdayjobs)\.com/(?:en-US/)?(?P<site>[\w-]+)")),
    ("recruitee", re.compile(r"(?P<slug>[\w-]+)\.recruitee\.com")),
]


def detect_from_url(url: str) -> tuple[str, str] | None:
    for ats_type, pattern in PATTERNS:
        m = pattern.search(url)
        if m:
            return ats_type, m.group("slug")
    return None


def detect_from_html(html: str) -> tuple[str, str] | None:
    for ats_type, pattern in PATTERNS:
        m = pattern.search(html)
        if m:
            return ats_type, m.group("slug")
    return None


def detect_ats(url: str) -> tuple[str, str] | None:
    """Returns (ats_type, identifier) or None if undetectable."""
    direct = detect_from_url(url)
    if direct:
        logger.info("ATS detected from URL: %s (%s)", direct[0], direct[1])
        return direct

    try:
        resp = http_get(url)
    except (FetchError, Exception) as e:  # detection failure is non-fatal
        logger.warning("Could not fetch %s for ATS detection: %s", url, e)
        return None

    found = detect_from_html(resp.text)
    if found:
        logger.info("ATS detected from page content: %s (%s)", found[0], found[1])
    else:
        logger.info("No known ATS detected for %s", url)
    return found
