"""Orchestrates one full run: detect ATS -> tiered fetch -> normalize ->
filter -> dedupe -> email digest.

Every company is processed inside its own try/except so one broken fetcher
never aborts the run for the rest ("per-company error isolation"). Companies
with no known ATS and no JSON-LD data just show up in the digest's "broken
fetchers" section for manual checking — there's no AI fallback tier.
"""
from __future__ import annotations

import logging

from . import db
from .config import load_config
from .detector import detect_ats
from .digest import build_digest_html, send_email_digest
from .filters import filter_jobs
from .fetchers import ats_api, jsonld_sitemap, playwright_render
from .fetchers.base import FetchError
from .link_crawl import find_job_related_links
from .normalize import normalize_jobs
from .webutil import domain_from_url, find_career_urls_via_gemini

logger = logging.getLogger("job_alert.pipeline")


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
    """Tries the ATS API, then JSON-LD/sitemap (which follows pagination),
    then a rendered-browser pass for JS-only career portals.

    The ATS API tier is authoritative: once we know the right board, a
    successful call that returns zero jobs means the company genuinely has
    no open roles right now — that's real signal, not a failure, so it's
    returned as-is (empty list included) rather than falling through to the
    next tier. JSON-LD/rendering, by contrast, finding nothing is ambiguous
    (could just mean "this tier doesn't apply here"), so those tiers only
    count as a result when they find at least one job — zero there falls
    through to the next tier instead.

    Raises FetchError (aggregating all tier errors) only if every tier
    either errors or is ambiguous-empty — the caller marks the company as
    broken rather than treating this as fatal for the whole run."""
    errors = []

    if company.get("ats_type") in ats_api.SUPPORTED:
        try:
            jobs = ats_api.fetch(
                company["ats_type"], company["ats_identifier"], site=company.get("ats_site")
            )
            return jobs, "ats_api"  # authoritative: trust it even if empty
        except FetchError as e:
            errors.append(str(e))

    try:
        jobs = jsonld_sitemap.fetch(company["url"])
        if jobs:
            return jobs, "jsonld_sitemap"
    except FetchError as e:
        errors.append(str(e))

    try:
        jobs = playwright_render.fetch(company["url"])
        if jobs:
            return jobs, "playwright_render"
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


def discover_career_url(domain: str, company_name: str | None = None) -> dict:
    """Given just a domain (from the company-name search, not a career page
    URL), finds and validates the real careers page. AI-first:

    1. Gemini with Google Search grounding — it's actually looking at live
       web results, not guessing from training data, so it generalizes to
       arbitrary companies (unlike fixed URL patterns).
    2. A handful of common URL patterns as a free fallback, used when Gemini
       isn't configured, is rate-limited, or genuinely finds nothing.

    Every candidate from either tier is validated the same way regardless of
    source: we actually try fetching jobs from it, never trusted on the
    model's word — a result only counts as "found" if it returns real
    postings.

    Returns {found, url, ats_type, tier, job_count, attempted, gemini_status}."""
    attempted = []
    seen_domains = {domain}

    gemini = find_career_urls_via_gemini(company_name or domain, domain)
    for url in gemini["urls"]:
        candidate_domain = domain_from_url(url)
        if candidate_domain in seen_domains:
            continue
        seen_domains.add(candidate_domain)

        result = preview_detect_and_fetch(url)
        attempted.append({"url": url, **result})
        if result["ok"] and result["job_count"] > 0:
            return {"found": True, "url": url, **result, "attempted": attempted, "gemini_status": gemini["status"]}

    candidates = [
        f"https://{domain}/careers",
        f"https://{domain}/jobs",
        f"https://careers.{domain}",  # many large companies (e.g. Google) use a subdomain
        f"https://jobs.{domain}",
        f"https://{domain}",
    ]
    for url in candidates:
        result = preview_detect_and_fetch(url)
        attempted.append({"url": url, **result})
        if result["ok"] and result["job_count"] > 0:
            return {"found": True, "url": url, **result, "attempted": attempted, "gemini_status": gemini["status"]}

    # Last resort: a careers "hub" page (e.g. stripe.com/careers) often has
    # zero postings itself and links out to the real listing (e.g.
    # stripe.com/careers/search via a "Search open roles" button). Read the
    # actual page and follow links that look job-related, instead of
    # guessing more fixed paths.
    tried_urls = {a["url"] for a in attempted}
    hub_candidates = [f"https://{domain}/careers", f"https://{domain}"]
    link_candidates: list[str] = []
    for hub in hub_candidates:
        for link in find_job_related_links(hub):
            if link not in tried_urls and link not in link_candidates:
                link_candidates.append(link)

    for url in link_candidates:
        result = preview_detect_and_fetch(url)
        attempted.append({"url": url, **result})
        if result["ok"] and result["job_count"] > 0:
            return {"found": True, "url": url, **result, "attempted": attempted, "gemini_status": gemini["status"]}

    return {"found": False, "url": None, "attempted": attempted, "gemini_status": gemini["status"]}


