"""One-hop link discovery: a careers landing page (e.g. stripe.com/careers)
often has zero job postings itself — the real listing is behind a button
like "Search open roles" (e.g. stripe.com/careers/search). Rather than guess
more URL patterns, this reads the actual page and follows links that look
job-related, so discovery generalizes to arbitrary site structures instead
of a fixed guess list.

Every link found here is still validated the same way as any other
candidate in pipeline.discover_career_url — we never trust that a link
"looks right", only that fetching it actually returns real postings.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .fetchers.base import FetchError, http_get

_JOB_LINK_HINTS = (
    "job", "career", "opening", "position", "role", "vacanc",
    "search", "open-roles", "openroles", "view-all", "see-all",
)


def find_job_related_links(page_url: str, limit: int = 8) -> list[str]:
    try:
        resp = http_get(page_url)
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    base_domain = urlparse(page_url).netloc

    candidates: list[str] = []
    seen: set[str] = {page_url}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        text = a.get_text(" ", strip=True).lower()
        haystack = f"{href.lower()} {text}"
        if not any(hint in haystack for hint in _JOB_LINK_HINTS):
            continue

        absolute = urljoin(page_url, href)
        # Stay on the same company's domain (or a known ATS domain it might
        # link out to) — don't follow unrelated outbound links.
        if urlparse(absolute).netloc != base_domain and "ashbyhq" not in absolute \
                and "greenhouse" not in absolute and "lever.co" not in absolute \
                and "workable" not in absolute and "smartrecruiters" not in absolute \
                and "myworkdayjobs" not in absolute and "recruitee" not in absolute:
            continue

        if absolute not in seen:
            seen.add(absolute)
            candidates.append(absolute)
            if len(candidates) >= limit:
                break

    return candidates
