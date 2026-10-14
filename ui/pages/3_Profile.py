import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src import db  # noqa: E402

st.set_page_config(page_title="Profile - Job Alert Tool", page_icon="🧑‍💻", layout="wide")
db.init_schema()

st.title("🧑‍💻 My profile")
st.caption(
    "This is sent to Claude alongside every new job to score fit. Keep it current — "
    "level, skills, what you're looking for, and red flags. Saved changes apply to the "
    "next scheduled run automatically."
)

current = db.get_profile()
text = st.text_area("Profile (Markdown)", value=current, height=500)

col1, col2 = st.columns([1, 5])
if col1.button("💾 Save", type="primary"):
    db.set_profile(text)
    st.success("Profile saved.")
    st.rerun()
