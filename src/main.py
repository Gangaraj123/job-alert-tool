"""CLI entry point.

Usage:
    python -m src.main                  # full daily run (fetch, filter, email digest)
    python -m src.main --dry-run        # full run, but skip the email send
    python -m src.main --no-email       # alias for --dry-run
    python -m src.main --test-company "Stripe"   # debug fetchers for one company
    python -m src.main --seed           # load companies.seed.yaml into the DB once
"""
from __future__ import annotations

import argparse

from . import db
from .config import load_seed_companies
from .logging_setup import setup_logging
from .pipeline import run_pipeline, run_test_company


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
    args = parser.parse_args()

    setup_logging()

    try:
        if args.seed:
            seed_companies()
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
