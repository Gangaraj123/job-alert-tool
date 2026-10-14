"""Tier 2: JSON-LD JobPosting schema on the career page, with a bounded
sitemap crawl as a fallback for sites that list postings on separate pages.

This tier is cheap (no AI calls) and catches sites that don't use one of the
7 known ATS products but still markup their postings with schema.org
JobPosting (common for SEO reasons).
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..config import load_config
from .base import FetchError, http_get

logger = logging.getLogger("job_alert.fetchers.jsonld_sitemap")

_cfg = load_config().get("fetch", {})
MAX_SITEMAP_URLS = _cfg.get("max_sitemap_urls", 25)

_JOB_PATH_HINT = re.compile(r"/(job|career|position|opening)s?/", re.IGNORECASE)


def _extract_jobpostings_from_html(html: str, page_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "JobPosting":
                jobs.append(_jobposting_to_raw(item, page_url))
            # Some sites nest postings under @graph
            for g in item.get("@graph", []) if isinstance(item.get("@graph"), list) else []:
                if isinstance(g, dict) and g.get("@type") == "JobPosting":
                    jobs.append(_jobposting_to_raw(g, page_url))
    return jobs


def _jobposting_to_raw(item: dict, page_url: str) -> dict:
    location = None
    loc = item.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if isinstance(loc, dict):
        address = loc.get("address", {})
        if isinstance(address, dict):
            location = ", ".join(filter(None, [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ])) or None
    if not location and item.get("applicantLocationRequirements"):
        location = "Remote"

    url = item.get("url") or page_url
    return {
        "title": item.get("title", ""),
        "location": location,
        "url": urljoin(page_url, url),
        "description": item.get("description", ""),
    }


def _discover_sitemap_job_urls(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    for sitemap_path in ("/sitemap.xml", "/sitemap_index.xml"):
        try:
            resp = http_get(root + sitemap_path)
        except Exception:
            continue
        try:
            soup = BeautifulSoup(resp.text, "xml")
        except Exception:
            continue
        locs = [loc.text for loc in soup.find_all("loc")]
        job_urls = [u for u in locs if _JOB_PATH_HINT.search(u)]
        if job_urls:
            return job_urls[:MAX_SITEMAP_URLS]
    return []


def fetch(career_page_url: str, **_) -> list[dict]:
    try:
        resp = http_get(career_page_url)
    except Exception as e:
        raise FetchError(f"jsonld_sitemap: could not fetch {career_page_url}: {e}") from e

    jobs = _extract_jobpostings_from_html(resp.text, career_page_url)
    if jobs:
        logger.info("jsonld: found %d JobPosting entries on career page", len(jobs))
        return jobs

    # Fallback: crawl a bounded set of sitemap URLs that look like job pages
    job_urls = _discover_sitemap_job_urls(career_page_url)
    for url in job_urls:
        try:
            page = http_get(url)
        except Exception as e:
            logger.debug("sitemap crawl: skipping %s (%s)", url, e)
            continue
        jobs.extend(_extract_jobpostings_from_html(page.text, url))

    if not jobs:
        raise FetchError("jsonld_sitemap: no JobPosting data found")
    logger.info("jsonld: found %d JobPosting entries via sitemap crawl", len(jobs))
    return jobs
