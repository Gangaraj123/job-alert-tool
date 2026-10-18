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
from nav import render_sidebar  # noqa: E402
from style import chip, inject_style  # noqa: E402
from timeutil import to_ist  # noqa: E402

sync_secrets()

st.set_page_config(page_title="Overview · Job Alerts", page_icon="📋", layout="wide", initial_sidebar_state="expanded")
inject_style()

db.init_schema()


@st.cache_data(ttl=15)
def _overview_data():
    return db.list_companies(), db.count_jobs()


companies, job_count = _overview_data()

enabled = [c for c in companies if c["enabled"]]
errored = [c for c in companies if c.get("last_status") == "error"]

render_sidebar(
    f"{len(enabled)} of {len(companies)} companies active"
    + (f"<br>{len(errored)} need attention" if errored else "")
)

st.title("Overview")
st.markdown(
    '<p class="lead">Companies you track, roles found for them, and the health of '
    "each check — all in one place.</p>",
    unsafe_allow_html=True,
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Companies tracked", len(companies), help="Everything in your watchlist, active or paused")
col2.metric("Actively monitored", len(enabled))
col3.metric("Jobs discovered", job_count)
col4.metric("Needs attention", len(errored),
            delta="Check companies" if errored else None,
            delta_color="inverse" if errored else "normal")

st.divider()

st.subheader("Run a check")
st.caption("Checks run automatically each day. Start one now for the latest openings.")
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

if errored:
    st.warning(f"{len(errored)} company check(s) are currently failing — see the Companies page.")

st.divider()
st.subheader("Recent activity")
st.caption("Past checks and the roles each one surfaced.")

runs = db.list_runs(limit=20)
if not runs:
    st.caption("No checks have run yet.")
else:
    for r in runs:
        new_count = r.get("new_jobs_count") or 0
        broken = r.get("companies_broken") or 0
        duration = f"{r['duration_seconds']:.1f}s" if r.get("duration_seconds") else "running"

        # Chips carry the priority information (did it find anything? did
        # anything break?); the timestamp stays plain text. Previously all
        # of this was one dot-joined grey string where nothing stood out.
        with st.expander(f"{to_ist(r['started_at'])}  —  {new_count} new"):
            st.markdown(
                " ".join([
                    chip(f"{new_count} new", "accent" if new_count else "neutral"),
                    chip(f"{broken} failed", "danger" if broken else "neutral"),
                    chip(r["triggered_by"], "neutral"),
                    chip(duration, "neutral"),
                ]),
                unsafe_allow_html=True,
            )
            run_jobs = db.list_jobs_for_run(r["id"])
            if not run_jobs:
                st.caption("No new roles in this check.")
            else:
                for j in run_jobs:
                    st.markdown(
                        f"- [{j['title']}]({j['url']}) — {j['company_name']}, "
                        f"{j.get('location') or 'location not stated'}"
                    )

st.divider()
with st.expander("Danger zone"):
    st.caption("Affects only the run log — your companies, filters and saved jobs are untouched.")
    confirm_runs = st.checkbox("Yes, delete all run history", key="confirm_clear_runs")
    if st.button("Clear run history", disabled=not confirm_runs):
        db.clear_runs()
        st.success("Run history cleared.")
        st.rerun()
