"""Call sync_secrets() at the top of every page (not just app.py) — Streamlit
only executes the script for whichever page is currently being viewed, so
secrets-mirroring code living only in app.py would silently be skipped if a
user opens e.g. the Companies page directly without visiting the home page
first in that session."""
import os

import streamlit as st

_SECRET_KEYS = (
    "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
    "GEMINI_API_KEY",
    "VERTEX_PROJECT", "VERTEX_LOCATION", "GOOGLE_VERTEX_CREDENTIALS_JSON",
)


def sync_secrets() -> None:
    try:
        for key in _SECRET_KEYS:
            if key in st.secrets and key not in os.environ:
                os.environ[key] = st.secrets[key]
    except Exception:
        pass  # no secrets.toml locally — fine, src/config.py already reads .env directly
