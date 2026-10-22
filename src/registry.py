"""Curated company registry.

Adding a company should take a name and nothing else. Auto-detection is slow,
sometimes wrong, and fails outright on big self-hosted boards — so instead we
keep a hand-checked list of companies with a known-good fetch method, and let
anything unknown sit in a `pending` state until we get round to it. A pending
company is never fetched and never counted as broken: it's a to-do, not a
failure.
"""
from __future__ import annotations

import functools
import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger("job_alert.registry")

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "companies.registry.yaml"

# Logos reuse the same keyless favicon service the company search uses, so a
# registry entry and a search result render identically. A missing icon is
# cosmetic — the UI falls back to a lettermark — so 404s need no handling.

PENDING = "pending"
AUTO = "auto"


def logo_for(domain: str | None) -> str | None:
    from .webutil import favicon_url
    return favicon_url(domain) if domain else None


def _normalise(name: str) -> str:
    """Match on name alone, forgivingly — 'amazon', 'Amazon ', 'AMAZON' and
    'Amazon.com' should all find the same entry."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


@functools.lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        logger.warning("No registry at %s — every company will be pending", REGISTRY_PATH)
        return {}
    try:
        raw = yaml.safe_load(REGISTRY_PATH.read_text()) or {}
    except yaml.YAMLError as e:
        # A malformed registry must not take the whole app down; degrade to
        # "everything is pending" and say so loudly.
        logger.error("Registry is not valid YAML (%s) — treating as empty", e)
        return {}

    entries = {}
    for entry in raw.get("companies") or []:
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        entries[_normalise(name)] = {
            "name": name,
            "domain": entry.get("domain"),
            "method": (entry.get("method") or PENDING).strip(),
            "careers_url": entry.get("careers_url"),
        }
    return entries


def lookup(name: str) -> dict | None:
    """The registry entry for a company name, or None if we don't know it."""
    return _load().get(_normalise(name))


def all_entries() -> list[dict]:
    return sorted(_load().values(), key=lambda e: e["name"].lower())


def parse_method(method: str) -> tuple[str | None, str | None]:
    """'greenhouse:databricks' -> ('greenhouse', 'databricks').

    'pending' and 'auto' carry no ATS, so both yield (None, None) and the
    caller decides what that means: skip entirely, or fall through to the
    generic fetch tiers.
    """
    if not method or method in (PENDING, AUTO):
        return None, None
    ats, _, identifier = method.partition(":")
    return ats or None, identifier or None
