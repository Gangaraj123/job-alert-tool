"""LinkedIn-style company search: a live dropdown with logos.

Streamlit's own widgets can't do this — selectbox options are plain strings
and text_input doesn't re-run while you type. A custom component owns its
own DOM inside an iframe, so it filters client-side on every keystroke with
no server round-trip, and can render a logo next to each result.

The frontend is static HTML talking the component postMessage protocol
directly, so there is no npm build and nothing to compile.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_BUILD_DIR = Path(__file__).resolve().parent / "components" / "company_search"

_component = components.declare_component("company_search", path=str(_BUILD_DIR))


def company_search(
    items: list[dict],
    *,
    placeholder: str = "Search companies…",
    key: str = "company_search",
) -> str | None:
    """Render the search box and return the name picked this run, if any.

    `items` entries are {"name", "logo", "meta"}. Returns None until the user
    picks something, and the same name can be picked repeatedly — the
    frontend stamps each selection so a repeat still reads as a change.
    """
    result = _component(items=items, placeholder=placeholder, key=key, default=None)
    if not result:
        return None

    name = result.get("name") if isinstance(result, dict) else None
    if not name:
        return None

    # Only report a pick once per selection; without this the value persists
    # across re-runs and the caller would re-add on every interaction.
    stamp = result.get("n")
    seen_key = f"_{key}_last"
    if st.session_state.get(seen_key) == stamp:
        return None
    st.session_state[seen_key] = stamp
    return name
