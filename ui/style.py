"""Shared visual system on top of .streamlit/config.toml. Call inject_style()
once near the top of every page.

Palette: warm paper background (not stark white) with a single confident
accent — deep emerald ("moss") for primary actions/progress, warm terracotta
("clay") reserved for things that need attention, so the two never compete.
Type: Manrope for headings (geometric, confident), Inter for body/data
(clean at small sizes) — distinct enough to read as a deliberate pairing.
"""
import streamlit as st

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&family=Inter:wght@400;500;600&display=swap');

:root {
    --paper: #F6F4EF;
    --surface: #FFFFFF;
    --ink: #161A14;
    --moss: #1F6F4F;
    --moss-deep: #124D36;
    --moss-tint: #E7F1EC;
    --clay: #C2553A;
    --clay-tint: #FBEAE5;
    --slate: #6B7280;
    --line: #E7E3D9;
}

html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    background-color: var(--paper) !important;
}

h1, h2, h3, h4 {
    font-family: 'Manrope', sans-serif !important;
    color: var(--ink);
    letter-spacing: -0.01em;
    font-weight: 700;
}

body, p, div, span, label, li {
    font-family: 'Inter', sans-serif;
    color: var(--ink);
}

/* De-emphasize the generic tracked-caps "eyebrow" treatment where present */
.hero-kicker {
    text-transform: none !important;
    letter-spacing: 0 !important;
    font-size: 0.85rem !important;
    color: var(--moss) !important;
    font-weight: 600;
    font-family: 'Inter', sans-serif;
}
.hero-copy {
    color: var(--slate);
    font-size: 1.02rem;
    max-width: 62ch;
}

/* Cards: subtle warm border, no generic grey drop-shadow-everywhere */
div[data-testid="stContainer"] > div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--surface);
    border: 1px solid var(--line) !important;
    border-radius: 12px;
    transition: border-color 0.15s ease;
}
div[data-testid="stContainer"] > div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: var(--moss) !important;
}

/* Metric tiles: colored left accent instead of flat grey boxes */
div[data-testid="stMetric"] {
    background: var(--surface);
    border-radius: 10px;
    padding: 14px 18px;
    border: 1px solid var(--line);
    border-left: 4px solid var(--moss);
}
div[data-testid="stMetric"] label {
    color: var(--slate) !important;
    font-weight: 500;
}
div[data-testid="stMetricValue"] {
    color: var(--ink) !important;
    font-family: 'Manrope', sans-serif;
}
/* "Needs attention" style metrics use delta_color="inverse" — recolor that
   pill to our clay accent instead of the washed default pink, with real
   contrast (dark text on a tinted chip, not light-on-light). */
div[data-testid="stMetricDelta"] {
    background: var(--clay-tint);
    border-radius: 6px;
    padding: 2px 8px;
    display: inline-block;
}
div[data-testid="stMetricDelta"] div {
    color: var(--clay) !important;
}

/* Primary button: solid, high-contrast, real hover state */
button[kind="primary"] {
    background-color: var(--moss) !important;
    border-color: var(--moss) !important;
    color: #FFFFFF !important;
    border-radius: 8px;
    font-weight: 600;
}
button[kind="primary"]:hover {
    background-color: var(--moss-deep) !important;
    border-color: var(--moss-deep) !important;
}
button[kind="primary"] p {
    color: #FFFFFF !important;
}

button[kind="secondary"] {
    border-radius: 8px;
    border-color: var(--line) !important;
}

a, a:visited {
    color: var(--moss-deep);
}

img.company-logo {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    object-fit: cover;
    border: 1px solid var(--line);
    background: var(--surface);
    vertical-align: middle;
}
.company-row-name {
    font-weight: 600;
    font-size: 0.95rem;
    color: var(--ink);
}
.company-row-domain {
    color: var(--slate);
    font-size: 0.8rem;
    font-family: ui-monospace, monospace;
}

/* --- Mobile: stack side-by-side columns, keep touch targets comfortable --- */
@media (max-width: 640px) {
    .block-container {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        min-width: 100% !important;
        flex: 1 1 100% !important;
    }
    button {
        min-height: 44px;
    }
    h1 { font-size: 1.6rem !important; }
    h2 { font-size: 1.3rem !important; }
}
</style>
"""


def inject_style() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def logo_img(url: str, size: int = 32) -> str:
    """Returns an <img> tag with the circular company-logo styling, for use
    inside st.markdown(..., unsafe_allow_html=True)."""
    return f'<img class="company-logo" src="{url}" width="{size}" height="{size}">'
