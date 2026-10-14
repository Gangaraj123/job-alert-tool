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

    anthropic_api_key: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None

    raw: dict


def load_settings() -> Settings:
    return Settings(
        turso_database_url=_env("TURSO_DATABASE_URL"),
        turso_auth_token=_env("TURSO_AUTH_TOKEN"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
        raw={},
    )


def load_config(path: Path | None = None) -> dict:
    path = path or (ROOT_DIR / "config.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_profile(path: Path | None = None) -> str:
    path = path or (ROOT_DIR / "profile.md")
    return path.read_text()


def load_seed_companies(path: Path | None = None) -> list[dict]:
    path = path or (ROOT_DIR / "companies.seed.yaml")
    if not path.exists():
        return []
    with open(path, "r") as f:
        data = yaml.safe_load(f) or []
    return data
