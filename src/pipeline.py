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
from . import webutil
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
        # Renders once; tries structured data first, then (if that's empty)
        # AI reading of the same rendered page's visible text — see
        # playwright_render.py for why both live in one tier.
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


def discover_career_url(
    domain: str,
    company_name: str | None = None,
    max_seconds: float = 90,
    on_progress=None,
) -> dict:
    """Given just a domain (from the company-name search, not a career page
    URL), finds and validates the real careers page:

    0. A direct ATS board guessed from the company name/domain (Greenhouse/
       Lever/Ashby/Workable/SmartRecruiters) — free, instant, and never
       touches the company's own domain, so it works even when that domain
       has bot-protection blocking everything else.
    1. Gemini with Google Search grounding — it's actually looking at live
       web results, not guessing from training data, so it generalizes to
       arbitrary companies (unlike fixed URL patterns).
    2. A handful of common URL patterns as a free fallback, used when Gemini
       isn't configured, is rate-limited, or genuinely finds nothing.
    3. Following real job-related links found on a "hub" page.

    Every candidate from any tier is validated the same way: we actually try
    fetching jobs from it, never trusted on the model's word — a result only
    counts as "found" if it returns real postings.

    This can chain through many slow network calls (each candidate retries
    on connection errors, and the rendering tier can take real time), so
    it's bounded by a hard wall-clock budget (`max_seconds`) rather than
    running every candidate regardless of how long it takes — once the
    budget is spent, remaining candidates are skipped and whatever was found
    so far (or "not found") is returned. `on_progress(message)`, if given,
    is called before each attempt so a caller (e.g. the UI) can show live
    status instead of a single static spinner for the whole call.

    Returns {found, url, ats_type, tier, job_count, attempted, gemini_status, timed_out}."""
    import time as _time

    started = _time.monotonic()
    attempted = []
    tried_urls: set[str] = set()  # exact-URL dedup across ALL tiers — a URL
    # guessed by patterns that Gemini already suggested (or vice versa) must
    # never be fetched twice; each attempt costs real seconds of the budget.
    seen_domains = {domain}

    def _out_of_time() -> bool:
        return _time.monotonic() - started > max_seconds

    def _progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    def _try(url: str, gemini_status: str, follow_links: bool = True) -> dict | None:
        if url in tried_urls:
            return None
        tried_urls.add(url)
        _progress(f"Checking {url}…")
        result = preview_detect_and_fetch(url)
        attempted.append({"url": url, **result})
        if result["ok"] and result["job_count"] > 0:
            return {"found": True, "url": url, **result, "attempted": attempted,
                     "gemini_status": gemini_status, "timed_out": False}

        # This page itself has no jobs — but it might be a "hub" page (e.g.
        # stripe.com/careers) linking to the real listing via a "Search open
        # roles" button. Check immediately rather than only as a last resort
        # after every other top-level candidate is exhausted — by then the
        # time budget is usually already spent.
        if follow_links and not _out_of_time():
            _progress(f"Reading {url} for job-related links…")
            for link in find_job_related_links(url):
                if _out_of_time():
                    break
                if (found := _try(link, gemini_status, follow_links=False)):
                    return found
        return None

    # Fastest, cheapest tier first: no AI, no rendering, and crucially no
    # request to the company's own domain at all — just tries obvious slug
    # variants directly against each ATS's own API. This finds companies
    # whose own site blocks us (bot-protection WAFs block plain HTTP *and*
    # headless-browser requests alike) but who still have a wide-open board
    # hosted on the ATS's infrastructure instead of theirs.
    #
    # Run alongside the Gemini discovery call (independent I/O, no reason to
    # make one wait for the other) — when guess_board fails, as it does for
    # any company without a standard ATS, that's ~5s that would otherwise be
    # pure dead time before Gemini even starts.
    import concurrent.futures as _cf

    guess_future = None
    if company_name:
        _progress("Checking for a direct ATS board under the company name…")
        executor = _cf.ThreadPoolExecutor(max_workers=1)
        guess_future = executor.submit(ats_api.guess_board, company_name, domain)

    _progress("Asking Gemini for likely career page URLs…")
    # Each candidate's full validation chain got more thorough (and thus
    # slower) once the render tier gained an AI-extraction fallback, so only
    # the single most likely Gemini suggestion is tried — trying fewer
    # candidates more thoroughly fits the time budget better than trying
    # many candidates shallowly.
    gemini = find_career_urls_via_gemini(company_name or domain, domain, count=1)

    if guess_future:
        guessed = guess_future.result()
        executor.shutdown(wait=False)
        if guessed:
            ats_type, slug, board_url, jobs = guessed
            attempted.append({"url": board_url, "ok": True, "ats_type": ats_type,
                               "ats_identifier": slug, "tier": "ats_api", "job_count": len(jobs), "error": None})
            return {"found": True, "url": board_url, "ok": True, "ats_type": ats_type,
                     "ats_identifier": slug, "tier": "ats_api", "job_count": len(jobs),
                     "attempted": attempted, "gemini_status": gemini["status"], "timed_out": False}

    for url in gemini["urls"]:
        if _out_of_time():
            return {"found": False, "url": None, "attempted": attempted,
                     "gemini_status": gemini["status"], "timed_out": True}
        candidate_domain = domain_from_url(url)
        if candidate_domain in seen_domains:
            continue
        seen_domains.add(candidate_domain)
        if (found := _try(url, gemini["status"])):
            return found

    candidates = [
        f"https://{domain}/careers",
        f"https://{domain}/jobs",
        f"https://careers.{domain}",  # many large companies (e.g. Google) use a subdomain
        f"https://jobs.{domain}",
        f"https://{domain}",
    ]
    for url in candidates:
        if _out_of_time():
            return {"found": False, "url": None, "attempted": attempted,
                     "gemini_status": gemini["status"], "timed_out": True}
        if (found := _try(url, gemini["status"])):
            return found

    return {"found": False, "url": None, "attempted": attempted,
             "gemini_status": gemini["status"], "timed_out": False}


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

    try:
        jobs = playwright_render.fetch(company["url"])
        print(f"[playwright_render] OK — {len(jobs)} job(s)")
        for j in jobs[:5]:
            print(f"    - {j['title']} ({j.get('location')})")
    except FetchError as e:
        print(f"[playwright_render] FAILED — {e}")

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

    def _fetch_one(company: dict) -> tuple[dict, list[dict] | None, str | None]:
        """Network-bound work only — no DB writes, so this is safe to run
        concurrently. Returns (company, normalized_jobs, error)."""
        try:
            company = ensure_ats_detected(company, cfg)
            raw_jobs, tier = fetch_company_jobs_tiered(company, cfg)
            normalized = normalize_jobs(raw_jobs, company["name"], tier)
            for j in normalized:
                j["company_id"] = company["id"]
            logger.info("%s: %d job(s) via %s", company["name"], len(normalized), tier)
            return company, normalized, None
        except Exception as e:
            logger.error("%s: FAILED — %s", company["name"], e)
            return company, None, str(e)

    # Companies are fetched concurrently — each one is almost entirely
    # waiting on network/browser I/O, and they're fully independent, so
    # running them serially made a run take the SUM of every company's
    # time. Bounded to avoid launching an unbounded number of headless
    # browsers at once. DB writes stay on this thread (libsql's client
    # isn't safe to share across threads), so only the fetching overlaps.
    import concurrent.futures as _cf

    max_workers = min(cfg.get("fetch", {}).get("max_concurrent_companies", 4), max(len(companies), 1))
    with _cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(_fetch_one, companies))

    for company, normalized, error in results:
        if error is not None:
            db.set_company_run_status(company["id"], "error", error=error)
            companies_broken += 1
            continue  # per-company error isolation: one bad fetcher never aborts the run
        collected.extend(normalized)
        db.set_company_run_status(company["id"], "ok", job_count=len(normalized))
        closed_jobs_count += db.close_stale_jobs(company["id"], [j["id"] for j in normalized])
        companies_ok += 1

    filtered = filter_jobs(collected, db.get_filters())
    new_jobs = [j for j in filtered if not db.job_exists(j["id"])]
    logger.info("%d jobs passed filters, %d are new", len(filtered), len(new_jobs))

    # AI experience-level check: a secondary refinement on top of the
    # deterministic role/location/exclude filters above, applied only to
    # genuinely new postings (never re-checks an already-seen job) to keep
    # AI usage to a minimum. Judges actual required years of experience from
    # the description, not title/tech-stack — "Cloud Engineer, 2-4 years"
    # matches just as well as "Software Engineer II". Falls open (keeps the
    # job) on anything it can't determine, so an AI hiccup never silently
    # drops a real match.
    new_jobs_to_store = [
        j for j in new_jobs
        if webutil.matches_experience_level(j["title"], j.get("description", ""))
    ]
    if len(new_jobs_to_store) != len(new_jobs):
        logger.info("%d job(s) dropped by AI experience-level check", len(new_jobs) - len(new_jobs_to_store))

    for job in new_jobs_to_store:
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
        len(new_jobs_to_store), closed_jobs_count,
    )

    return {
        "run_id": run_id,
        "duration_seconds": duration,
        "companies_checked": len(companies),
        "companies_ok": companies_ok,
        "companies_broken": companies_broken,
        "new_jobs_count": len(new_jobs_to_store),
        "closed_jobs_count": closed_jobs_count,
        "email_sent": email_sent,
        "new_jobs": new_jobs_to_store,
    }
