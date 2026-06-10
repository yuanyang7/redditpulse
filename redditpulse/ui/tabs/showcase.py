"""Showcase tab: configure how this topic appears on the static showcase
site, and build the site."""

import streamlit as st

from redditpulse import services
from redditpulse.showcase import SECTIONS, build_site, default_config

SECTION_LABELS = {
    "sentiment": "Sentiment overview",
    "trends": "Sentiment over time",
    "themes": "Top themes",
    "emotions": "Emotions",
    "breakdown": "Subtopic breakdown",
    "opinions": "Key opinions",
    "insights": "Key insights",
    "top_comments": "Top comments",
}


def render(topic: str) -> None:
    st.subheader(f"Showcase: {topic}")
    st.caption(
        "The showcase is a static website (GitHub Pages-ready) presenting your "
        "best results. Customize what this topic's page shows, then build the "
        "site — no API calls, everything comes from saved analyses."
    )

    config = services.get_showcase_config(topic) or default_config(topic)

    enabled = st.checkbox("Include this topic on the showcase site",
                          value=config.get("enabled", True), key=f"sc_enabled_{topic}")
    title = st.text_input("Display title", value=config.get("title") or topic,
                          key=f"sc_title_{topic}")
    description = st.text_area(
        "Description / intro text",
        value=config.get("description", ""),
        key=f"sc_desc_{topic}",
        placeholder="What was studied, what stood out, why it's interesting...",
        help="Shown under the title on the topic's page and on its index card.",
    )

    selected_sections = st.multiselect(
        "Sections to show (in order)",
        options=SECTIONS,
        default=[s for s in config.get("sections", SECTIONS) if s in SECTIONS],
        format_func=lambda s: SECTION_LABELS.get(s, s),
        key=f"sc_sections_{topic}",
    )

    st.markdown("**Per-section commentary** (optional, shown above each section)")
    notes = dict(config.get("section_notes") or {})
    for section in selected_sections:
        notes[section] = st.text_input(
            SECTION_LABELS.get(section, section),
            value=notes.get(section, ""),
            key=f"sc_note_{topic}_{section}",
        )

    if st.button("Save showcase settings", use_container_width=True):
        services.set_showcase_config(topic, {
            "enabled": enabled,
            "title": title.strip() or topic,
            "description": description.strip(),
            "sections": selected_sections,
            "section_notes": {k: v.strip() for k, v in notes.items()
                              if k in selected_sections and v.strip()},
        })
        st.success("Saved.")

    st.markdown("---")
    bc1, bc2 = st.columns([1, 2])
    with bc1:
        if st.button("Build showcase site", type="primary", use_container_width=True):
            with st.spinner("Building static site..."):
                out = build_site()
            st.session_state["showcase_built"] = str(out)
    with bc2:
        built = st.session_state.get("showcase_built")
        if built:
            st.success(f"Site built at `{built}/` — open `{built}/index.html` "
                       "or push and enable GitHub Pages (deploy from branch, "
                       "/docs folder).")
