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
    fit_score INTEGER,
    why_it_fits TEXT,
    gaps TEXT,
    red_flags TEXT,
    priority TEXT,
    scored_at TEXT,
    notified_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_priority ON jobs(priority);
CREATE INDEX IF NOT EXISTS idx_jobs_notified ON jobs(notified_at);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
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


def init_schema() -> None:
    client = get_client()
    for statement in [s.strip() for s in SCHEMA.split(";") if s.strip()]:
        client.execute(statement)


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
    client = get_client()
    res = client.execute(
        "INSERT INTO companies (name, url) VALUES (?, ?)", [name, url]
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


def insert_job(job: dict) -> None:
    client = get_client()
    client.execute(
        "INSERT INTO jobs (id, company_id, company_name, title, location, url, "
        "description, fetch_tier) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
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
        ],
    )


def update_job_score(
    job_id: str,
    fit_score: int,
    why_it_fits: str,
    gaps: str,
    red_flags: str,
    priority: str,
) -> None:
    client = get_client()
    client.execute(
        "UPDATE jobs SET fit_score = ?, why_it_fits = ?, gaps = ?, red_flags = ?, "
        "priority = ?, scored_at = ? WHERE id = ?",
        [fit_score, why_it_fits, gaps, red_flags, priority, _now(), job_id],
    )


def get_unnotified_scored_jobs(min_fit_score: int) -> list[dict]:
    client = get_client()
    res = client.execute(
        "SELECT * FROM jobs WHERE notified_at IS NULL AND fit_score IS NOT NULL "
        "AND fit_score >= ? ORDER BY fit_score DESC",
        [min_fit_score],
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


# --- Settings / profile -------------------------------------------------

def get_setting(key: str) -> str | None:
    client = get_client()
    res = client.execute("SELECT value FROM settings WHERE key = ?", [key])
    rows = _rows_to_dicts(res)
    return rows[0]["value"] if rows else None


def set_setting(key: str, value: str) -> None:
    client = get_client()
    client.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        [key, value, _now()],
    )


def get_profile() -> str:
    """Profile text used for AI scoring, editable from the UI. Seeded from
    profile.md the first time it's read if the DB doesn't have one yet."""
    value = get_setting("profile")
    if value is not None:
        return value
    from .config import load_profile
    text = load_profile()
    set_setting("profile", text)
    return text


def set_profile(text: str) -> None:
    set_setting("profile", text)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
