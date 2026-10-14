import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from bootstrap import sync_secrets  # noqa: E402
from style import inject_style  # noqa: E402
from timeutil import to_ist  # noqa: E402

sync_secrets()

st.set_page_config(page_title="Jobs - Job Alert Tool", page_icon="💼", layout="wide")
inject_style()
db.init_schema()

st.markdown('<div class="hero-kicker">Opportunity inbox</div>', unsafe_allow_html=True)
st.title("Your jobs")
st.markdown('<div class="hero-copy">Every role found across your watchlist. Save your focus by marking roles done as you review them.</div>', unsafe_allow_html=True)

@st.cache_data(ttl=15)
def _recent_jobs():
    return db.list_recent_jobs(limit=1000)


jobs = _recent_jobs()
if not jobs:
    st.info("No jobs scraped yet. Run the pipeline (`python -m src.main`, or the Run now button on the home page).")
    st.stop()

df = pd.DataFrame(jobs)
df["is_closed"] = df["closed_at"].notna()
df["done"] = df["done_at"].notna()

companies = sorted(df["company_name"].dropna().unique().tolist())
col1, col2, col3 = st.columns([2, 1, 1])
company_filter = col1.multiselect("Company", companies)
hide_closed = col2.checkbox("Hide closed/expired", value=True)
hide_done = col3.checkbox("Hide done", value=False)

filtered = df
if company_filter:
    filtered = filtered[filtered["company_name"].isin(company_filter)]
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

st.caption(f"Showing {len(filtered)} of {len(df)} opportunities")

if filtered.empty:
    st.info("No jobs match these filters. Try changing your search or showing closed roles.")
else:
    for _, job in filtered.iterrows():
        with st.container(border=True):
            left, action = st.columns([5, 1])
            title = str(job.get("title") or "Untitled role")
            company = str(job.get("company_name") or "Company")
            location = str(job.get("location") or "Location not specified")
            seen = to_ist(job.get("first_seen_at"))
            badges = " · ".join(x for x in ["Closed" if job["is_closed"] else "Open", "Done" if job["done"] else ""] if x)
            left.markdown(f"**{title}**  \n{company} · {location}  \n<small>{badges} · Found {seen}</small>", unsafe_allow_html=True)
            action.link_button("View role ↗", str(job["url"]), use_container_width=True)
            checked = st.checkbox("Mark as done", value=bool(job["done"]), key=f"done_{job['id']}")
            if checked != bool(job["done"]):
                db.mark_job_done(job["id"], checked)
                _recent_jobs.clear()
                st.rerun()

st.divider()
with st.expander("⚠️ Danger zone"):
    st.caption("This doesn't affect your companies, filters, or run history — only the jobs themselves. "
               "Re-running the pipeline will re-discover anything still actually posted.")
    confirm_jobs = st.checkbox("I'm sure — delete all jobs", key="confirm_clear_jobs")
    if st.button("🗑️ Clear all jobs", disabled=not confirm_jobs):
        db.clear_jobs()
        _recent_jobs.clear()
        st.success("All jobs cleared.")
        st.rerun()
