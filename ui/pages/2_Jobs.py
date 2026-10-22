import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from bootstrap import sync_secrets  # noqa: E402
from nav import render_sidebar  # noqa: E402
from style import chip, logo_img, inject_style  # noqa: E402
from timeutil import to_ist  # noqa: E402

sync_secrets()

st.set_page_config(page_title="Jobs · Job Alerts", page_icon="💼", layout="wide")
inject_style()
db.init_schema()
render_sidebar()

st.title("Jobs")
st.markdown(
    '<p class="lead">Every role found across your watchlist. Roles that disappear '
    "from a company's listings are marked closed automatically.</p>",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=15)
def _recent_jobs():
    return db.list_recent_jobs(limit=1000)


@st.cache_data(ttl=300)
def _logos() -> dict[str, str]:
    """company name -> logo URL. Jobs store the company name only, so the
    logo is looked up once per render rather than joined per row."""
    return {
        c["name"]: c.get("logo_url") or ""
        for c in db.list_companies()
    }


jobs = _recent_jobs()
_company_logos = _logos()
if not jobs:
    st.info("No roles found yet. Start a check from the Overview page.")
    st.stop()

df = pd.DataFrame(jobs)
df["is_closed"] = df["closed_at"].notna()
df["done"] = df["done_at"].notna()

# first_seen_at is stored UTC; bucket by IST calendar day so "Today" means
# today where the user is, not wherever the server thinks it is.
df["found_date"] = (
    pd.to_datetime(df["first_seen_at"], errors="coerce", utc=True)
    .dt.tz_convert("Asia/Kolkata")
    .dt.date
)

_WINDOWS = {
    "Any time": None,
    "Today": 0,
    "Last 3 days": 2,
    "Last 7 days": 6,
    "Last 30 days": 29,
}

companies = sorted(df["company_name"].dropna().unique().tolist())
col1, col2, col3, col4 = st.columns([2, 1.3, 1, 1])
company_filter = col1.multiselect("Company", companies)
found_window = col2.selectbox(
    "Found", list(_WINDOWS), index=0,
    help="When the role first showed up in a scan, not when it was posted.",
)
hide_closed = col3.checkbox("Hide closed/expired", value=True)
hide_done = col4.checkbox("Hide done", value=False)

filtered = df
if company_filter:
    filtered = filtered[filtered["company_name"].isin(company_filter)]

days_back = _WINDOWS[found_window]
if days_back is not None:
    from datetime import datetime, timedelta, timezone

    today_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    cutoff = today_ist - timedelta(days=days_back)
    filtered = filtered[filtered["found_date"].notna() & (filtered["found_date"] >= cutoff)]
if hide_closed:
    filtered = filtered[~filtered["is_closed"]]
if hide_done:
    filtered = filtered[~filtered["done"]]

search = st.text_input("Search title/description")
if search:
    mask = filtered["title"].str.contains(search, case=False, na=False) | \
        filtered["description"].str.contains(search, case=False, na=False)
    filtered = filtered[mask]

filtered = filtered.sort_values(by=["is_closed", "first_seen_at"], ascending=[True, False])

st.caption(f"Showing {len(filtered)} of {len(df)} roles")

if filtered.empty:
    st.info("No roles match these filters. Try a different search, or show closed roles.")
else:
    for _, job in filtered.iterrows():
        with st.container(border=True):
            # 1/6th of a 390px phone is ~55px, which clipped "Open" to "O...".
            left, action = st.columns([3.1, 1.15])
            title = str(job.get("title") or "Untitled role")
            company = str(job.get("company_name") or "Company")
            location = str(job.get("location") or "Location not stated")

            badges = [chip("Closed", "warn") if job["is_closed"] else chip("Open", "ok")]
            if job["done"]:
                badges.append(chip("Done", "neutral"))

            left.markdown(
                '<div class="row-ident">'
                + logo_img(_company_logos.get(company, ""), size=26)
                + f'<div class="row-title">{title}</div></div>'
                f'<div class="meta"><b>{company}</b> — {location}</div>'
                + " ".join(badges)
                + f'<span class="meta">&nbsp; Found {to_ist(job.get("first_seen_at"))}</span>',
                unsafe_allow_html=True,
            )
            action.link_button("Open", str(job["url"]), use_container_width=True)
            checked = st.checkbox("Mark as done", value=bool(job["done"]), key=f"done_{job['id']}")
            if checked != bool(job["done"]):
                db.mark_job_done(job["id"], checked)
                _recent_jobs.clear()
                st.rerun()

st.divider()
with st.expander("Danger zone"):
    st.caption("Affects only saved roles — your companies, filters and run history are untouched. "
               "The next check re-discovers anything still posted.")
    confirm_jobs = st.checkbox("Yes, delete all roles", key="confirm_clear_jobs")
    if st.button("Clear all roles", disabled=not confirm_jobs):
        db.clear_jobs()
        _recent_jobs.clear()
        st.success("All jobs cleared.")
        st.rerun()
