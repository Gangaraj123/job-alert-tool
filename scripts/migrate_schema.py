"""One-off schema migration: add foreign keys, drop dead columns, fix indexes.

SQLite can't add constraints to an existing table, so the tables that gain
foreign keys are rebuilt: create the new shape, copy the rows, drop the old,
rename. Safe to re-run — it checks whether the migration already applied and
exits rather than rebuilding a second time.

What changes and why:

* `jobs.company_id` and `jobs.found_in_run_id` gain foreign keys. Nothing
  enforced them before, so deleting a company silently orphaned its jobs —
  a live risk now that the UI has a remove button.

* Deleting a company sets its jobs' `company_id` to NULL rather than
  cascading. The UI promises saved roles stay, and `company_name` is kept
  precisely so a job stays readable after its company is gone. That makes
  the denormalised name a deliberate historical snapshot instead of a field
  that can silently drift.

* Six columns from the removed AI-scoring feature are dropped
  (fit_score, why_it_fits, gaps, red_flags, priority, scored_at), along with
  idx_jobs_priority, an index on one of them.

* `run_jobs` gains both foreign keys with ON DELETE CASCADE and a composite
  primary key. It is the fastest-growing table (already ~10x the jobs table)
  and had no constraints at all.

* Indexes are added for the columns the UI actually filters on.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402

DEAD_COLUMNS = {
    "fit_score", "why_it_fits", "gaps", "red_flags", "priority", "scored_at",
}

JOBS_COLUMNS = [
    "id", "company_id", "company_name", "title", "location", "url",
    "description", "fetch_tier", "first_seen_at", "notified_at",
    "found_in_run_id", "closed_at", "done_at", "posted_at", "dismissed_at",
]

NEW_JOBS_TABLE = """
CREATE TABLE jobs_new (
    id TEXT PRIMARY KEY,
    -- Nullable so a job survives its company being removed; company_name
    -- below is the historical label that keeps it readable.
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    company_name TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    description TEXT,
    fetch_tier TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    notified_at TEXT,
    found_in_run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    closed_at TEXT,
    done_at TEXT,
    posted_at TEXT,
    dismissed_at TEXT
)
"""

NEW_RUN_JOBS_TABLE = """
CREATE TABLE run_jobs_new (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, job_id)
)
"""

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_notified ON jobs(notified_at)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(found_in_run_id)",
    # The open-jobs query filters on all three state columns together.
    "CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(closed_at, done_at, dismissed_at)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(posted_at)",
    "CREATE INDEX IF NOT EXISTS idx_run_jobs_job ON run_jobs(job_id)",
]


def _columns(client, table: str) -> set[str]:
    return {row[1] for row in client.execute(f"PRAGMA table_info({table})").rows}


def _has_foreign_keys(client, table: str) -> bool:
    return bool(client.execute(f"PRAGMA foreign_key_list({table})").rows)


def main() -> int:
    db.init_schema()
    client = db.get_client()

    already = _has_foreign_keys(client, "jobs") and not (
        _columns(client, "jobs") & DEAD_COLUMNS
    )
    if already:
        print("Schema already migrated — nothing to do.")
        db.close_client()
        return 0

    before = {
        t: client.execute(f"SELECT COUNT(*) FROM {t}").rows[0][0]
        for t in ("companies", "jobs", "runs", "run_jobs")
    }
    print("before:", before)

    # Constraints are checked as rows are inserted, so the rebuild runs with
    # enforcement off and is verified explicitly at the end.
    client.execute("PRAGMA foreign_keys = OFF")

    cols = ", ".join(JOBS_COLUMNS)
    statements = [
        NEW_JOBS_TABLE,
        f"INSERT INTO jobs_new ({cols}) SELECT {cols} FROM jobs",
        "DROP TABLE jobs",
        "ALTER TABLE jobs_new RENAME TO jobs",
        NEW_RUN_JOBS_TABLE,
        "INSERT INTO run_jobs_new (run_id, job_id) "
        "SELECT DISTINCT run_id, job_id FROM run_jobs",
        "DROP TABLE run_jobs",
        "ALTER TABLE run_jobs_new RENAME TO run_jobs",
        *INDEXES,
    ]
    for sql in statements:
        client.execute(sql)
        print("  ok:", " ".join(sql.split())[:72])

    client.execute("PRAGMA foreign_keys = ON")

    violations = client.execute("PRAGMA foreign_key_check").rows
    after = {
        t: client.execute(f"SELECT COUNT(*) FROM {t}").rows[0][0]
        for t in ("companies", "jobs", "runs", "run_jobs")
    }
    print("after: ", after)
    print("foreign key violations:", violations or "none")

    # run_jobs may legitimately shrink if duplicate pairs existed; nothing else
    # is allowed to lose rows.
    lost = [t for t in ("companies", "jobs", "runs") if after[t] != before[t]]
    if lost or violations:
        print(f"\nFAILED — row loss in {lost}, violations={violations}")
        db.close_client()
        return 1

    print("\nMigration applied cleanly.")
    db.close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
