"""Shared visual system.

Direction: this is a tool you open daily to triage a job hunt — closer in
spirit to an inbox or a dev tool than to a landing page. So: cool neutral
surfaces, a strong typographic hierarchy, dense-but-breathable rows, and
exactly one accent colour doing the work. Amber is reserved strictly for
"something needs your attention" so it never competes with the accent.

Deliberately avoided: the warm-cream/serif/terracotta combination, uniform
rounded cards with identical shadows, tracked-out ALL-CAPS eyebrow labels,
and metadata rendered as middle-dot-joined strings — all of which read as
generic template defaults rather than decisions.
"""
import streamlit as st

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
    --canvas:      #FAFAFB;
    --surface:     #FFFFFF;
    --ink:         #15161A;
    --muted:       #6B7280;
    --line:        #E6E7EB;
    --line-strong: #D3D5DA;

    --accent:      #4F46E5;
    --accent-deep: #3730A3;
    --accent-soft: #EEF2FF;

    --ok:          #047857;
    --ok-soft:     #ECFDF5;
    --warn:        #B45309;
    --warn-soft:   #FFFBEB;
    --danger:      #B91C1C;
    --danger-soft: #FEF2F2;

    --r-sm: 6px;
    --r-md: 10px;
}

/* ---------- Foundations ---------- */

html, body,
[data-testid="stAppViewContainer"],
[data-testid="stHeader"] {
    background-color: var(--canvas) !important;
}

body, p, div, span, label, li, input, textarea {
    font-family: 'IBM Plex Sans', system-ui, sans-serif;
    color: var(--ink);
}

h1, h2, h3, h4 {
    font-family: 'Space Grotesk', system-ui, sans-serif !important;
    color: var(--ink);
    letter-spacing: -0.02em;
    font-weight: 600;
}
h1 { font-size: 1.9rem !important; line-height: 1.15; }
h2 { font-size: 1.35rem !important; }
h3 { font-size: 1.05rem !important; }

/* Page intro: a plain lead paragraph, not an eyebrow + hero stack */
.lead {
    color: var(--muted);
    font-size: 1rem;
    line-height: 1.55;
    max-width: 68ch;
    margin: -0.25rem 0 0.5rem;
}

a, a:visited { color: var(--accent-deep); text-decoration-thickness: 1px; }

/* Visible keyboard focus everywhere (Streamlit's default is faint) */
a:focus-visible,
button:focus-visible,
input:focus-visible,
textarea:focus-visible,
[role="button"]:focus-visible {
    outline: 2px solid var(--accent) !important;
    outline-offset: 2px !important;
    border-radius: var(--r-sm);
}

/* ---------- Sidebar ---------- */

[data-testid="stSidebar"] {
    background: var(--surface);
    border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] > div { padding-top: 0.5rem; }

/* Replaced by the custom nav in ui/nav.py — Streamlit's default renders a
   bare list of filenames with no hierarchy, icons, or active state. */
[data-testid="stSidebarNav"] { display: none; }

.brand {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.3rem 0.25rem 0.9rem;
    margin-bottom: 0.4rem;
    border-bottom: 1px solid var(--line);
}
.brand-mark {
    width: 30px; height: 30px;
    border-radius: 8px;
    background: var(--accent);
    color: #fff;
    display: grid; place-items: center;
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700; font-size: 0.95rem;
    flex: 0 0 auto;
}
.brand-name {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600; font-size: 0.98rem; line-height: 1.1;
}
.brand-sub { color: var(--muted); font-size: 0.73rem; }

/* st.page_link styled as real nav items with a clear active state */
[data-testid="stSidebar"] [data-testid="stPageLink"] a {
    display: flex; align-items: center; gap: 0.6rem;
    padding: 0.5rem 0.65rem;
    margin: 0.12rem 0;
    border-radius: var(--r-sm);
    color: var(--ink) !important;
    font-size: 0.92rem;
    font-weight: 500;
    text-decoration: none !important;
    transition: background-color .12s ease;
}
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
    background: var(--accent-soft);
}
[data-testid="stSidebar"] [data-testid="stPageLink"][aria-current="page"] a,
[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] {
    background: var(--accent-soft);
    color: var(--accent-deep) !important;
    font-weight: 600;
    box-shadow: inset 2px 0 0 var(--accent);
}

.nav-section {
    color: var(--muted);
    font-size: 0.72rem;
    font-weight: 600;
    padding: 0.9rem 0.65rem 0.3rem;
}

/* ---------- Cards / rows ---------- */

div[data-testid="stContainer"] > div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--surface);
    border: 1px solid var(--line) !important;
    border-radius: var(--r-md);
    transition: border-color .12s ease;
}
div[data-testid="stContainer"] > div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: var(--line-strong) !important;
}

/* ---------- Metrics ---------- */

div[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--r-md);
    padding: 0.85rem 1rem;
}
div[data-testid="stMetric"] label p {
    color: var(--muted) !important;
    font-size: 0.78rem !important;
    font-weight: 500;
}
div[data-testid="stMetricValue"] {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.75rem !important;
    color: var(--ink) !important;
}
div[data-testid="stMetricDelta"] { font-size: 0.75rem; }

/* ---------- Buttons ---------- */

