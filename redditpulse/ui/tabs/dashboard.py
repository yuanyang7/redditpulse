"""Dashboard tab: topic overview and latest analysis at a glance."""

import pandas as pd
import streamlit as st

from redditpulse import services
from .. import charts, state


def _sentiment_section(analysis: dict) -> None:
    st.markdown("---")
    st.subheader("Latest Analysis")
    st.caption(f"Run at {analysis['run_at'][:19]}  •  {analysis['num_comments']} comments analyzed")

    sent = analysis["sentiment"]
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Positive", sent.get("positive", 0))
    sc2.metric("Neutral", sent.get("neutral", 0))
    sc3.metric("Negative", sent.get("negative", 0))
    sc4.metric("Avg Compound", f"{sent.get('average_compound', 0):.3f}")

    weighted = sent.get("upvote_weighted")
    if weighted:
        st.caption(
            f"**Upvote-weighted:** {weighted['pct_positive']}% positive · "
            f"{weighted['pct_neutral']}% neutral · {weighted['pct_negative']}% negative "
            f"(each comment weighted by its score)"
        )

    chart_data = pd.DataFrame({
        "Sentiment": ["Positive", "Neutral", "Negative"],
        "Count": [sent.get("positive", 0), sent.get("neutral", 0), sent.get("negative", 0)],
    })
    st.bar_chart(chart_data, x="Sentiment", y="Count", color="Sentiment")


def _themes_section(themes: dict) -> None:
    if "themes" in themes:
        st.subheader("Top Themes")
        df = pd.DataFrame(themes["themes"][:10])
        if not df.empty:
            if "count" in df.columns:
                st.altair_chart(charts.themes_chart(df), use_container_width=True)
            st.dataframe(df, use_container_width=True, hide_index=True)

    if "emotions" in themes:
        st.subheader("Emotions")
        df = pd.DataFrame(themes["emotions"][:8])
        if not df.empty:
            if "prevalence" in df.columns:
                st.altair_chart(charts.emotions_chart(df), use_container_width=True)
            st.dataframe(df, use_container_width=True, hide_index=True)

    breakdown = themes.get("subtopic_breakdown")
    if breakdown and breakdown.get("categories"):
        dimension = breakdown.get("dimension", "Breakdown")
        st.subheader(dimension)
        df = pd.DataFrame(breakdown["categories"])
        if not df.empty:
            if "percentage" in df.columns:
                st.altair_chart(charts.breakdown_chart(df, dimension), use_container_width=True)
            st.dataframe(df, use_container_width=True, hide_index=True)

    if "key_insights" in themes:
        st.subheader("Key Insights")
        for insight in themes["key_insights"]:
            st.markdown(f"- {insight}")

    if "controversy_level" in themes:
        level = themes["controversy_level"]
        if isinstance(level, dict):
            st.info(f"**Controversy:** {level.get('level', '?')} — {level.get('explanation', '')}")
        else:
            st.info(f"**Controversy:** {level}")


def render(topic: str) -> None:
    try:
        summary = services.get_topic_summary(topic)
    except services.TopicNotFoundError:
        st.error("Topic not found.")
        st.stop()

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Comments", summary["comment_count"])
    mc2.metric("Keywords", len(summary["keywords"].split(",")))
    mc3.metric("Created", summary["created_at"][:10])

    st.markdown(f"**Keywords:** {summary['keywords']}")

    note_input = st.text_area(
        "Note",
        value=summary.get("note", ""),
        key=f"note_{topic}",
        placeholder="e.g. v2 — re-fetched after broadening keywords",
        help="Freeform note to help you tell topic versions apart. Saved automatically.",
    )
    if note_input != summary.get("note", ""):
        services.set_topic_note(topic, note_input)
        state.refresh_topics()

    analysis = summary.get("latest_analysis")
    if analysis and analysis.get("sentiment"):
        _sentiment_section(analysis)
        themes = analysis.get("themes")
        if themes:
            _themes_section(themes)
    else:
        st.info("No analysis yet. Go to the **Analyze** tab to run one.")
