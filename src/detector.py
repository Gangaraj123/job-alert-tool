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
    ("workday", re.compile(r"(?P<slug>[\w-]+)\.(?P<host>wd\d+|myworkdayjobs)\.com/(?:en-US/)?(?P<site>[\w-]+)")),
    ("recruitee", re.compile(r"(?P<slug>[\w-]+)\.recruitee\.com")),
    # Self-hosted boards that still expose a usable public JSON API. The
    # slug is a country code rather than a tenant name, so the default
    # below is what gets used unless a caller overrides it.
    ("amazon", re.compile(r"(?:www\.)?amazon\.jobs(?P<slug>)")),
]


def _identifier_from_match(ats_type: str, m: re.Match) -> str:
    if ats_type == "amazon":
        # Amazon's catalogue is global and far larger than the API will
        # page through, so it is scoped by country; India by default.
        return "IND"
    if ats_type == "workday":
        # Workday needs tenant + site + host variant (wd1/wd3/...) to build
        # correct URLs — encoded into one identifier string so the (ats_type,
        # identifier) 2-tuple contract stays the same for every other ATS
        # and every call site. ats_api.fetch_workday parses this back apart.
        groups = m.groupdict()
        return f"{groups['slug']}:{groups.get('site', 'External')}:{groups.get('host', 'wd1')}"
    return m.group("slug")


def detect_from_url(url: str) -> tuple[str, str] | None:
    for ats_type, pattern in PATTERNS:
        m = pattern.search(url)
        if m:
            return ats_type, _identifier_from_match(ats_type, m)
    return None


def detect_from_html(html: str) -> tuple[str, str] | None:
    for ats_type, pattern in PATTERNS:
        m = pattern.search(html)
        if m:
            return ats_type, _identifier_from_match(ats_type, m)
    return None


def detect_ats(url: str) -> tuple[str, str] | None:
    """Returns (ats_type, identifier) or None if undetectable."""
    if not (url or "").strip():
        # Registry-backed companies are fetched by method alone and carry no
        # careers URL, so there is nothing to detect and nothing wrong.
        return None

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
