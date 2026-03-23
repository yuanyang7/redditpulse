"""Streamlit GUI for RedditPulse."""

import json
import subprocess
import sys

import streamlit as st
import pandas as pd

try:
    from . import core
except ImportError:
    # Running directly via `streamlit run` — add package root to path
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from redditpulse import core


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="RedditPulse", page_icon="📊", layout="wide")


# ---------------------------------------------------------------------------
# Sidebar — topic selection & search controls
# ---------------------------------------------------------------------------
def _refresh_topics():
    """Fetch all topics from DB and cache in session state."""
    st.session_state["topics"] = core.list_topics()


if "topics" not in st.session_state:
    _refresh_topics()

with st.sidebar:
    st.title("📊 RedditPulse")
    st.markdown("---")

    # ------ Existing topics ------
    topics = st.session_state["topics"]
    topic_names = [t["name"] for t in topics]

    if topic_names:
        selected = st.selectbox("Select topic", topic_names, key="topic_select")
    else:
        selected = None
        st.info("No topics yet. Create one below.")

    # ------ New topic search ------
    st.markdown("### New Search")
    new_topic = st.text_input("Topic", placeholder="e.g. AI and privacy")

    col1, col2 = st.columns(2)
    with col1:
        limit = st.number_input("Limit", min_value=1, max_value=100, value=30)
    with col2:
        time_filter = st.selectbox("Time", ["month", "week", "day", "hour", "year", "all"])

    subreddits = st.text_input("Subreddits", placeholder="all (comma-separated)")
    use_public = st.checkbox("Use public API (no credentials)", value=False)
    min_relevance = st.slider("Min relevance (0 = off)", 0.0, 1.0, 0.0, 0.05,
                              help="Semantic similarity threshold. Try 0.3 to filter off-topic comments.")

    if st.button("🔍 Search", use_container_width=True, type="primary"):
        if not new_topic.strip():
            st.warning("Enter a topic first.")
        else:
            with st.spinner(f"Searching Reddit for \"{new_topic}\"..."):
                try:
                    result = core.search_topic(
                        topic=new_topic.strip(),
                        subreddits=subreddits.split(",") if subreddits.strip() else None,
                        limit=limit,
                        time_filter=time_filter,
                        public=use_public,
                        refresh=True,
                        min_relevance=min_relevance if min_relevance > 0 else None,
                    )
                    _refresh_topics()
                    st.session_state["topic_select"] = new_topic.strip()
                    msg = (
                        f"Found {result['fetched']} comments, "
                        f"inserted {result['new_comments']} new "
                        f"(total: {result['total_comments']})"
                    )
                    if "filtered_out" in result:
                        msg += f" — filtered out {result['filtered_out']} irrelevant"
                    st.success(msg)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    # ------ Refresh / Reset for selected topic ------
    if selected:
        st.markdown("---")
        st.markdown(f"**Active:** {selected}")
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            if st.button("🔄 Refresh", use_container_width=True):
                with st.spinner("Fetching more comments..."):
                    try:
                        result = core.search_topic(selected, refresh=True, public=use_public,
                                                   min_relevance=min_relevance if min_relevance > 0 else None)
                        _refresh_topics()
                        st.success(f"+{result['new_comments']} new comments")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
        with rc2:
            if st.button("🔁 Re-fetch", use_container_width=True,
                         help="Clear comments and re-fetch, keeping keywords and past analyses"):
                with st.spinner("Re-fetching comments..."):
                    try:
                        result = core.search_topic(selected, reset_comments=True, keep_analyses=True,
                                                   public=use_public,
                                                   min_relevance=min_relevance if min_relevance > 0 else None)
                        _refresh_topics()
                        st.success(f"Re-fetched: {result['new_comments']} comments (analyses kept)")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
        with rc3:
            if st.button("🗑 Reset All", use_container_width=True,
                         help="Clear comments AND analyses, then re-fetch"):
                with st.spinner("Resetting..."):
                    try:
                        core.search_topic(selected, reset_comments=True, public=use_public,
                                          min_relevance=min_relevance if min_relevance > 0 else None)
                        _refresh_topics()
                        st.success("Comments & analyses cleared, re-fetched")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))


# ---------------------------------------------------------------------------
# Main area — tabs
# ---------------------------------------------------------------------------
if not selected:
    st.markdown("## Welcome to RedditPulse")
    st.markdown("Create a topic in the sidebar to get started.")
    st.stop()

tab_dash, tab_analyze, tab_browse, tab_export = st.tabs(
    ["📈 Dashboard", "🔬 Analyze", "💬 Browse", "📁 Export"]
)

# ========================== DASHBOARD TAB ==========================
with tab_dash:
    try:
        summary = core.get_topic_summary(selected)
    except core.TopicNotFoundError:
        st.error("Topic not found.")
        st.stop()

    # Metrics row
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Comments", summary["comment_count"])
    mc2.metric("Keywords", len(summary["keywords"].split(",")))
    mc3.metric("Created", summary["created_at"][:10])

    st.markdown(f"**Keywords:** {summary['keywords']}")

    analysis = summary.get("latest_analysis")
    if analysis and analysis.get("sentiment"):
        st.markdown("---")
        st.subheader("Latest Analysis")
        st.caption(f"Run at {analysis['run_at'][:19]}  •  {analysis['num_comments']} comments analyzed")

        sent = analysis["sentiment"]
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Positive", sent.get("positive", 0))
        sc2.metric("Neutral", sent.get("neutral", 0))
        sc3.metric("Negative", sent.get("negative", 0))
        sc4.metric("Avg Compound", f"{sent.get('average_compound', 0):.3f}")

        # Sentiment bar chart
        chart_data = pd.DataFrame({
            "Sentiment": ["Positive", "Neutral", "Negative"],
            "Count": [sent.get("positive", 0), sent.get("neutral", 0), sent.get("negative", 0)],
        })
        st.bar_chart(chart_data, x="Sentiment", y="Count", color="Sentiment")

        # Themes summary
        themes = analysis.get("themes")
        if themes:
            if "themes" in themes:
                st.subheader("Top Themes")
                df = pd.DataFrame(themes["themes"][:10])
                if not df.empty:
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
    else:
        st.info("No analysis yet. Go to the **Analyze** tab to run one.")