button[kind="primary"] {
    background: var(--accent) !important;
    border: 1px solid var(--accent) !important;
    border-radius: var(--r-sm) !important;
    font-weight: 600;
}
button[kind="primary"]:hover {
    background: var(--accent-deep) !important;
    border-color: var(--accent-deep) !important;
}
button[kind="primary"] p { color: #FFFFFF !important; }

button[kind="secondary"] {
    border-radius: var(--r-sm) !important;
    border: 1px solid var(--line-strong) !important;
    background: var(--surface) !important;
    font-weight: 500;
}
button[kind="secondary"]:hover {
    border-color: var(--accent) !important;
    color: var(--accent-deep) !important;
}

/* ---------- Status chips (replaces "a · b · c" meta strings) ---------- */

.chip {
    display: inline-flex; align-items: center; gap: 0.3rem;
    padding: 0.14rem 0.5rem;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 600;
    line-height: 1.5;
    white-space: nowrap;
}
.chip-ok      { background: var(--ok-soft);     color: var(--ok); }
.chip-warn    { background: var(--warn-soft);   color: var(--warn); }
.chip-danger  { background: var(--danger-soft); color: var(--danger); }
.chip-neutral { background: #F3F4F6;            color: var(--muted); }
.chip-accent  { background: var(--accent-soft); color: var(--accent-deep); }

.meta {
    color: var(--muted);
    font-size: 0.8rem;
    line-height: 1.6;
}
.meta b { color: var(--ink); font-weight: 600; }

/* ---------- Company / job rows ---------- */

img.company-logo {
    width: 30px; height: 30px;
    border-radius: 7px;
    object-fit: contain;
    border: 1px solid var(--line);
    background: var(--surface);
    padding: 2px;
}
.row-title {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
    font-size: 0.97rem;
    line-height: 1.3;
}
.row-sub {
    color: var(--muted);
    font-size: 0.8rem;
    font-family: ui-monospace, 'SFMono-Regular', monospace;
    word-break: break-all;
}

/* Wide content must scroll inside itself, never the page body */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    overflow-x: auto;
}

/* ---------- Mobile ---------- */

@media (max-width: 640px) {
    .block-container {
        padding: 1rem 0.9rem 3rem !important;
    }
    h1 { font-size: 1.5rem !important; }
    h2 { font-size: 1.2rem !important; }
    .lead { font-size: 0.94rem; }

    /* Streamlit keeps columns side-by-side at any width, which squeezes
       6-column rows into unreadable slivers on a phone. Stack them. */
    div[data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.4rem !important; }
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }

    /* Comfortable touch targets */
    button, [role="button"] { min-height: 44px; }
    div[data-testid="stMetric"] { padding: 0.7rem 0.8rem; }
    div[data-testid="stMetricValue"] { font-size: 1.4rem !important; }
}

/* Respect reduced-motion preferences */
@media (prefers-reduced-motion: reduce) {
    * { transition: none !important; animation: none !important; }
}

/* --- Streamlit Cloud chrome -------------------------------------------
   The hosting toolbar (Fork / GitHub / Manage app) and the corner badge
   belong to the platform, not to this app, and they sit on top of page
   content. Hidden so the dashboard reads as its own thing. */
[data-testid="stToolbar"],
[data-testid="stToolbarActions"],
[data-testid="stAppDeployButton"],
[data-testid="stStatusWidget"],
.stAppDeployButton,
#MainMenu,
header[data-testid="stHeader"] a[href*="github.com"],
.viewerBadge_container__r5tak,
.viewerBadge_link__qRIco,
a[href*="streamlit.io/cloud"],
footer {
  display: none !important;
  visibility: hidden !important;
}

/* Streamlit renames the badge's hashed classes between releases, so match
   on the stable part of the name rather than a specific build's hash. */
[class*="viewerBadge"],
[data-testid*="ViewerBadge"],
[data-testid="stAppViewerBadge"],
[data-testid="stBottomBlockContainer"] > [data-testid="stDecoration"],
[data-testid="stDecoration"],
div[class*="_profileContainer"],
div[class*="_container"][class*="viewer"],
a[href*="share.streamlit.io"],
a[href*="streamlit.io"][target="_blank"] {
  display: none !important;
}

/* The header still reserves vertical space once emptied. */
header[data-testid="stHeader"] { height: 0; background: transparent; }
</style>

"""


def inject_style() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def logo_img(url: str, size: int = 30) -> str:
    """<img> with the shared company-logo styling, for use inside
    st.markdown(..., unsafe_allow_html=True).

    Neither free icon service covers every company — DuckDuckGo misses several
    Indian firms that Google has, and vice versa — so the tag falls back from
    one to the other and finally removes itself, leaving the caller's
    lettermark visible rather than a broken-image glyph.
    """
    from urllib.parse import urlparse

    fallback = ""
    host = urlparse(url).netloc
    if "duckduckgo" in host:
        domain = url.rsplit("/", 1)[-1].removesuffix(".ico")
        google = f"https://www.google.com/s2/favicons?domain={domain}&amp;sz=128"
        fallback = (
            f"this.onerror=function(){{this.remove()}};this.src='{google}'"
        )
    else:
        fallback = "this.remove()"

    return (
        f'<img class="company-logo" src="{url}" width="{size}" height="{size}" '
        f'alt="" onerror="{fallback}">'
    )


def chip(label: str, kind: str = "neutral") -> str:
    """A small status pill. Replaces the middle-dot-joined metadata strings
    ("cron · 0 new · 1 broken") that made every row read as one grey blur
    with no visual priority."""
    return f'<span class="chip chip-{kind}">{label}</span>'
