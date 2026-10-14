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
from bootstrap import sync_secrets  # noqa: E402
from style import inject_style  # noqa: E402

sync_secrets()

st.set_page_config(page_title="Job Alert Tool", page_icon="📋", layout="wide", initial_sidebar_state="expanded")
inject_style()

db.init_schema()


@st.cache_data(ttl=15)
def _overview_data():
    return db.list_companies(), db.count_jobs()


st.markdown('<div class="hero-kicker">Your career search, organized</div>', unsafe_allow_html=True)
st.title("Job search dashboard")
st.markdown('<div class="hero-copy">Track the companies you care about and keep new opportunities in one calm, searchable place.</div>', unsafe_allow_html=True)

companies, job_count = _overview_data()

enabled = [c for c in companies if c["enabled"]]
errored = [c for c in companies if c.get("last_status") == "error"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Companies tracked", len(companies), help="All companies in your watchlist")
col2.metric("Actively monitored", len(enabled))
col3.metric("Jobs discovered", job_count)
col4.metric("Needs attention", len(errored), delta="Check companies" if errored else "All systems clear", delta_color="inverse" if errored else "normal")

st.divider()

st.subheader("Refresh your watchlist")
st.caption("Runs also happen automatically every day. Start one now to check for the latest openings.")
run_col, mail_col = st.columns([1.25, 3])
send_email = mail_col.checkbox("Email me a digest if new jobs are found", value=False)
if run_col.button("Run check now", type="primary", use_container_width=True):
    with st.spinner("Fetching every enabled company… this can take a minute."):
        stats = run_pipeline(dry_run=not send_email, triggered_by="ui")
    _overview_data.clear()
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
st.subheader("Recent activity")
st.caption("A history of company checks and newly discovered roles.")

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
