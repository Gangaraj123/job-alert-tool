import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src import db  # noqa: E402

st.set_page_config(page_title="Companies - Job Alert Tool", page_icon="🏢", layout="wide")
db.init_schema()

st.title("🏢 Target companies")
st.caption("Edit the list the daily pipeline scrapes. Changes are picked up by the next scheduled run — no redeploy needed.")

with st.expander("➕ Add a company", expanded=False):
    with st.form("add_company", clear_on_submit=True):
        name = st.text_input("Name")
        url = st.text_input("Career page URL", placeholder="https://example.com/careers")
        submitted = st.form_submit_button("Add")
        if submitted:
            if not name.strip() or not url.strip():
                st.error("Both name and URL are required.")
            elif db.get_company_by_name(name.strip()):
                st.error(f"A company named '{name}' already exists.")
            else:
                db.add_company(name.strip(), url.strip())
                st.success(f"Added {name}.")
                st.rerun()

companies = db.list_companies()
if not companies:
    st.info("No companies yet — add one above, or run `python -m src.main --seed` once to load companies.seed.yaml.")
else:
    st.subheader("All companies")
    for c in companies:
        with st.container(border=True):
            cols = st.columns([3, 4, 2, 2, 1])
            cols[0].markdown(f"**{c['name']}**  \n[{c['url']}]({c['url']})")

            ats_label = c.get("ats_type") or "not detected"
            status = c.get("last_status") or "never run"
            status_icon = {"ok": "🟢", "error": "🔴"}.get(status, "⚪")
            cols[1].markdown(
                f"ATS: `{ats_label}`  \n"
                f"{status_icon} {status} · last checked: {c.get('last_checked_at') or '—'}  \n"
                f"jobs last run: {c.get('last_job_count') or 0}"
            )
            if c.get("last_error"):
                cols[1].caption(f"⚠️ {c['last_error']}")

            new_enabled = cols[2].toggle("Enabled", value=bool(c["enabled"]), key=f"enabled_{c['id']}")
            if new_enabled != bool(c["enabled"]):
                db.update_company(c["id"], enabled=1 if new_enabled else 0)
                st.rerun()

            with cols[3].popover("Edit URL"):
                new_url = st.text_input("Career page URL", value=c["url"], key=f"url_{c['id']}")
                if st.button("Save", key=f"save_{c['id']}"):
                    db.update_company(c["id"], url=new_url, ats_type=None, ats_identifier=None, ats_detected_at=None)
                    st.success("Updated — ATS will be re-detected on next run.")
                    st.rerun()

            if cols[4].button("🗑️", key=f"delete_{c['id']}", help="Delete company and its scraped jobs"):
                db.delete_company(c["id"])
                st.rerun()
