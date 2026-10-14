import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from bootstrap import sync_secrets  # noqa: E402
from style import inject_style  # noqa: E402

sync_secrets()

st.set_page_config(page_title="Filters - Job Alert Tool", page_icon="🎯", layout="wide")
inject_style()
db.init_schema()

st.title("🎯 Role & location filters")
st.caption(
    "A job only gets stored if its title/description matches one of your roles (or experience terms), "
    "and its location matches your location list (or is remote, if allowed below). "
    "Changes apply to the next run — no redeploy needed."
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
        help="E.g. \"SDE II\", \"Software Engineer II\", \"Backend Engineer\". One per line.",
    )
    experience_terms = _tag_list_input(
        "Experience terms (optional)", "experience_input", filters.get("experience_terms", []),
        help="E.g. \"3-5 years\", \"mid-level\". Matched the same way as roles — leave empty to skip.",
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

if st.button("💾 Save filters", type="primary"):
    db.set_filters({
        "roles": roles,
        "experience_terms": experience_terms,
        "locations": locations,
        "always_allow_remote": always_allow_remote,
    })
    st.success("Saved.")
    st.rerun()
