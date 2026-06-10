"""Export tab: download the latest saved analysis as JSON."""

import json

import streamlit as st

from redditpulse import services


def render(topic: str) -> None:
    st.subheader(f"Export: {topic}")

    try:
        data = services.export_analysis(topic)
    except services.NoAnalysisError:
        st.info("No analysis to export. Run an analysis first.")
        return
    except services.TopicNotFoundError:
        st.error("Topic not found.")
        return

    st.caption(f"Analysis from {data['run_at'][:19]}")

    json_str = json.dumps(data["result"], indent=2)

    st.download_button(
        label="📥 Download JSON",
        data=json_str,
        file_name=f"{topic.replace(' ', '_')}_analysis.json",
        mime="application/json",
        use_container_width=True,
    )

    with st.expander("Preview JSON", expanded=False):
        st.json(data["result"])
