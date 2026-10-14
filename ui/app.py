"""Streamlit entry point: overview/home page.

Run locally with: streamlit run ui/app.py
On Streamlit Community Cloud, point the app at this file.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402

# On Streamlit Cloud, secrets come from st.secrets rather than a local .env.
# Mirror them into os.environ so src/config.py (which reads env vars) picks
# them up transparently, whether running locally or hosted.
import os  # noqa: E402

for key in (
    "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
):
    if key in st.secrets and key not in os.environ:
        os.environ[key] = st.secrets[key]

st.set_page_config(page_title="Job Alert Tool", page_icon="📋", layout="wide")

db.init_schema()

st.title("📋 Job Alert Tool")
st.caption("Edit target companies and review scraped jobs. The daily pipeline runs separately via GitHub Actions.")

companies = db.list_companies()
jobs = db.list_recent_jobs(limit=1000)

enabled = [c for c in companies if c["enabled"]]
errored = [c for c in companies if c.get("last_status") == "error"]
scored_jobs = [j for j in jobs if j.get("fit_score") is not None]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Companies tracked", len(companies))
col2.metric("Enabled", len(enabled))
col3.metric("Jobs seen (last 1000)", len(jobs))
col4.metric("Fetchers currently broken", len(errored))

st.divider()
st.markdown(
    "Use the pages in the sidebar:\n"
    "- **Companies** — add, edit, enable/disable the companies being tracked\n"
    "- **Jobs** — browse scraped + AI-scored jobs"
)

if errored:
    st.warning(f"{len(errored)} company fetcher(s) are currently failing — check the Companies page.")