# ========================== ANALYZE TAB ==========================
with tab_analyze:
    st.subheader(f"Analyze: {selected}")

    ac1, ac2 = st.columns(2)
    with ac1:
        analyze_limit = st.number_input("Max comments", min_value=10, max_value=2000, value=500, key="analyze_limit")
    with ac2:
        sentiment_only = st.checkbox("Sentiment only (skip Claude)", value=False, key="sentiment_only")

    reset_analyses = st.checkbox("Clear previous analyses first", value=False, key="reset_analyses")

    if st.button("🔬 Run Analysis", use_container_width=True, type="primary"):
        mode = "sentiment-only" if sentiment_only else "full"
        with st.spinner(f"Running {mode} analysis on {selected}..."):
            try:
                result = core.analyze_topic(
                    topic=selected,
                    limit=analyze_limit,
                    sentiment_only=sentiment_only,
                    reset_analyses=reset_analyses,
                )
                st.session_state["last_analysis"] = result
                _refresh_topics()
                st.success("Analysis complete!")
            except (core.TopicNotFoundError, core.NoCommentsError) as e:
                st.error(str(e))

    # Display results
    result = st.session_state.get("last_analysis")
    if result:
        st.markdown("---")

        # Sentiment
        sent = result["sentiment"]
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Positive", sent["positive"])
        sc2.metric("Neutral", sent["neutral"])
        sc3.metric("Negative", sent["negative"])
        sc4.metric("Avg Compound", f"{sent['average_compound']:.3f}")

        chart_data = pd.DataFrame({
            "Sentiment": ["Positive", "Neutral", "Negative"],
            "Count": [sent["positive"], sent["neutral"], sent["negative"]],
        })
        st.bar_chart(chart_data, x="Sentiment", y="Count", color="Sentiment")

        themes = result.get("themes", {})

        # Themes
        if "themes" in themes:
            st.subheader("Themes")
            df = pd.DataFrame(themes["themes"][:10])
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)

        # Emotions
        if "emotions" in themes:
            st.subheader("Emotions")
            df = pd.DataFrame(themes["emotions"][:8])
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)

        # Opinions
        if "opinions" in themes:
            st.subheader("Key Opinions")
            df = pd.DataFrame(themes["opinions"][:8])
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)

        # Controversy
        if "controversy_level" in themes:
            level = themes["controversy_level"]
            if isinstance(level, dict):
                st.info(f"**Controversy:** {level.get('level', '?')} — {level.get('explanation', '')}")
            else:
                st.info(f"**Controversy:** {level}")

        # Key insights
        if "key_insights" in themes:
            st.subheader("Key Insights")
            for insight in themes["key_insights"]:
                st.markdown(f"- {insight}")


# ========================== BROWSE TAB ==========================
with tab_browse:
    st.subheader(f"Browse Comments: {selected}")

    bc1, bc2 = st.columns(2)
    with bc1:
        browse_sentiment = st.radio(
            "Sentiment filter",
            ["negative", "positive", "neutral"],
            horizontal=True,
            key="browse_sentiment",
        )
    with bc2:
        browse_limit = st.number_input("Max comments", min_value=5, max_value=200, value=20, key="browse_limit")

    if st.button("💬 Load Comments", use_container_width=True):
        with st.spinner("Loading comments..."):
            try:
                data = core.browse_comments(
                    topic=selected,
                    sentiment=browse_sentiment,
                    limit=browse_limit,
                )
                st.session_state["browse_data"] = data
            except core.TopicNotFoundError as e:
                st.error(str(e))

    data = st.session_state.get("browse_data")
    if data:
        st.caption(f"Showing {data['total']} {data['sentiment']} comments")
        color_map = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}
        icon = color_map.get(data["sentiment"], "")

        for c in data["comments"]:
            with st.container(border=True):
                st.markdown(
                    f"{icon} **r/{c['subreddit']}** · "
                    f"score: {c['score']} · "
                    f"vader: {c['compound']:+.2f}"
                )
                st.markdown(c["body"])


# ========================== EXPORT TAB ==========================
with tab_export:
    st.subheader(f"Export: {selected}")

    try:
        data = core.export_analysis(selected)
        st.caption(f"Analysis from {data['run_at'][:19]}")

        json_str = json.dumps(data["result"], indent=2)

        st.download_button(
            label="📥 Download JSON",
            data=json_str,
            file_name=f"{selected.replace(' ', '_')}_analysis.json",
            mime="application/json",
            use_container_width=True,
        )

        with st.expander("Preview JSON", expanded=False):
            st.json(data["result"])

    except core.NoAnalysisError:
        st.info("No analysis to export. Run an analysis first.")
    except core.TopicNotFoundError:
        st.error("Topic not found.")


# ---------------------------------------------------------------------------
# Entry point for `redditpulse-gui` command
# ---------------------------------------------------------------------------
def main():
    """Launch Streamlit app via subprocess."""
    import os
    script_path = os.path.abspath(__file__)
    subprocess.run([sys.executable, "-m", "streamlit", "run", script_path, "--server.headless=true"])
