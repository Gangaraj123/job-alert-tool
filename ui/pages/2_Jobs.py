import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src import db  # noqa: E402

st.set_page_config(page_title="Jobs - Job Alert Tool", page_icon="💼", layout="wide")
db.init_schema()

st.title("💼 Scraped jobs")
st.caption("Unique open roles across all companies. Closed/expired roles are detected automatically — "
           "if a job disappears from a company's listings on a later run, it's marked closed here.")

jobs = db.list_recent_jobs(limit=1000)
if not jobs:
    st.info("No jobs scraped yet. Run the pipeline (`python -m src.main`, or the Run now button on the home page).")
    st.stop()

df = pd.DataFrame(jobs)
df["is_closed"] = df["closed_at"].notna()
df["done"] = df["done_at"].notna()

companies = sorted(df["company_name"].dropna().unique().tolist())
col1, col2, col3 = st.columns([2, 2, 2])
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

st.caption(f"{len(filtered)} of {len(df)} jobs shown")

display_cols = ["id", "company_name", "title", "location", "url", "is_closed", "done", "first_seen_at"]
edited = st.data_editor(
    filtered[display_cols],
    column_config={
        "id": None,  # hide, but keep for diffing edits below
        "url": st.column_config.LinkColumn("Apply"),
        "is_closed": st.column_config.CheckboxColumn("Closed", disabled=True),
        "done": st.column_config.CheckboxColumn("Done", disabled=False),
    },
    hide_index=True,
    use_container_width=True,
    height=600,
    key="jobs_editor",
)

changed = edited[edited["done"] != filtered["done"].values]
for _, row in changed.iterrows():
    db.mark_job_done(row["id"], bool(row["done"]))
if len(changed):
    st.rerun()
