import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src import db  # noqa: E402

st.set_page_config(page_title="Jobs - Job Alert Tool", page_icon="💼", layout="wide")
db.init_schema()

st.title("💼 Scraped jobs")

jobs = db.list_recent_jobs(limit=1000)
if not jobs:
    st.info("No jobs scraped yet. Run the pipeline (`python -m src.main`) or wait for the next scheduled run.")
    st.stop()

df = pd.DataFrame(jobs)

companies = sorted(df["company_name"].dropna().unique().tolist())
col1, col2, col3 = st.columns([2, 2, 3])
company_filter = col1.multiselect("Company", companies)
priority_filter = col2.multiselect("Priority", ["high", "medium", "low"])
min_score = col3.slider("Minimum fit score", 0, 100, 0)

filtered = df
if company_filter:
    filtered = filtered[filtered["company_name"].isin(company_filter)]
if priority_filter:
    filtered = filtered[filtered["priority"].isin(priority_filter)]
filtered = filtered[filtered["fit_score"].fillna(0) >= min_score]

search = st.text_input("Search title/description")
if search:
    mask = filtered["title"].str.contains(search, case=False, na=False) | \
        filtered["description"].str.contains(search, case=False, na=False)
    filtered = filtered[mask]

filtered = filtered.sort_values(by=["fit_score"], ascending=False, na_position="last")

st.caption(f"{len(filtered)} of {len(df)} jobs shown")

st.dataframe(
    filtered[[
        "company_name", "title", "location", "fit_score", "priority",
        "why_it_fits", "red_flags", "url", "first_seen_at",
    ]],
    column_config={
        "url": st.column_config.LinkColumn("Apply"),
        "fit_score": st.column_config.NumberColumn("Score", format="%d"),
    },
    hide_index=True,
    use_container_width=True,
    height=600,
)
