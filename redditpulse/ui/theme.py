"""Custom CSS theme — arty, flat, modern light look on top of Streamlit."""

import streamlit as st

_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {
    --rp-coral: #FF4D6D;   /* accent */
    --rp-coral-dark: #E0344F; /* button hover */
    --rp-ink:   #181818;   /* text / borders */
    --rp-teal:  #1FB6A6;
    --rp-blue:  #2D5BFF;
    --rp-yellow:#FFC23C;
    --rp-cream: #FBF7F0;
    --rp-sand:  #F3E9D8;
}

/* Flat cream canvas — no gradients, no shadows */
.stApp { background: var(--rp-cream); }
.block-container { padding-top: 2.5rem; }

/* Typography */
html, body, [class*="css"] { font-family: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace; }
.stApp, .stMarkdown, p, span, label, li { color: var(--rp-ink); }
h1, h2, h3, h4 {
    font-family: 'Space Grotesk', sans-serif !important;
    letter-spacing: -0.02em;
    color: var(--rp-ink);
    font-weight: 700 !important;
}
h1 { font-size: 2.6rem !important; }
/* Flat solid accent block behind section headers */
h2, h3 {
    display: inline-block;
    background: var(--rp-coral);
    color: #FFFFFF !important;
    padding: 0.4rem 1.4rem;
    border: 2px solid var(--rp-ink);
    line-height: 1.3;
}

/* Sidebar — flat solid color block with hard edge */
[data-testid="stSidebar"] {
    background: var(--rp-teal);
    border-right: 3px solid var(--rp-ink);
}
[data-testid="stSidebar"] * { color: var(--rp-ink) !important; }
[data-testid="stSidebar"] h1 { color: #FFFFFF !important; font-size: 1.7rem; }
[data-testid="stSidebar"] .stTextInput input,
[data-testid="stSidebar"] .stNumberInput input,
[data-testid="stSidebar"] .stDateInput input,
[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div {
    background: var(--rp-cream) !important;
    border: 2px solid var(--rp-ink) !important;
    color: var(--rp-ink) !important;
}

/* Buttons — flat solid blocks, hard border, no shadow/gradient.
   !important + sidebar-scoped overrides so every button is identical and the
   sidebar's global text-color rule can't repaint the label. */
.stButton  button, .stDownloadButton  button, .stFormSubmitButton  button,
[data-testid="stSidebar"] .stButton  button {
    border-radius: 0 !important;
    border: 2px solid var(--rp-ink) !important;
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 700 !important;
    background: var(--rp-coral) !important;
    color: #FFFFFF !important;
    padding: 0.55rem 1.4rem !important;
    box-shadow: none !important;
    transition: background 0.1s ease;
    line-height: 1.3;
    white-space: normal;
    min-height: 2.7rem;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
}
/* Label text: centered, no stray margins, always white */
.stButton  button p, .stDownloadButton  button p, .stFormSubmitButton  button p,
[data-testid="stSidebar"] .stButton  button p {
    margin: 0 !important;
    color: #FFFFFF !important;
}
/* Consistent hover/focus/active — darker coral, never black */
.stButton  button:hover, .stDownloadButton  button:hover, .stFormSubmitButton  button:hover,
.stButton  button:focus, .stButton  button:active,
[data-testid="stSidebar"] .stButton  button:hover,
[data-testid="stSidebar"] .stButton  button:focus {
    background: var(--rp-coral-dark) !important;
    color: #FFFFFF !important;
    border-color: var(--rp-ink) !important;
    box-shadow: none !important;
}

/* Inputs — flat, hard 2px border */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
.stDateInput input,
.stSelectbox [data-baseweb="select"] > div {
    border-radius: 0 !important;
    border: 2px solid var(--rp-ink) !important;
    background: #FFFFFF !important;
}

/* Tabs — flat blocks, solid active fill */
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 2px solid var(--rp-ink); }
.stTabs [data-baseweb="tab"] {
    border-radius: 0;
    padding: 8px 18px;
    font-weight: 600;
    background: var(--rp-sand);
    border: 2px solid var(--rp-ink);
    border-bottom: none;
}
.stTabs [aria-selected="true"] { background: var(--rp-coral); }
.stTabs [aria-selected="true"] * { color: #FFFFFF !important; }

/* Metrics, dataframes & expanders — flat white panels, hard border */
[data-testid="stMetric"], .stDataFrame, [data-testid="stExpander"] {
    background: #FFFFFF;
    border: 2px solid var(--rp-ink);
    border-radius: 0;
    padding: 0.7rem 1rem;
    box-shadow: none;
}
[data-testid="stMetricValue"] { color: var(--rp-coral); font-weight: 700; }

/* Number input — unify field + steppers into one flat bordered block */
[data-testid="stNumberInput"] > div {
    border: 2px solid var(--rp-ink) !important;
    border-radius: 0 !important;
    overflow: hidden;
}
[data-testid="stNumberInput"] input {
    border: none !important;
}
[data-testid="stNumberInput"] button {
    border: none !important;
    border-left: 2px solid var(--rp-ink) !important;
    border-radius: 0 !important;
    background: var(--rp-cream) !important;
    color: var(--rp-ink) !important;
}
[data-testid="stNumberInput"] button:hover {
    background: var(--rp-coral) !important;
    color: #FFFFFF !important;
}

/* Hide Streamlit's default top header bar so the sidebar isn't cut in half */
header[data-testid="stHeader"] { background: transparent; height: 0; }
[data-testid="stSidebar"] > div:first-child { padding-top: 1.25rem; }

/* Dividers — solid ink line */
hr { border-color: var(--rp-ink); border-top-width: 2px; }
</style>
"""


def apply_theme() -> None:
    st.markdown(_THEME_CSS, unsafe_allow_html=True)
