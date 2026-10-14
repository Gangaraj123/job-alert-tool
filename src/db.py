"""Shared DB layer on Turso (libSQL, SQLite-compatible).

Both the daily pipeline (GitHub Actions) and the Streamlit UI import this
module and talk to the SAME remote database, so company edits made in the UI
are immediately visible to the next cron run, and jobs scraped by the cron
run are immediately visible in the UI.

If TURSO_DATABASE_URL isn't set (e.g. running locally without a Turso
account), falls back to a local file `data/local.db` using the same libsql
client — handy for `--test-company` runs and Streamlit local dev.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

import libsql_client

from .config import ROOT_DIR, load_settings

_client: libsql_client.Client | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    ats_type TEXT,
    ats_identifier TEXT,
    ats_detected_at TEXT,
    last_checked_at TEXT,
    last_status TEXT,
    last_error TEXT,
    last_job_count INTEGER DEFAULT 0,
    logo_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    company_id INTEGER NOT NULL,
    company_name TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    description TEXT,
    fetch_tier TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    notified_at TEXT,
    found_in_run_id INTEGER,
    closed_at TEXT,
    done_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_notified ON jobs(notified_at);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_seconds REAL,
    triggered_by TEXT NOT NULL DEFAULT 'cron',
    companies_checked INTEGER DEFAULT 0,
    companies_ok INTEGER DEFAULT 0,
    companies_broken INTEGER DEFAULT 0,
    new_jobs_count INTEGER DEFAULT 0,
    closed_jobs_count INTEGER DEFAULT 0
);
"""


def get_client() -> libsql_client.Client:
    global _client
    if _client is not None:
        return _client

    settings = load_settings()
    if settings.turso_database_url:
        url = settings.turso_database_url
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        _client = libsql_client.create_client_sync(
            url=url, auth_token=settings.turso_auth_token
        )
    else:
        data_dir = ROOT_DIR / "data"
        data_dir.mkdir(exist_ok=True)
        _client = libsql_client.create_client_sync(url=f"file:{data_dir / 'local.db'}")
    return _client


def close_client() -> None:
    """libsql_client runs a background thread that keeps the process alive
    until the client is explicitly closed. Call this at the end of any
    short-lived script (the CLI does); long-running processes (Streamlit)
    should NOT call this."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


# Added after the initial deploy — run as best-effort ALTERs so existing
# remote DBs (where CREATE TABLE IF NOT EXISTS is a no-op) pick them up too.
MIGRATIONS = [
    "ALTER TABLE jobs ADD COLUMN found_in_run_id INTEGER",
    "ALTER TABLE jobs ADD COLUMN closed_at TEXT",
    "ALTER TABLE jobs ADD COLUMN done_at TEXT",
    "ALTER TABLE companies ADD COLUMN logo_url TEXT",
    # Must run after the ALTERs above add found_in_run_id, since on an
    # existing DB the column won't exist until that migration runs.
    "CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(found_in_run_id)",
]


def init_schema() -> None:
    client = get_client()
    for statement in [s.strip() for s in SCHEMA.split(";") if s.strip()]:
        client.execute(statement)
    for statement in MIGRATIONS:
        try:
            client.execute(statement)
        except Exception:
            pass  # column already exists
    _backfill_missing_logo_urls()


def _backfill_missing_logo_urls() -> None:
    """Companies added before logo_url existed (or via --seed, which doesn't
    set it) get it computed once here instead of on every page render."""
    from .webutil import favicon_url
    client = get_client()
    res = client.execute("SELECT id, url FROM companies WHERE logo_url IS NULL")
    for row in _rows_to_dicts(res):
        client.execute(
            "UPDATE companies SET logo_url = ? WHERE id = ?",
            [favicon_url(row["url"]), row["id"]],
        )


def _rows_to_dicts(result) -> list[dict[str, Any]]:
    cols = result.columns
    return [dict(zip(cols, row)) for row in result.rows]


# --- Companies -------------------------------------------------------------

def list_companies(enabled_only: bool = False) -> list[dict]:
    client = get_client()
    sql = "SELECT * FROM companies"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY name"
    return _rows_to_dicts(client.execute(sql))


def get_company_by_name(name: str) -> dict | None:
    client = get_client()
    res = client.execute("SELECT * FROM companies WHERE name = ?", [name])
    rows = _rows_to_dicts(res)
    return rows[0] if rows else None


def get_company_by_id(company_id: int) -> dict | None:
    client = get_client()
    res = client.execute("SELECT * FROM companies WHERE id = ?", [company_id])
    rows = _rows_to_dicts(res)
    return rows[0] if rows else None


def upsert_company_seed(name: str, url: str) -> None:
    """Insert if the name doesn't already exist. Used only by --seed."""
    client = get_client()
    client.execute(
        "INSERT INTO companies (name, url) VALUES (?, ?) "
        "ON CONFLICT(name) DO NOTHING",
        [name, url],
    )


def add_company(name: str, url: str) -> int:
    from .webutil import favicon_url
    client = get_client()
    res = client.execute(
        "INSERT INTO companies (name, url, logo_url) VALUES (?, ?, ?)",
        [name, url, favicon_url(url)],
    )
    return res.last_insert_rowid