def run_test_company(name: str) -> None:
    """Debug helper: runs every tier independently (does not stop at first
    success) and prints per-tier results. Does not write anything to the DB."""
    db.init_schema()
    company = db.get_company_by_name(name)
    if not company:
        logger.error("No company named %r in the DB. Add it via the UI or --seed first.", name)
        return

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
        for j in jobs[:5]:
            print(f"    - {j['title']} ({j.get('location')})")
    except FetchError as e:
        print(f"[jsonld_sitemap] FAILED — {e}")

    print()


def run_pipeline(dry_run: bool = False, no_email: bool = False, triggered_by: str = "cron") -> dict:
    """Runs one full pass. Returns a stats dict (also persisted as a row in
    the `runs` table) so the UI can show run history and per-run results."""
    import time as _time

    db.init_schema()
    cfg = load_config()
    companies = db.list_companies(enabled_only=True)
    logger.info("Running pipeline for %d enabled companies", len(companies))

    run_id = db.create_run(triggered_by=triggered_by)
    started = _time.monotonic()

    collected: list[dict] = []
    companies_ok = companies_broken = closed_jobs_count = 0

    for company in companies:
        try:
            company = ensure_ats_detected(company, cfg)
            raw_jobs, tier = fetch_company_jobs_tiered(company, cfg)
            normalized = normalize_jobs(raw_jobs, company["name"], tier)
            for j in normalized:
                j["company_id"] = company["id"]
            collected.extend(normalized)
            db.set_company_run_status(company["id"], "ok", job_count=len(normalized))
            closed_jobs_count += db.close_stale_jobs(company["id"], [j["id"] for j in normalized])
            companies_ok += 1
            logger.info("%s: %d job(s) via %s", company["name"], len(normalized), tier)
        except Exception as e:
            logger.error("%s: FAILED — %s", company["name"], e)
            db.set_company_run_status(company["id"], "error", error=str(e))
            companies_broken += 1
            continue  # per-company error isolation: one bad fetcher never aborts the run

    filtered = filter_jobs(collected, db.get_filters())
    new_jobs = [j for j in filtered if not db.job_exists(j["id"])]
    logger.info("%d jobs passed filters, %d are new", len(filtered), len(new_jobs))

    for job in new_jobs:
        db.insert_job(job, run_id=run_id)
    # Every job this run matched, new or already-seen — for full run history.
    db.record_run_jobs(run_id, [j["id"] for j in filtered])

    digest_jobs = db.get_unnotified_jobs()
    broken_companies = [c for c in db.list_companies() if c.get("last_status") == "error"]

    html = build_digest_html(digest_jobs, broken_companies)
    email_sent = False
    if html and not (dry_run or no_email):
        email_sent = send_email_digest(html, len(digest_jobs))
        if email_sent:
            db.mark_jobs_notified([j["id"] for j in digest_jobs])
            logger.info("Digest emailed and %d job(s) marked notified", len(digest_jobs))
        else:
            logger.error("Digest send failed — jobs left unnotified for retry on next run")
    elif html:
        logger.info("Dry run / email disabled — %d job(s) would be in today's digest", len(digest_jobs))
    else:
        logger.info("Nothing to notify about today.")

    duration = _time.monotonic() - started
    db.finish_run(
        run_id, duration, len(companies), companies_ok, companies_broken,
        len(new_jobs), closed_jobs_count,
    )

    return {
        "run_id": run_id,
        "duration_seconds": duration,
        "companies_checked": len(companies),
        "companies_ok": companies_ok,
        "companies_broken": companies_broken,
        "new_jobs_count": len(new_jobs),
        "closed_jobs_count": closed_jobs_count,
        "email_sent": email_sent,
        "new_jobs": new_jobs,
    }
