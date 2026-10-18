"""Custom sidebar navigation.

Streamlit's built-in sidebar nav renders a bare list of page filenames with
no branding, icons, grouping, or meaningful active state — it reads as
scaffolding rather than part of the product. style.py hides it; this
replaces it with real nav items plus a brand block and a live status line.

Call render_sidebar() immediately after inject_style() on every page.
"""
import streamlit as st

_PAGES = [
    ("app.py", "Overview", ":material/dashboard:"),
    ("pages/1_Companies.py", "Companies", ":material/apartment:"),
    ("pages/2_Jobs.py", "Jobs", ":material/work:"),
    ("pages/3_Filters.py", "Filters", ":material/tune:"),
]


def render_sidebar(status_note: str | None = None) -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand">'
            '<div class="brand-mark">JA</div>'
            '<div><div class="brand-name">Job Alerts</div>'
            '<div class="brand-sub">Daily role tracker</div></div>'
            "</div>",
            unsafe_allow_html=True,
        )

        for path, label, icon in _PAGES:
            st.page_link(path, label=label, icon=icon)

        notes = [status_note] if status_note else []

        # Surface AI availability everywhere, not just where a feature
        # happens to use it — a degraded AI tier otherwise shows up only as
        # mysteriously worse results on one page.
        try:
            from src.webutil import ai_status
            ai_ok, ai_reason = ai_status()
            notes.append(("AI on — " if ai_ok else "AI off — ") + ai_reason)
        except Exception:
            pass

        if notes:
            st.markdown('<div class="nav-section">Status</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="meta">{"<br>".join(notes)}</div>', unsafe_allow_html=True)