def update_company(company_id: int, **fields: Any) -> None:
    if not fields:
        return
    client = get_client()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    client.execute(
        f"UPDATE companies SET {set_clause} WHERE id = ?",
        [*fields.values(), company_id],
    )


def delete_company(company_id: int) -> None:
    client = get_client()
    client.execute("DELETE FROM jobs WHERE company_id = ?", [company_id])
    client.execute("DELETE FROM companies WHERE id = ?", [company_id])


def set_company_run_status(
    company_id: int,
    status: str,
    error: str | None = None,
    job_count: int | None = None,
    ats_type: str | None = None,
    ats_identifier: str | None = None,
) -> None:
    client = get_client()
    fields: dict[str, Any] = {
        "last_checked_at": _now(),
        "last_status": status,
        "last_error": error,
    }
    if job_count is not None:
        fields["last_job_count"] = job_count
    if ats_type is not None:
        fields["ats_type"] = ats_type
        fields["ats_identifier"] = ats_identifier
        fields["ats_detected_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    client.execute(
        f"UPDATE companies SET {set_clause} WHERE id = ?",
        [*fields.values(), company_id],
    )


# --- Jobs --------------------------------------------------------------

def job_exists(job_id: str) -> bool:
    client = get_client()
    res = client.execute("SELECT 1 FROM jobs WHERE id = ?", [job_id])
    return len(res.rows) > 0


def insert_job(job: dict, run_id: int | None = None) -> None:
    client = get_client()
    client.execute(
        "INSERT INTO jobs (id, company_id, company_name, title, location, url, "
        "description, fetch_tier, found_in_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO NOTHING",
        [
            job["id"],
            job["company_id"],
            job["company"],
            job["title"],
            job.get("location"),
            job["url"],
            job.get("description"),
            job.get("fetch_tier"),
            run_id,
        ],
    )


def close_stale_jobs(company_id: int, current_job_ids: list[str]) -> int:
    """Marks jobs for this company as closed if they're no longer present
    in the latest successful fetch, and re-opens any that reappeared.
    Only call this when the fetch for `company_id` succeeded (non-empty
    `current_job_ids`) — never on a failed/empty fetch, or every open job
    for that company would be wrongly marked closed."""
    if not current_job_ids:
        return 0
    client = get_client()
    placeholders = ", ".join("?" for _ in current_job_ids)

    result = client.execute(
        f"UPDATE jobs SET closed_at = ? WHERE company_id = ? AND closed_at IS NULL "
        f"AND id NOT IN ({placeholders})",
        [_now(), company_id, *current_job_ids],
    )
    client.execute(
        f"UPDATE jobs SET closed_at = NULL WHERE company_id = ? AND closed_at IS NOT NULL "
        f"AND id IN ({placeholders})",
        [company_id, *current_job_ids],
    )
    return result.rows_affected if hasattr(result, "rows_affected") else 0


def mark_job_done(job_id: str, done: bool) -> None:
    client = get_client()
    client.execute(
        "UPDATE jobs SET done_at = ? WHERE id = ?",
        [_now() if done else None, job_id],
    )


def get_unnotified_jobs() -> list[dict]:
    client = get_client()
    res = client.execute(
        "SELECT * FROM jobs WHERE notified_at IS NULL ORDER BY company_name, title"
    )
    return _rows_to_dicts(res)


def mark_jobs_notified(job_ids: Iterable[str]) -> None:
    job_ids = list(job_ids)
    if not job_ids:
        return
    client = get_client()
    placeholders = ", ".join("?" for _ in job_ids)
    client.execute(
        f"UPDATE jobs SET notified_at = ? WHERE id IN ({placeholders})",
        [_now(), *job_ids],
    )


def list_recent_jobs(limit: int = 300) -> list[dict]:
    client = get_client()
    res = client.execute(
        "SELECT * FROM jobs ORDER BY first_seen_at DESC LIMIT ?", [limit]
    )
    return _rows_to_dicts(res)


# --- Runs ----------------------------------------------------------------

def create_run(triggered_by: str = "cron") -> int:
    client = get_client()
    res = client.execute(
        "INSERT INTO runs (started_at, triggered_by) VALUES (?, ?)",
        [_now(), triggered_by],
    )
    return res.last_insert_rowid


def finish_run(
    run_id: int,
    duration_seconds: float,
    companies_checked: int,
    companies_ok: int,
    companies_broken: int,
    new_jobs_count: int,
    closed_jobs_count: int,
) -> None:
    client = get_client()
    client.execute(
        "UPDATE runs SET finished_at = ?, duration_seconds = ?, companies_checked = ?, "
        "companies_ok = ?, companies_broken = ?, new_jobs_count = ?, closed_jobs_count = ? "
        "WHERE id = ?",
        [_now(), duration_seconds, companies_checked, companies_ok, companies_broken,
         new_jobs_count, closed_jobs_count, run_id],
    )


def list_runs(limit: int = 20) -> list[dict]:
    client = get_client()
    res = client.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", [limit]
    )
    return _rows_to_dicts(res)


def list_jobs_for_run(run_id: int) -> list[dict]:
    client = get_client()
    res = client.execute(
        "SELECT * FROM jobs WHERE found_in_run_id = ? ORDER BY company_name, title", [run_id]
    )
    return _rows_to_dicts(res)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
