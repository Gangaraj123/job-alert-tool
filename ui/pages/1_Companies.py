import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from src.pipeline import discover_career_url, preview_detect_and_fetch  # noqa: E402
from src import registry  # noqa: E402
from src.webutil import ai_status, favicon_url, rerank_company_matches, search_companies  # noqa: E402
from bootstrap import sync_secrets  # noqa: E402
from nav import render_sidebar  # noqa: E402
from style import chip, inject_style, logo_img  # noqa: E402
from timeutil import to_ist  # noqa: E402

sync_secrets()

st.set_page_config(page_title="Companies · Job Alerts", page_icon="🏢", layout="wide")
inject_style()
db.init_schema()
render_sidebar()

@st.cache_data(ttl=600, show_spinner=False)
def _reset_search() -> None:
    """Clear the search box and its cached results after a successful add,
    so the page returns to a clean state instead of re-offering a company
    that is now tracked."""
    for key in ("picked_company", "discovery", "search_query",
                "search_results", "searched_query"):
        st.session_state.pop(key, None)


def _probe(name: str, domain: str):
    """Cached so re-renders (every keystroke commit, every toggle) don't
    re-hit the ATS APIs for results already on screen."""
    from src.fetchers.ats_api import probe_board
    return probe_board(name, domain)


st.title("Companies")
st.markdown(
    '<p class="lead">Search for a company by name — its careers page is found and '
    "verified automatically, then checked for new roles every day.</p>",
    unsafe_allow_html=True,
)

