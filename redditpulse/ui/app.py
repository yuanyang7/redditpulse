"""Streamlit app entry point: page config, theme, sidebar, tab dispatch."""

import sys
from pathlib import Path

# Running directly via `streamlit run redditpulse/ui/app.py` executes this file
# without package context — make the package importable first.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

st.set_page_config(page_title="RedditPulse", page_icon="📊", layout="wide")

from redditpulse.ui import sidebar, theme  # noqa: E402
from redditpulse.ui.tabs import (  # noqa: E402
    analyze, browse, dashboard, data, evaluate, export, label, showcase, trends,
)

theme.apply_theme()

with st.sidebar:
    selected = sidebar.render()

if not selected:
    st.markdown("## Welcome to RedditPulse")
    st.markdown("Create a topic in the sidebar to get started.")
    st.stop()

TABS = [
    ("Dashboard", dashboard),
    ("Trends", trends),
    ("Analyze", analyze),
    ("Browse", browse),
    ("Data", data),
    ("Label", label),
    ("Evaluate", evaluate),
    ("Showcase", showcase),
    ("Export", export),
]

for tab, (_, module) in zip(st.tabs([name for name, _ in TABS]), TABS):
    with tab:
        module.render(selected)
