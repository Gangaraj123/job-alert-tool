"""Loads config.yaml and environment/secrets. Single source of truth for settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # Database (Turso). If unset, falls back to a local SQLite-compatible file
    # so the pipeline is runnable offline for development/testing.
    turso_database_url: str | None
    turso_auth_token: str | None

    gmail_address: str | None
    gmail_app_password: str | None
    digest_to_email: str | None
    # Public URL of the Streamlit dashboard. Linked at the foot of every
    # digest so the mail is a notification, not the only copy of the data.
    app_url: str | None
    # Dead-man's-switch URL pinged after every successful run. An external
    # watchdog alerts when the ping STOPS -- the only way to detect a run
    # that never happened, since nothing inside the system is executing to
    # notice. Unset means no ping and no behaviour change.
    healthcheck_url: str | None

    gemini_api_key: str | None

    # Vertex AI (preferred when configured): bills against a GCP project's
    # billing account (e.g. free trial credits) instead of the AI Studio
    # key's thin free-tier quota. GOOGLE_VERTEX_CREDENTIALS_JSON holds the
    # full service account key JSON as a single-line string.
    google_vertex_credentials_json: str | None
    vertex_project: str | None
    vertex_location: str

    raw: dict


def load_settings() -> Settings:
    return Settings(
        turso_database_url=_env("TURSO_DATABASE_URL"),
        turso_auth_token=_env("TURSO_AUTH_TOKEN"),
        gmail_address=_env("GMAIL_ADDRESS"),
        gmail_app_password=_env("GMAIL_APP_PASSWORD"),
        digest_to_email=_env("DIGEST_TO_EMAIL"),
        app_url=_env("APP_URL"),
        healthcheck_url=_env("HEALTHCHECK_URL"),
        gemini_api_key=_env("GEMINI_API_KEY"),
        google_vertex_credentials_json=_env("GOOGLE_VERTEX_CREDENTIALS_JSON"),
        vertex_project=_env("VERTEX_PROJECT"),
        vertex_location=_env("VERTEX_LOCATION", "us-central1"),
        raw={},
    )


def load_config(path: Path | None = None) -> dict:
    path = path or (ROOT_DIR / "config.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_seed_companies(path: Path | None = None) -> list[dict]:
    path = path or (ROOT_DIR / "companies.seed.yaml")
    if not path.exists():
        return []
    with open(path, "r") as f:
        data = yaml.safe_load(f) or []
    return data
