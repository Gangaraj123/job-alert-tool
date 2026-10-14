"""Streamlit entry point: overview/home page, with a "Run now" button and
run history.

Run locally with: streamlit run ui/app.py
On Streamlit Community Cloud, point the app at this file.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402

# On Streamlit Cloud, secrets come from st.secrets rather than a local .env.
# Mirror them into os.environ so src/config.py (which reads env vars) picks
# them up transparently, whether running locally or hosted.
import os  # noqa: E402

for key in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
    if key in st.secrets and key not in os.environ:
        os.environ[key] = st.secrets[key]

st.set_page_config(page_title="Job Alert Tool", page_icon="📋", layout="wide")

db.init_schema()

st.title("📋 Job Alert Tool")
st.caption("Edit target companies and review scraped jobs. Runs automatically via GitHub Actions daily, or trigger one below.")

companies = db.list_companies()
jobs = db.list_recent_jobs(limit=1000)

enabled = [c for c in companies if c["enabled"]]
errored = [c for c in companies if c.get("last_status") == "error"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Companies tracked", len(companies))
col2.metric("Enabled", len(enabled))
col3.metric("Jobs seen (last 1000)", len(jobs))
col4.metric("Fetchers currently broken", len(errored))

st.divider()

send_email = st.checkbox("Send email digest if this run finds anything new", value=False)
if st.button("▶️ Run now", type="primary"):
    with st.spinner("Fetching every enabled company… this can take a minute."):
        stats = run_pipeline(dry_run=not send_email, triggered_by="ui")
    st.success(
        f"Done in {stats['duration_seconds']:.1f}s — "
        f"{stats['companies_ok']}/{stats['companies_checked']} companies OK, "
        f"{stats['new_jobs_count']} new job(s), {stats['closed_jobs_count']} closed, "
        f"{'email sent' if stats['email_sent'] else 'email not sent'}."
    )
    if stats["new_jobs"]:
        with st.expander(f"New jobs found ({len(stats['new_jobs'])})", expanded=True):
            for j in stats["new_jobs"]:
                st.markdown(f"- [{j['title']} @ {j['company']}]({j['url']}) — {j.get('location') or 'unspecified'}")
    st.rerun()

st.divider()
st.subheader("Run history")

runs = db.list_runs(limit=20)
if not runs:
    st.caption("No runs yet.")
else:
    for r in runs:
        duration_label = f"{r['duration_seconds']:.1f}s" if r.get("duration_seconds") else "running…"
        label = (
            f"{r['started_at']} · {r['triggered_by']} · "
            f"{r.get('new_jobs_count') or 0} new · "
            f"{r.get('companies_broken') or 0} broken · {duration_label}"
        )
        with st.expander(label):
            run_jobs = db.list_jobs_for_run(r["id"])
            if not run_jobs:
                st.caption("No new jobs found in this run.")
            else:
                for j in run_jobs:
                    st.markdown(f"- [{j['title']} @ {j['company_name']}]({j['url']}) — {j.get('location') or 'unspecified'}")

if errored:
    st.warning(f"{len(errored)} company fetcher(s) are currently failing — check the Companies page.")
