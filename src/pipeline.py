"""Orchestrates one full run: detect ATS -> tiered fetch -> normalize ->
filter -> dedupe -> score -> digest -> notify.

Every company is processed inside its own try/except so one broken fetcher
never aborts the run for the rest ("per-company error isolation").
"""
from __future__ import annotations

import logging

from . import db
from .config import load_config
from .detector import detect_ats
from .digest import build_digest_text, send_telegram_message
from .filters import filter_jobs
from .fetchers import ats_api, jsonld_sitemap, playwright_ai
from .fetchers.base import FetchError
from .normalize import normalize_jobs
from .scorer import score_jobs

logger = logging.getLogger("job_alert.pipeline")

ATS_CACHE_TTL_DAYS = None  # loaded from config at call time


def _ats_is_stale(company: dict, ttl_days: int) -> bool:
    if not company.get("ats_detected_at"):
        return True
    import datetime as _dt
    try:
        detected = _dt.datetime.strptime(company["ats_detected_at"], "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return True
    return (_dt.datetime.utcnow() - detected).days >= ttl_days


def ensure_ats_detected(company: dict, cfg: dict) -> dict:
    """Returns the company dict, refreshed with ats_type/ats_identifier if
    (re)detection ran."""
    ttl_days = cfg.get("fetch", {}).get("ats_cache_ttl_days", 14)
    if company.get("ats_type") and not _ats_is_stale(company, ttl_days):
        return company

    detected = detect_ats(company["url"])
    if detected:
        ats_type, identifier = detected
        db.update_company(
            company["id"],
            ats_type=ats_type,
            ats_identifier=identifier,
            ats_detected_at=db._now(),
        )
        company = {**company, "ats_type": ats_type, "ats_identifier": identifier}
    return company


def fetch_company_jobs_tiered(company: dict, cfg: dict) -> tuple[list[dict], str]:
    """Tries ATS API, then JSON-LD/sitemap, then Playwright+AI, in that
    order, stopping at the first tier that returns at least one job.
    Raises FetchError (aggregating all tier errors) if every tier fails."""
    errors = []

    if company.get("ats_type") in ats_api.SUPPORTED:
        try:
            jobs = ats_api.fetch(
                company["ats_type"], company["ats_identifier"], site=company.get("ats_site")
            )
            if jobs:
                return jobs, "ats_api"
        except FetchError as e:
            errors.append(str(e))

    try:
        jobs = jsonld_sitemap.fetch(company["url"])
        if jobs:
            return jobs, "jsonld_sitemap"
    except FetchError as e:
        errors.append(str(e))

    try:
        jobs = playwright_ai.fetch(company["url"])
        if jobs:
            return jobs, "playwright_ai"
    except FetchError as e:
        errors.append(str(e))

    raise FetchError("; ".join(errors) if errors else "all tiers returned zero jobs")


def preview_detect_and_fetch(url: str) -> dict:
    """Runs detection + the tiered fetch against a bare URL that may not be
    in the DB yet (used by the UI's "Add company" preview and the
    "Re-check now" button). Returns a dict the UI can render directly:
    {ok, ats_type, ats_identifier, tier, job_count, error}."""
    cfg = load_config()
    detected = detect_ats(url)
    ats_type, ats_identifier = detected if detected else (None, None)
    company_like = {"url": url, "ats_type": ats_type, "ats_identifier": ats_identifier}

    try:
        jobs, tier = fetch_company_jobs_tiered(company_like, cfg)
        return {
            "ok": True, "ats_type": ats_type, "ats_identifier": ats_identifier,
            "tier": tier, "job_count": len(jobs), "error": None,
        }
    except FetchError as e:
        return {
            "ok": False, "ats_type": ats_type, "ats_identifier": ats_identifier,
            "tier": None, "job_count": 0, "error": str(e),
        }


def run_test_company(name: str) -> None:
    """Debug helper: runs every tier independently (does not stop at first
    success) and prints per-tier results. Does not write anything to the DB."""
    db.init_schema()
    company = db.get_company_by_name(name)
    if not company:
        logger.error("No company named %r in the DB. Add it via the UI or --seed first.", name)
        return

    cfg = load_config()
    print(f"\n=== Testing {company['name']} ({company['url']}) ===\n")

    detected = detect_ats(company["url"])
    print(f"[detect] {detected if detected else 'no known ATS detected'}")

    if detected:
        ats_type, identifier = detected
        try:
            jobs = ats_api.fetch(ats_type, identifier)
            print(f"[ats_api:{ats_type}] OK — {len(jobs)} job(s)")
        except FetchError as e:
            print(f"[ats_api:{ats_type}] FAILED — {e}")

    try:
        jobs = jsonld_sitemap.fetch(company["url"])
        print(f"[jsonld_sitemap] OK — {len(jobs)} job(s)")
    except FetchError as e:
        print(f"[jsonld_sitemap] FAILED — {e}")

    try:
        jobs = playwright_ai.fetch(company["url"])
        print(f"[playwright_ai] OK — {len(jobs)} job(s)")
        for j in jobs[:5]:
            print(f"    - {j['title']} ({j.get('location')})")
    except FetchError as e:
        print(f"[playwright_ai] FAILED — {e}")

    print()


def run_pipeline(dry_run: bool = False, no_telegram: bool = False) -> None:
    db.init_schema()
    cfg = load_config()
    companies = db.list_companies(enabled_only=True)
    logger.info("Running pipeline for %d enabled companies", len(companies))

    collected: list[dict] = []

    for company in companies:
        try:
            company = ensure_ats_detected(company, cfg)
            raw_jobs, tier = fetch_company_jobs_tiered(company, cfg)
            normalized = normalize_jobs(raw_jobs, company["name"], tier)
            for j in normalized:
                j["company_id"] = company["id"]
            collected.extend(normalized)
            db.set_company_run_status(company["id"], "ok", job_count=len(normalized))
            logger.info("%s: %d job(s) via %s", company["name"], len(normalized), tier)
        except Exception as e:
            logger.error("%s: FAILED — %s", company["name"], e)
            db.set_company_run_status(company["id"], "error", error=str(e))
            continue  # per-company error isolation: one bad fetcher never aborts the run

    filtered = filter_jobs(collected, cfg.get("filters", {}))
    new_jobs = [j for j in filtered if not db.job_exists(j["id"])]
    logger.info("%d jobs passed filters, %d are new", len(filtered), len(new_jobs))

    for job in new_jobs:
        db.insert_job(job)

    scored = score_jobs(new_jobs)
    for job, score, error in scored:
        if score:
            db.update_job_score(
                job["id"], score["fit_score"], score["why_it_fits"],
                score["gaps"], score["red_flags"], score["priority"],
            )
        else:
            logger.warning("Could not score %s (%s): %s", job["id"], job["title"], error)

    min_score = cfg.get("scoring", {}).get("min_fit_score_for_digest", 60)
    digest_jobs = db.get_unnotified_scored_jobs(min_score)
    broken_companies = [c for c in db.list_companies() if c.get("last_status") == "error"]

    digest_text = build_digest_text(digest_jobs, broken_companies)
    if not digest_text:
        logger.info("Nothing to notify about today.")
        return

    if dry_run or no_telegram:
        logger.info("Dry run / Telegram disabled — digest below:\n%s", digest_text)
        return

    if send_telegram_message(digest_text):
        db.mark_jobs_notified([j["id"] for j in digest_jobs])
        logger.info("Digest sent and %d job(s) marked notified", len(digest_jobs))
    else:
        logger.error("Digest send failed — jobs left unnotified for retry on next run")