with st.expander("Add a company", expanded=not db.list_companies()):
    picked = st.session_state.get("picked_company")

    if picked:
        # Show the selected company + discovery status right here, at the
        # top — not below a long results list that needs scrolling past.
        st.markdown(f"**Selected:** {picked['name']} (`{picked['domain']}`)")
        if st.button("← Back to search results"):
            st.session_state.pop("picked_company", None)
            st.session_state.pop("discovery", None)
            st.rerun()

        if "discovery" not in st.session_state:
            # The search list already probed for an ATS board. When it found
            # one, that IS the answer — re-running full discovery would just
            # rediscover it in 30-90s. Reuse it and skip straight to Save.
            prefetched = st.session_state.pop("prefetched_portal", None)
            if prefetched:
                st.session_state["discovery"] = {
                    "found": True, "ok": True, "url": prefetched["board_url"],
                    "ats_type": prefetched["ats_type"], "ats_identifier": prefetched["slug"],
                    "tier": "ats_api", "job_count": prefetched["job_count"],
                    "attempted": [], "gemini_status": "not_needed", "timed_out": False,
                }
            else:
                status = st.status(f"Finding {picked['name']}'s career page…", expanded=True)
                st.session_state["discovery"] = discover_career_url(
                    picked["domain"], picked["name"],
                    on_progress=lambda msg: status.update(label=msg),
                )
                status.update(label="Done", state="complete", expanded=False)
        discovery = st.session_state["discovery"]

        if discovery["found"]:
            st.success(
                f"Found it: `{discovery['url']}` — detected **{discovery['ats_type'] or 'no known ATS, but JSON-LD data found'}** "
                f"via `{discovery['tier']}`, {discovery['job_count']} job(s)."
            )
            if st.button("💾 Save company", type="primary"):
                name = picked["name"]
                if db.get_company_by_name(name):
                    st.error(f"A company named '{name}' already exists.")
                else:
                    company_id = db.add_company(name, discovery["url"])
                    if discovery.get("ats_type"):
                        db.update_company(
                            company_id, ats_type=discovery["ats_type"],
                            ats_identifier=discovery["ats_identifier"], ats_detected_at=db._now(),
                        )
                    db.set_company_run_status(company_id, "ok", job_count=discovery["job_count"])
                    for key in ("picked_company", "discovery", "search_query", "search_results", "searched_query"):
                        st.session_state.pop(key, None)
                    st.success(f"Added {name}.")
                    st.rerun()
        else:
            if discovery.get("timed_out"):
                st.error("Discovery took too long (90s budget) and was stopped partway through — some candidates below weren't tried. Paste the URL manually, or try again.")
            gemini_status = discovery.get("gemini_status")
            if gemini_status == "rate_limited":
                st.error("AI search (Gemini) hit its rate limit — falling back to basic pattern guessing only. Try again in a bit, or paste the URL manually below.")
            elif gemini_status == "budget_exceeded":
                st.warning("This app's own daily AI usage cap has been reached — falling back to basic pattern guessing. Resets tomorrow (UTC).")
            elif gemini_status == "not_configured":
                st.caption("AI search isn't configured (no GEMINI_API_KEY) — only basic pattern guessing was tried.")
            elif gemini_status == "unavailable":
                st.caption("AI search was temporarily unavailable — only basic pattern guessing was tried.")
            st.warning("Couldn't auto-detect a career page for this domain. Paste the exact URL manually below.")
            manual_url = st.text_input("Career page URL", key="manual_url", placeholder=f"https://{picked['domain']}/careers")
            if st.button("🔍 Check this URL", disabled=not manual_url):
                with st.spinner("Checking…"):
                    result = preview_detect_and_fetch(manual_url)
                st.session_state["discovery"] = {"found": result["ok"], "url": manual_url, **result, "attempted": []}
                st.rerun()
            with st.expander("What was tried automatically"):
                for a in discovery["attempted"]:
                    st.caption(f"`{a['url']}` — {'OK' if a['ok'] else a['error']}")

    else:
        # No separate "Search" button — text_input already commits on Enter
        # or on losing focus (tab/click away), so typing a name and pressing
        # Enter (or just clicking elsewhere) re-searches automatically. We
        # detect a changed, committed query below and re-run the search for
        # it, showing a spinner for that exact lookup.
        query = st.text_input("Company name", key="search_query", placeholder="e.g. Stripe (press Enter)")

        query = query.strip()
        if not query:
            st.session_state.pop("searched_query", None)
            st.session_state.pop("search_results", None)
        elif len(query) >= 2 and query != st.session_state.get("searched_query"):
            with st.spinner(f"Searching for \"{query}\"…"):
                raw_results = search_companies(query)
                st.session_state["search_results"] = rerank_company_matches(query, raw_results)
            st.session_state["searched_query"] = query

        # Registry first. A curated entry needs no detection, no probing and
        # no network round-trip, so a known name is one click from tracked.
        known = registry.lookup(query) if query else None
        if known:
            ats, _ = registry.parse_method(known["method"])
            with st.container(border=True):
                row = st.columns([0.6, 4, 1.4])
                row[0].markdown(
                    logo_img(registry.logo_for(known["domain"]) or ""),
                    unsafe_allow_html=True,
                )
                label = (
                    chip(f"{ats} · verified", "ok") if ats
                    else chip("needs setup", "warn")
                )
                row[1].markdown(
                    f"**{known['name']}** &nbsp; {label}<br>"
                    f"<span class='muted'>{known['domain'] or ''}</span>",
                    unsafe_allow_html=True,
                )
                already = db.get_company_by_name(known["name"])
                if already:
                    row[2].button("Already tracked", disabled=True, key="known_dupe")
                elif row[2].button("Add", type="primary", key="known_add"):
                    db.add_company(known["name"])
                    st.success(f"Added {known['name']}.")
                    _reset_search()
                    st.rerun()

        results = st.session_state.get("search_results", [])
        if "searched_query" in st.session_state:
            # Say so when AI narrowing is off. Without this the user just
            # sees sub-brands and spin-offs mixed into the results and
            # reasonably concludes the feature is broken, rather than
            # degraded for a known, temporary reason.
            ai_ok, ai_reason = ai_status()
            if not ai_ok and len(results) > 1:
                st.caption(
                    "Ranked by name and domain — best match first. "
                    f"AI narrowing is off ({ai_reason})"
                )
            if not results and not known:
                st.caption(
                    f"No matches for \"{st.session_state['searched_query']}\"."
                )
                # Saving the plain name is always better than making the user
                # hunt for a careers URL. It gets picked up next time the
                # registry is reviewed; until then it is simply skipped.
                if st.button(
                    f"Save \"{st.session_state['searched_query']}\" for later",
                    key="save_pending",
                ):
                    name = st.session_state["searched_query"]
                    if db.get_company_by_name(name):
                        st.warning(f"{name} is already in the list.")
                    else:
                        db.add_company(name)
                        st.success(
                            f"Saved {name}. It will not be scanned until a "
                            "fetch method is added for it."
                        )
                        _reset_search()
                        st.rerun()

            for r in results:
                with st.container(border=True):
                    row = st.columns([0.6, 4, 1.2])
                    row[0].markdown(logo_img(r["logo_url"]), unsafe_allow_html=True)

                    # Probe for a known ATS board up front, so you can see
                    # which results are actually trackable before picking
                    # one — rather than selecting, waiting through full
                    # discovery, and only then finding out.
                    portal = _probe(r["name"], r["domain"])
                    if portal:
                        badge = chip(f"{portal['ats_type']} · {portal['job_count']} roles", "ok")
                    else:
                        badge = chip("needs a deeper check", "neutral")

                    row[1].markdown(
                        f'<div class="row-title">{r["name"]}</div>'
                        f'<div class="row-sub">{r["domain"]}</div>'
                        f'<div style="margin-top:.3rem">{badge}</div>',
                        unsafe_allow_html=True,
                    )
                    if row[2].button("Select", key=f"pick_{r['domain']}", use_container_width=True):
                        st.session_state["picked_company"] = r
                        st.session_state["prefetched_portal"] = portal
                        st.session_state.pop("discovery", None)
                        st.rerun()

companies = db.list_companies()
if not companies:
    st.info("No companies yet — search for one above.")
else:
    st.subheader(f"Tracked companies ({len(companies)})")
    for c in companies:
        with st.container(border=True):
            cols = st.columns([0.5, 3, 3, 1.3, 1.3, 0.7])
            cols[0].markdown(logo_img(c.get("logo_url") or favicon_url(c["url"])), unsafe_allow_html=True)
            cols[1].markdown(
                f'<div class="row-title">{c["name"]}</div>'
                f'<div class="row-sub"><a href="{c["url"]}">{c["url"]}</a></div>',
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

            cols[2].markdown(
                " ".join(chips)
                + f'<div class="meta">Checked {to_ist(c.get("last_checked_at"))}</div>',
                unsafe_allow_html=True,
            )
            if c.get("last_error"):
                cols[2].caption(str(c["last_error"])[:160])

            new_enabled = cols[3].toggle("Active", value=bool(c["enabled"]), key=f"enabled_{c['id']}")
            if new_enabled != bool(c["enabled"]):
                db.update_company(c["id"], enabled=1 if new_enabled else 0)
                st.rerun()

            if cols[4].button("Re-check", key=f"recheck_{c['id']}", help="Detect the ATS and test-fetch right now", use_container_width=True):
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
