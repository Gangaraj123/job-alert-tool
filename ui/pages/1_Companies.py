import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from src.pipeline import preview_detect_and_fetch  # noqa: E402
from src import registry  # noqa: E402
from src.webutil import favicon_url  # noqa: E402
from bootstrap import sync_secrets  # noqa: E402
from nav import render_sidebar  # noqa: E402
from style import chip, inject_style, logo_img  # noqa: E402
from timeutil import to_ist  # noqa: E402

sync_secrets()

st.set_page_config(page_title="Companies · Job Alerts", page_icon="🏢", layout="wide")
inject_style()
db.init_schema()
render_sidebar()



def _reset_search() -> None:
    """Clear the search box and cached results after a successful add, so the
    page returns to a clean state instead of re-offering a tracked company."""
    for key in ("search_query", "search_results", "searched_query"):
        st.session_state.pop(key, None)


@st.cache_data(ttl=600, show_spinner=False)
def _registry_matches(query: str) -> list[dict]:
    """Registry entries whose name contains the query. Local and in-memory —
    no network call, so it runs on every keystroke without cost."""
    q = query.strip().lower()
    if len(q) < 2:
        return []
    exact = [e for e in registry.all_entries() if e["name"].lower() == q]
    partial = [
        e for e in registry.all_entries()
        if q in e["name"].lower() and e["name"].lower() != q
    ]
    return exact + partial


def _add(name: str, *, pending: bool = False) -> None:
    if db.get_company_by_name(name):
        st.warning(f"{name} is already tracked.")
        return
    # url passed explicitly: harmless now, and keeps the call valid if the
    # UI is ever served from a newer checkout than src/ (Streamlit Cloud
    # has shipped a half-updated tree at least once).
    db.add_company(name, "")
    if pending:
        st.success(
            f"Saved {name} to the upcoming list. It won't be scanned until "
            "a fetch method is added for it."
        )
    else:
        st.success(f"Added {name}.")
    _reset_search()
    st.rerun()


st.title("Companies")
st.markdown(
    '<p class="lead">Type a company name and add it. Known companies are '
    "tracked straight away; anything else is saved for setup later.</p>",
    unsafe_allow_html=True,
)

with st.expander("Add a company", expanded=not db.list_companies()):
    query = st.text_input(
        "Company name", key="search_query", placeholder="e.g. Stripe"
    ).strip()

    if query:
        matches = _registry_matches(query)

        for entry in matches:
            ats, _ = registry.parse_method(entry["method"])
            with st.container(border=True):
                row = st.columns([0.6, 4, 1.4])
                row[0].markdown(
                    logo_img(registry.logo_for(entry["domain"]) or ""),
                    unsafe_allow_html=True,
                )
                badge = (
                    chip(f"{ats} · verified", "ok") if ats
                    else chip("needs setup", "warn")
                )
                row[1].markdown(
                    f"**{entry['name']}** &nbsp; {badge}<br>"
                    f"<span class='meta'>{entry['domain'] or ''}</span>",
                    unsafe_allow_html=True,
                )
                if db.get_company_by_name(entry["name"]):
                    row[2].button(
                        "Tracked", disabled=True, key=f"dupe_{entry['name']}"
                    )
                elif row[2].button(
                    "Add", type="primary", key=f"add_{entry['name']}"
                ):
                    _add(entry["name"])

        # Nothing in the registry matches: save the name as typed rather than
        # making the user hunt for a careers URL. Auto-detection used to run
        # here and was the slowest, least reliable part of the page -- it
        # could not resolve self-hosted boards like Amazon's at all.
        if not matches:
            st.caption(
                f"\"{query}\" isn't set up yet. Save it to the upcoming list "
                "and it will be wired up on the next review."
            )
            if st.button(
                f"Save \"{query}\" to upcoming list", key="save_pending"
            ):
                _add(query, pending=True)

companies = db.list_companies()
if not companies:
    st.info("No companies yet — search for one above.")
else:
    st.subheader(f"Tracked companies ({len(companies)})")
    for c in companies:
        with st.container(border=True):
            info, controls = st.container(), st.container()
            # Logo and name share one block rather than separate columns: on a
            # phone the columns stack, and a 30px logo given its own full-width
            # row collided with the name underneath it.
            url = c["url"] or ""
            link = f'<div class="row-sub"><a href="{url}">{url}</a></div>' if url else ""
            info.markdown(
                '<div class="row-ident">'
                + logo_img(c.get("logo_url") or (favicon_url(url) if url else ""))
                + f'<div><div class="row-title">{c["name"]}</div>{link}</div>'
                + "</div>",
                unsafe_allow_html=True,
            )

            status = c.get("last_status") or "never run"
            status_kind = {"ok": "ok", "error": "danger"}.get(status, "neutral")
            status_text = {"ok": "healthy", "error": "failing"}.get(status, "never run")
            chips = [chip(status_text, status_kind)]
            if c.get("ats_type"):
                chips.append(chip(c["ats_type"], "accent"))
            # Lead with what matched the user's filters. The board total is
            # context, not the headline -- "898 roles" next to a company with
            # one relevant opening is actively misleading.
            method = c.get("method") or ""
            if method == "pending":
                chips.append(chip("needs setup", "warn"))
            elif c.get("last_status") == "ok":
                matched = c.get("last_match_count") or 0
                scanned = c.get("last_job_count") or 0
                chips.append(chip(
                    f"{matched} matching" if matched else "no matches",
                    "ok" if matched else "neutral",
                ))
                chips.append(chip(f"of {scanned} scanned", "neutral"))

            checked = c.get("last_checked_at")
            info.markdown(
                " ".join(chips)
                + (f'<div class="meta">Checked {to_ist(checked)}</div>' if checked else ""),
                unsafe_allow_html=True,
            )
            if c.get("last_error"):
                info.caption(str(c["last_error"])[:160])

            act = controls.columns([1, 1, 0.6])
            new_enabled = act[0].toggle("Active", value=bool(c["enabled"]), key=f"enabled_{c['id']}")
            if new_enabled != bool(c["enabled"]):
                db.update_company(c["id"], enabled=1 if new_enabled else 0)
                st.rerun()

            if act[1].button("Re-check", key=f"recheck_{c['id']}", help="Detect the ATS and test-fetch right now", use_container_width=True):
                with st.spinner(f"Checking {c['name']}…"):
                    result = preview_detect_and_fetch(c["url"])
                db.set_company_run_status(
                    c["id"], "ok" if result["ok"] else "error",
                    error=result.get("error"), job_count=result.get("job_count"),
                    ats_type=result.get("ats_type"), ats_identifier=result.get("ats_identifier"),
                )
                st.rerun()

            with act[2].popover("⚙️"):
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
