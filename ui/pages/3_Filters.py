import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from bootstrap import sync_secrets  # noqa: E402
from nav import render_sidebar  # noqa: E402
from style import inject_style  # noqa: E402

sync_secrets()

st.set_page_config(page_title="Filters · Job Alerts", page_icon="🎯", layout="wide")
inject_style()
db.init_schema()
render_sidebar()

st.title("Filters")
st.markdown(
    '<p class="lead">A role is kept only if it matches one of your target roles, '
    "isn't excluded by title, and is in an allowed location. Changes apply to the "
    "next check.</p>",
    unsafe_allow_html=True,
)

filters = db.get_filters()


def _tag_list_input(label, key, current, help=None):
    text = st.text_area(
        label, value="\n".join(current), key=key, height=120,
        help=help or "One per line. A job matches if it contains ANY of these (case-insensitive).",
    )
    return [line.strip() for line in text.split("\n") if line.strip()]


col1, col2 = st.columns(2)
with col1:
    roles = _tag_list_input(
        "Target roles", "roles_input", filters.get("roles", []),
        help="E.g. \"software engineer\", \"backend engineer\". Keep these level-agnostic "
             "(no \"II\"/\"Senior\") — use Exclude below to cap seniority instead.",
    )
    experience_terms = _tag_list_input(
        "Experience terms (optional)", "experience_input", filters.get("experience_terms", []),
        help="E.g. \"0-3 years\", \"mid-level\" — only helps for postings that happen to state an "
             "exact range; most don't, so Exclude below is the more reliable lever.",
    )
    exclude_terms = _tag_list_input(
        "Exclude (title terms)", "exclude_input", filters.get("exclude_terms", []),
        help="A job is rejected if its TITLE contains any of these, regardless of role match. "
             "Default covers seniority (Senior/Staff/...) and non-full-time roles "
             "(Intern/PhD/Co-op). An AI check (separate, on the description) also catches "
             "experience-years and degree-level mismatches these title words can't.",
    )

with col2:
    locations = _tag_list_input(
        "Allowed locations", "locations_input", filters.get("locations", []),
        help="E.g. \"bengaluru\", \"india\". Leave empty to allow any location.",
    )
    always_allow_remote = st.checkbox(
        "Always allow remote-labeled jobs", value=filters.get("always_allow_remote", True),
        help="If checked, a job whose location contains \"remote\" always passes, even if it doesn't match the list above.",
    )

    max_experience_years = st.slider(
        "Maximum years of experience required", min_value=1, max_value=15,
        value=int(filters.get("max_experience_years") or 5),
        help=(
            "Reads the minimum experience out of the job description and drops "
            "anything asking for more than this. Titles are unreliable on their "
            "own — a plain \"Software Engineer\" can want 8+ years. Postings "
            "that state no requirement are always kept."
        ),
    )

if st.button("💾 Save filters", type="primary"):
    db.set_filters({
        "roles": roles,
        "experience_terms": experience_terms,
        "exclude_terms": exclude_terms,
        "locations": locations,
        "always_allow_remote": always_allow_remote,
        "max_experience_years": max_experience_years,
    })
    st.success("Saved.")
    st.rerun()
