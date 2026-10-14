import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src import db  # noqa: E402
from src.pipeline import preview_detect_and_fetch  # noqa: E402
from src.webutil import favicon_url  # noqa: E402

st.set_page_config(page_title="Companies - Job Alert Tool", page_icon="🏢", layout="wide")
db.init_schema()

st.title("🏢 Target companies")
st.caption("Edit the list the daily pipeline scrapes. Changes are picked up by the next scheduled run — no redeploy needed.")

with st.expander("➕ Add a company", expanded=False):
    name = st.text_input("Name", key="add_name")
    url = st.text_input("Career page URL", key="add_url", placeholder="https://example.com/careers")

    if url:
        st.image(favicon_url(url), width=32)

    col_a, col_b = st.columns([1, 1])
    if col_a.button("🔍 Detect & preview", disabled=not url):
        with st.spinner("Detecting ATS and test-fetching jobs…"):
            st.session_state["add_preview"] = preview_detect_and_fetch(url)

    preview = st.session_state.get("add_preview")
    if preview:
        if preview["ok"]:
            st.success(f"Detected **{preview['ats_type'] or 'no known ATS'}** via `{preview['tier']}` — {preview['job_count']} job(s) found.")
        else:
            st.error(f"Every fetch tier failed: {preview['error']}")

    if col_b.button("💾 Save company", type="primary", disabled=not (name and url)):
        if db.get_company_by_name(name.strip()):
            st.error(f"A company named '{name}' already exists.")
        else:
            company_id = db.add_company(name.strip(), url.strip())
            if preview and preview["ok"] and preview["ats_type"]:
                db.update_company(
                    company_id, ats_type=preview["ats_type"],
                    ats_identifier=preview["ats_identifier"], ats_detected_at=db._now(),
                )
            if preview:
                db.set_company_run_status(
                    company_id, "ok" if preview["ok"] else "error",
                    error=preview.get("error"), job_count=preview.get("job_count"),
                )
            st.session_state.pop("add_preview", None)
            st.success(f"Added {name}.")
            st.rerun()

companies = db.list_companies()
if not companies:
    st.info("No companies yet — add one above, or run `python -m src.main --seed` once to load companies.seed.yaml.")
else:
    st.subheader("All companies")
    for c in companies:
        with st.container(border=True):
            cols = st.columns([0.6, 2.5, 3.5, 1.5, 1.5, 0.8])
            cols[0].image(c.get("logo_url") or favicon_url(c["url"]), width=28)
            cols[1].markdown(f"**{c['name']}**  \n[{c['url']}]({c['url']})")

            ats_label = c.get("ats_type") or "not detected"
            status = c.get("last_status") or "never run"
            status_icon = {"ok": "🟢", "error": "🔴"}.get(status, "⚪")
            cols[2].markdown(
                f"ATS: `{ats_label}`  \n"
                f"{status_icon} {status} · last checked: {c.get('last_checked_at') or '—'}  \n"
                f"jobs last run: {c.get('last_job_count') or 0}"
            )
            if c.get("last_error"):
                cols[2].caption(f"⚠️ {c['last_error']}")

            new_enabled = cols[3].toggle("Enabled", value=bool(c["enabled"]), key=f"enabled_{c['id']}")
            if new_enabled != bool(c["enabled"]):
                db.update_company(c["id"], enabled=1 if new_enabled else 0)
                st.rerun()

            if cols[4].button("🔍 Re-check", key=f"recheck_{c['id']}", help="Detect ATS and test-fetch right now"):
                with st.spinner(f"Checking {c['name']}…"):
                    result = preview_detect_and_fetch(c["url"])
                db.set_company_run_status(
                    c["id"], "ok" if result["ok"] else "error",
                    error=result.get("error"), job_count=result.get("job_count"),
                    ats_type=result.get("ats_type"), ats_identifier=result.get("ats_identifier"),
                )
                st.rerun()

            with cols[5].popover("⚙️"):
                new_url = st.text_input("Career page URL", value=c["url"], key=f"url_{c['id']}")
                if st.button("Save URL", key=f"save_{c['id']}"):
                    db.update_company(
                        c["id"], url=new_url, logo_url=favicon_url(new_url),
                        ats_type=None, ats_identifier=None, ats_detected_at=None,
                    )
                    st.success("Updated — click Re-check to re-detect.")
                    st.rerun()
                st.divider()
                if st.button("🗑️ Delete company", key=f"delete_{c['id']}"):
                    db.delete_company(c["id"])
                    st.rerun()
