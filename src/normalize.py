"""Turns raw per-tier job dicts into the canonical shape used everywhere else:
{id, company, title, location, url, description, fetch_tier}

`id` is a stable hash of (company, title, location, url) so the same posting
seen across multiple runs always dedupes to the same row, even though
different fetch tiers produce slightly different raw shapes.
"""
from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import urlsplit, urlunsplit

MAX_DESCRIPTION_CHARS = 4000


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(value)  # some APIs double-escape entities (&lt;div&gt; etc.)
    text = re.sub(r"<[^>]+>", " ", text)  # strip HTML tags if present
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _canonical_url(url: str) -> str:
    """Drops query string and fragment before hashing, so a tracking param
    an ATS adds/rotates (?gh_src=..., ?utm_source=..., etc.) doesn't make the
    same posting hash as a "new" job — the stored/displayed URL keeps the
    original with params intact; only the hash input is canonicalized."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _stable_id(company: str, title: str, location: str, url: str) -> str:
    key = f"{company}::{title}::{location}::{_canonical_url(url)}".lower()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def normalize_job(raw: dict, company_name: str, fetch_tier: str) -> dict:
    title = _clean_text(raw.get("title"))
    location = _clean_text(raw.get("location")) or None
    url = (raw.get("url") or "").strip()
    description = _clean_text(raw.get("description"))[:MAX_DESCRIPTION_CHARS]

    return {
        "id": _stable_id(company_name, title, location or "", url),
        "company": company_name,
        "title": title,
        "location": location,
        "url": url,
        "description": description,
        "fetch_tier": fetch_tier,
    }


def normalize_jobs(raw_jobs: list[dict], company_name: str, fetch_tier: str) -> list[dict]:
    return [
        normalize_job(j, company_name, fetch_tier)
        for j in raw_jobs
        if (j.get("title") or "").strip()
    ]
