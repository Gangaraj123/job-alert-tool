"""CLI entry point.

Usage:
    python -m src.main                  # full daily run (fetch, filter, email digest)
    python -m src.main --dry-run        # full run, but skip the email send
    python -m src.main --no-email       # alias for --dry-run
    python -m src.main --test-company "Stripe"   # debug fetchers for one company
    python -m src.main --seed           # load companies.seed.yaml into the DB once

    # Used by the scheduled Claude Code discovery routine:
    python -m src.main --list-broken             # companies whose last check failed
    python -m src.main --verify-url "<url>"      # does this URL yield real jobs?
    python -m src.main --set-url "Name" "<url>"  # save a verified careers URL
"""
from __future__ import annotations

import argparse
import json

from . import db
from .config import load_seed_companies
from .logging_setup import setup_logging
from .pipeline import preview_detect_and_fetch, run_pipeline, run_test_company


def list_broken() -> None:
    """Companies the deterministic pipeline couldn't fetch. Printed as JSON
    so the discovery routine can parse it rather than scrape log text."""
    db.init_schema()
    broken = [
        {
            "name": c["name"],
            "current_url": c["url"],
            "last_error": (c.get("last_error") or "")[:300],
        }
        for c in db.list_companies(enabled_only=True)
        if c.get("last_status") == "error"
    ]
    print(json.dumps(broken, indent=2))


def verify_url(url: str) -> None:
    """Check a candidate careers URL through the real fetch tiers. The
    discovery routine must call this before --set-url so a plausible-looking
    but wrong URL never reaches the database."""
    db.init_schema()
    result = preview_detect_and_fetch(url)
    print(json.dumps({
        "url": url,
        "ok": bool(result["ok"] and result["job_count"] > 0),
        "job_count": result["job_count"],
        "ats_type": result["ats_type"],
        "tier": result["tier"],
        "error": result.get("error"),
    }, indent=2))


def set_url(name: str, url: str) -> None:
    """Point a company at a new careers URL, but only if it actually yields
    jobs — verification happens here too, so this is safe to call directly
    and can't be talked into storing a dead URL."""
    db.init_schema()
    company = db.get_company_by_name(name)
    if not company:
        print(json.dumps({"ok": False, "error": f"No company named {name!r}"}))
        return

    result = preview_detect_and_fetch(url)
    if not (result["ok"] and result["job_count"] > 0):
        print(json.dumps({
            "ok": False,
            "error": f"URL yielded no jobs, not saving: {result.get('error')}",
        }, indent=2))
        return

    db.update_company(
        company["id"], url=url,
        ats_type=result["ats_type"], ats_identifier=result["ats_identifier"],
        ats_detected_at=db._now(),
    )
    db.set_company_run_status(company["id"], "ok", job_count=result["job_count"])
    print(json.dumps({
        "ok": True, "name": name, "url": url,
        "ats_type": result["ats_type"], "job_count": result["job_count"],
    }, indent=2))


def seed_companies() -> None:
    db.init_schema()
    seeds = load_seed_companies()
    if not seeds:
        print("No companies.seed.yaml found or it's empty — nothing to seed.")
        return
    for entry in seeds:
        db.upsert_company_seed(entry["name"], entry["url"])
    print(f"Seeded {len(seeds)} companies (existing names were left untouched).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Job alert pipeline")
    parser.add_argument("--test-company", metavar="NAME", help="Debug fetchers for a single company (no DB writes, no notify)")
    parser.add_argument("--dry-run", action="store_true", help="Run the full pipeline but skip sending the email digest")
    parser.add_argument("--no-email", action="store_true", help="Alias for --dry-run")
    parser.add_argument("--seed", action="store_true", help="Load companies.seed.yaml into the DB (one-time bootstrap)")
    parser.add_argument("--list-broken", action="store_true", help="JSON list of companies whose last check failed")
    parser.add_argument("--verify-url", metavar="URL", help="Check whether a candidate careers URL yields real jobs")
    parser.add_argument("--set-url", nargs=2, metavar=("NAME", "URL"), help="Save a careers URL for a company (verified first)")
    args = parser.parse_args()

    setup_logging()

    try:
        if args.seed:
            seed_companies()
        elif args.list_broken:
            list_broken()
        elif args.verify_url:
            verify_url(args.verify_url)
        elif args.set_url:
            set_url(args.set_url[0], args.set_url[1])
        elif args.test_company:
            run_test_company(args.test_company)
        else:
            run_pipeline(dry_run=args.dry_run, no_email=args.no_email)
    finally:
        # libsql_client keeps a background thread alive until closed, which
        # would otherwise hang the process after the script "finishes".
        db.close_client()


if __name__ == "__main__":
    main()
