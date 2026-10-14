"""Small helpers for displaying a company without needing any external
search API or key: derive its domain from the career-page URL, and build a
favicon URL from Google's public (keyless) favicon endpoint."""
from __future__ import annotations

from urllib.parse import urlparse


def domain_from_url(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.removeprefix("www.")


def favicon_url(url: str, size: int = 64) -> str:
    domain = domain_from_url(url)
    return f"https://www.google.com/s2/favicons?domain={domain}&sz={size}"
