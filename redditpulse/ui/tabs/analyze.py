"""Analyze tab: run sentiment + theme analysis and display results."""

import pandas as pd
import streamlit as st

from redditpulse import services
from .. import charts, state


def _show_result(result: dict) -> None:
    st.markdown("---")
    if result.get("cached"):
        st.info("Identical analysis already existed (same comments and settings) — "
                "showing the saved result. No API call was made.")

    sent = result["sentiment"]
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Positive", sent["positive"])
    sc2.metric("Neutral", sent["neutral"])
    sc3.metric("Negative", sent["negative"])
    sc4.metric("Avg Compound", f"{sent['average_compound']:.3f}")

    weighted = sent.get("upvote_weighted")
    if weighted:
        st.caption(
            f"**Upvote-weighted:** {weighted['pct_positive']}% positive · "
            f"{weighted['pct_neutral']}% neutral · {weighted['pct_negative']}% negative · "
            f"avg {weighted['average_compound']:+.3f} "
            f"(each comment weighted by its score)"
        )

    chart_data = pd.DataFrame({
        "Sentiment": ["Positive", "Neutral", "Negative"],
        "Count": [sent["positive"], sent["neutral"], sent["negative"]],
    })
    st.bar_chart(chart_data, x="Sentiment", y="Count", color="Sentiment")

    themes = result.get("themes", {})

    if "themes" in themes:
        st.subheader("Themes")
        df = pd.DataFrame(themes["themes"][:10])
        if not df.empty:
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

    if "opinions" in themes:
        st.subheader("Key Opinions")
        df = pd.DataFrame(themes["opinions"][:8])
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)

    if "controversy_level" in themes:
        level = themes["controversy_level"]
        if isinstance(level, dict):
            st.info(f"**Controversy:** {level.get('level', '?')} — {level.get('explanation', '')}")
        else:
            st.info(f"**Controversy:** {level}")

    if "key_insights" in themes:
        st.subheader("Key Insights")
        for insight in themes["key_insights"]:
            st.markdown(f"- {insight}")


def render(topic: str) -> None:
    st.subheader(f"Analyze: {topic}")

    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        analyze_limit = st.number_input("Max comments", min_value=10, max_value=2000,
                                        value=500, key="analyze_limit")
    with ac2:
        sentiment_model = st.selectbox(
            "Sentiment model", ["claude", "vader"], key="sentiment_model_choice",
            help="vader: local, instant, rule-based. claude: LLM, slower + uses "
                 "API tokens, but far better at sarcasm/context.",
        )
    with ac3:
        min_score = st.number_input(
            "Min upvotes (0 = off)", min_value=0, max_value=1000, value=0,
            key="analyze_min_score",
            help="Only analyze comments with at least this score, so conclusions "
                 "rest on comments the community engaged with.",
        )

    oc1, oc2 = st.columns(2)
    with oc1:
        sentiment_only = st.checkbox("Sentiment only (skip themes)", value=False, key="sentiment_only")
    with oc2:
        reset_analyses = st.checkbox("Clear previous analyses first", value=False, key="reset_analyses")

    if st.button("Run Analysis", use_container_width=True, type="primary"):
        mode = "sentiment-only" if sentiment_only else "full"
        with st.spinner(f"Running {mode} analysis ({sentiment_model}) on {topic}..."):
            try:
                result = services.analyze_topic(
                    topic=topic,
                    limit=analyze_limit,
                    sentiment_only=sentiment_only,
                    reset_analyses=reset_analyses,
                    sentiment_model=sentiment_model,
                    min_score=min_score if min_score > 0 else None,
                )
                st.session_state["last_analysis"] = result
                state.refresh_topics()
                st.success("Analysis complete!")
            except (services.TopicNotFoundError, services.NoCommentsError) as e:
                st.error(str(e))

    result = st.session_state.get("last_analysis")
    if result:
        _show_result(result)
