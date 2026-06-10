"""Streamlit GUI for RedditPulse."""

import json
import subprocess
import sys

import streamlit as st
import pandas as pd
import altair as alt

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
# Theme — arty, modern, light look (custom CSS on top of the Streamlit theme)
# ---------------------------------------------------------------------------
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
st.markdown(_THEME_CSS, unsafe_allow_html=True)


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

    # Apply any pending topic selection before the selectbox widget is
    # instantiated (session_state for a widget key can't be set after that).
    pending = st.session_state.pop("pending_topic_select", None)
    if pending in topic_names:
        st.session_state["topic_select"] = pending

    if topic_names:
        selected = st.selectbox("Select topic", topic_names, key="topic_select")
    else:
        selected = None
        st.info("No topics yet. Create one below.")

    # Clear cached per-topic results when the selected topic changes, so tabs
    # don't show stale results from a previously viewed topic.
    if st.session_state.get("active_topic") != selected:
        st.session_state["active_topic"] = selected
        for k in ("last_analysis", "browse_data", "eval_result"):
            st.session_state.pop(k, None)

    # ------ New topic search ------
    st.markdown("### New Search")
    new_topic = st.text_input("Topic", placeholder="e.g. AI and privacy")

    # ------ Keyword generation & review ------
    review = st.session_state.get("keyword_review")
    if st.button("Generate Keywords", use_container_width=True):
        if not new_topic.strip():
            st.warning("Enter a topic first.")
        else:
            with st.spinner("Generating keywords..."):
                try:
                    keywords = core.generate_keywords(new_topic.strip())
                    st.session_state["keyword_review"] = {
                        "topic": new_topic.strip(),
                        "text": ", ".join(keywords),
                    }
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    keyword_override = None
    if review and review["topic"] == new_topic.strip():
        edited = st.text_area(
            "Keywords (review and edit before fetching)",
            value=review["text"],
            help="Comma-separated. Edit out anything outdated or irrelevant "
                 "(e.g. drop a stale year) before fetching.",
        )
        keyword_override = [k.strip() for k in edited.split(",") if k.strip()]

    col1, col2 = st.columns(2)
    with col1:
        limit = st.number_input("Limit", min_value=1, max_value=100, value=30)
    with col2:
        time_filter = st.selectbox(
            "Time", ["month", "week", "day", "hour", "6months", "year", "all"],
            format_func=lambda v: "6 months" if v == "6months" else v,
        )

    subreddits = st.text_input("Subreddits", placeholder="all (comma-separated)")
    use_public = st.checkbox(
        "Use public API (no credentials)", value=True,
        help="Fetches via the Arctic Shift archive — no credentials needed and "
             "no Reddit rate limits. Keyword search is scoped to subreddits, so "
             "set the Subreddits field for best results (defaults to a broad list).",
    )
    min_relevance = st.slider("Min relevance (0 = off)", 0.0, 1.0, 0.3, 0.05,
                              help="Semantic similarity threshold. Try 0.3 to filter off-topic comments.")

    if st.button("Search", use_container_width=True, type="primary"):
        if not new_topic.strip():
            st.warning("Enter a topic first.")
        else:
            topic_to_use = core.next_available_topic_name(new_topic.strip(), topic_names)
            with st.spinner(f"Searching Reddit for \"{topic_to_use}\"..."):
                try:
                    result = core.search_topic(
                        topic=topic_to_use,
                        subreddits=subreddits.split(",") if subreddits.strip() else None,
                        limit=limit,
                        time_filter=time_filter,
                        public=use_public,
                        refresh=True,
                        min_relevance=min_relevance if min_relevance > 0 else None,
                        keywords=keyword_override,
                    )
                    _refresh_topics()
                    st.session_state.pop("keyword_review", None)
                    st.session_state["pending_topic_select"] = topic_to_use
                    msg = (
                        f"Found {result['fetched']} comments, "
                        f"inserted {result['new_comments']} new "
                        f"(total: {result['total_comments']})"
                    )
                    if "filtered_out" in result:
                        msg += f" — filtered out {result['filtered_out']} irrelevant"
                    if topic_to_use != new_topic.strip():
                        msg = f"Created '{topic_to_use}' — " + msg
                    st.success(msg)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    # ------ Refresh / Reset for selected topic ------
    if selected:
        st.markdown("---")
        st.markdown(f"**Active:** {selected}")
        if st.button("Refresh", use_container_width=True):
            with st.spinner("Fetching more comments..."):
                try:
                    result = core.search_topic(selected, refresh=True, public=use_public,
                                               min_relevance=min_relevance if min_relevance > 0 else None)
                    _refresh_topics()
                    st.success(f"+{result['new_comments']} new comments")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        if st.button("Re-fetch", use_container_width=True,
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
        if st.button("Reset All", use_container_width=True,
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

        st.markdown("---")
        with st.expander("⚠️ Danger zone"):
            st.markdown(f"Permanently delete **{selected}**, including all its comments and analyses.")
            confirm_delete = st.checkbox(f"I'm sure I want to delete '{selected}'", key="confirm_delete")
            if st.button("Delete topic", use_container_width=True, disabled=not confirm_delete):
                try:
                    core.delete_topic(selected)
                    _refresh_topics()
                    st.session_state.pop("topic_select", None)
                    st.session_state.pop("confirm_delete", None)
                    st.success(f"Deleted '{selected}'")
                    st.rerun()
                except core.TopicNotFoundError as e:
                    st.error(str(e))


# ---------------------------------------------------------------------------
# Main area — tabs
# ---------------------------------------------------------------------------
if not selected:
    st.markdown("## Welcome to RedditPulse")
    st.markdown("Create a topic in the sidebar to get started.")
    st.stop()

tab_dash, tab_trends, tab_analyze, tab_browse, tab_label, tab_evaluate, tab_export = st.tabs(
    ["Dashboard", "Trends", "Analyze", "Browse", "Label", "Evaluate", "Export"]
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
                    if "count" in df.columns:
                        chart = alt.Chart(df).mark_bar(color="#2D5BFF").encode(
                            x=alt.X("count:Q", title="Mentions"),
                            y=alt.Y("theme:N", title="", sort="-x"),
                            tooltip=["theme", "count", "summary"],
                        )
                        st.altair_chart(chart, use_container_width=True)
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


# ========================== TRENDS TAB ==========================
with tab_trends:
    st.subheader(f"Sentiment Over Time: {selected}")
    st.caption(
        "How sentiment shifts across the dates of the comments you fetched. "
        "Sentiment reuses your latest analysis (or VADER if none yet). "
        "Buckets with too few comments are dimmed — widen them or fetch more."
    )

    tc1, tc2 = st.columns(2)
    with tc1:
        bucket_choice = st.selectbox(
            "Bucket size", ["auto", "day", "week", "month"], key="trend_bucket",
            help="auto picks day/week/month based on how wide your date range is.",
        )
    with tc2:
        min_per_bucket = st.number_input(
            "Min comments per bucket", min_value=1, max_value=50, value=3,
            key="trend_min", help="Buckets below this are flagged as too sparse to trust.",
        )

    try:
        trends = core.get_sentiment_trends(
            selected, min_comments=int(min_per_bucket), bucket=bucket_choice
        )
    except (core.TopicNotFoundError, core.NoCommentsError) as e:
        st.info(str(e))
        trends = None

    if trends and trends["points"]:
        pts = trends["points"]
        df = pd.DataFrame(pts)

        rng = trends["date_range"]
        solid = sum(1 for p in pts if not p["sparse"])
        st.markdown(
            f"**{trends['total']}** comments · **{rng[0]} → {rng[1]}** · "
            f"bucketed by **{trends['bucket']}** · sentiment from **{trends['source']}** · "
            f"**{solid}/{len(pts)}** buckets have ≥{trends['min_comments']} comments"
        )
        if trends["source"] == "vader":
            st.caption("No saved analysis yet — using VADER. Run the Analyze tab for Claude-based sentiment here.")

        if trends["bucket"] == "month":
            # Use Altair with an ordinal axis so every month gets its own tick.
            period_order = df["period"].tolist()
            x_enc = alt.X(
                "period:O", title="Month", sort=period_order,
                axis=alt.Axis(labelAngle=-45, labelOverlap=False),
            )

            sentiment_long = df.melt(
                id_vars=["period"], value_vars=["pct_positive", "pct_negative"],
                var_name="Sentiment", value_name="Percent",
            )
            sentiment_long["Sentiment"] = sentiment_long["Sentiment"].map(
                {"pct_positive": "% Positive", "pct_negative": "% Negative"}
            )
            line = alt.Chart(sentiment_long).mark_line(point=True).encode(
                x=x_enc,
                y=alt.Y("Percent:Q", title="% of comments"),
                color=alt.Color(
                    "Sentiment:N", title="",
                    scale=alt.Scale(domain=["% Positive", "% Negative"], range=["#1FB6A6", "#FF4D6D"]),
                ),
            )
            st.markdown("**Sentiment (% of comments per bucket)**")
            st.altair_chart(line, use_container_width=True)

            bar = alt.Chart(df).mark_bar(color="#2D5BFF").encode(
                x=x_enc,
                y=alt.Y("count:Q", title="Comments"),
                tooltip=["period", "count"],
            )
            st.markdown("**Comment volume per bucket**")
            st.altair_chart(bar, use_container_width=True)
        else:
            # Sentiment line: % positive vs % negative across buckets.
            line_df = df.set_index("period")[["pct_positive", "pct_negative"]].rename(
                columns={"pct_positive": "% Positive", "pct_negative": "% Negative"}
            )
            st.markdown("**Sentiment (% of comments per bucket)**")
            st.line_chart(line_df, color=["#1FB6A6", "#FF4D6D"])

            # Volume underneath so sparse buckets are obvious at a glance.
            st.markdown("**Comment volume per bucket**")
            st.bar_chart(df.set_index("period")[["count"]].rename(columns={"count": "Comments"}),
                         color="#2D5BFF")

        sparse = [p for p in pts if p["sparse"]]
        if sparse:
            st.caption(
                f"⚠️ {len(sparse)} sparse bucket(s) with <{trends['min_comments']} comments — "
                "treat those points as noise: " + ", ".join(p["period"] for p in sparse[:8])
                + ("…" if len(sparse) > 8 else "")
            )

        with st.expander("Per-bucket table"):
            st.dataframe(
                df[["period", "count", "positive", "neutral", "negative",
                    "pct_positive", "pct_negative", "avg_compound", "sparse"]],
                use_container_width=True, hide_index=True,
            )
    elif trends:
        st.info("No timestamped comments to chart yet.")


# ========================== ANALYZE TAB ==========================
with tab_analyze:
    st.subheader(f"Analyze: {selected}")

    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        analyze_limit = st.number_input("Max comments", min_value=10, max_value=2000, value=500, key="analyze_limit")
    with ac2:
        sentiment_model = st.selectbox(
            "Sentiment model", ["vader", "claude"], key="sentiment_model_choice",
            help="vader: local, instant, rule-based. claude: LLM, slower + uses "
                 "API tokens, but far better at sarcasm/context.",
        )
    with ac3:
        sentiment_only = st.checkbox("Sentiment only (skip themes)", value=False, key="sentiment_only")

    reset_analyses = st.checkbox("Clear previous analyses first", value=False, key="reset_analyses")

    if st.button("Run Analysis", use_container_width=True, type="primary"):
        mode = "sentiment-only" if sentiment_only else "full"
        with st.spinner(f"Running {mode} analysis ({sentiment_model}) on {selected}..."):
            try:
                result = core.analyze_topic(
                    topic=selected,
                    limit=analyze_limit,
                    sentiment_only=sentiment_only,
                    reset_analyses=reset_analyses,
                    sentiment_model=sentiment_model,
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

    if st.button("Load Comments", use_container_width=True):
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


# ========================== LABEL TAB ==========================
with tab_label:
    st.subheader(f"Label Comments: {selected}")
    st.caption("Assign ground-truth sentiment labels. These are used in the Evaluate tab to benchmark models.")

    lc1, lc2, lc3 = st.columns(3)
    with lc1:
        unlabeled_only = st.checkbox("Show unlabeled only", value=True, key="lbl_unlabeled")
    with lc2:
        label_page_size = st.number_input("Per page", min_value=5, max_value=50, value=10, key="lbl_page_size")
    with lc3:
        label_page = st.number_input("Page", min_value=1, value=1, key="lbl_page")

    try:
        data = core.get_comments_for_labeling(
            selected,
            unlabeled_only=unlabeled_only,
            limit=label_page_size,
            offset=(label_page - 1) * label_page_size,
        )
    except core.TopicNotFoundError as e:
        st.error(str(e))
        st.stop()

    counts = data["counts"]
    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
    cc1.metric("Total", counts["total"])
    cc2.metric("Labeled", counts["labeled"])
    cc3.metric("Positive", counts["breakdown"].get("positive", 0))
    cc4.metric("Neutral", counts["breakdown"].get("neutral", 0))
    cc5.metric("Negative", counts["breakdown"].get("negative", 0))

    st.markdown("---")

    if not data["comments"]:
        st.info("No comments to show. Try unchecking 'Show unlabeled only' or fetch more comments.")
    else:
        LABEL_COLORS = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}
        for c in data["comments"]:
            current = c["manual_label"]
            icon = LABEL_COLORS.get(current, "⬜")
            with st.container(border=True):
                st.markdown(
                    f"{icon} **r/{c['subreddit']}** · score: {c['score']} "
                    + (f"· **{current.upper()}**" if current else "· *unlabeled*")
                )
                st.markdown(c["body"])
                b1, b2, b3, b4 = st.columns(4)
                with b1:
                    if st.button("Positive", key=f"pos_{c['id']}"):
                        core.label_comment(selected, c["id"], "positive")
                        st.rerun()
                with b2:
                    if st.button("Neutral", key=f"neu_{c['id']}"):
                        core.label_comment(selected, c["id"], "neutral")
                        st.rerun()
                with b3:
                    if st.button("Negative", key=f"neg_{c['id']}"):
                        core.label_comment(selected, c["id"], "negative")
                        st.rerun()
                with b4:
                    if current and st.button("Clear", key=f"clr_{c['id']}"):
                        core.label_comment(selected, c["id"], None)
                        st.rerun()


# ========================== EVALUATE TAB ==========================
with tab_evaluate:
    st.subheader(f"Model Evaluation: {selected}")
    st.caption("Compare sentiment model predictions against your manual ground-truth labels.")

    ev1, ev2 = st.columns([2, 1])
    with ev1:
        model_choice = st.selectbox("Model to evaluate", ["vader", "textblob", "claude"], key="eval_model")
    with ev2:
        run_eval = st.button("Run Evaluation", use_container_width=True, type="primary")

    if run_eval:
        try:
            result = core.evaluate_sentiment(selected, model=model_choice)
            st.session_state["eval_result"] = result
        except core.TopicNotFoundError as e:
            st.error(str(e))
        except core.NoCommentsError as e:
            st.warning(str(e))
        except ImportError as e:
            st.error(str(e))

    eval_result = st.session_state.get("eval_result")
    if eval_result:
        st.markdown("---")
        st.markdown(f"**Model:** `{eval_result['model']}` · **Labeled comments:** {eval_result['total_labeled']}")

        acc_col, _ = st.columns([1, 3])
        acc_col.metric("Accuracy", f"{eval_result['accuracy']:.1%}")

        # Per-class table
        st.subheader("Per-class Metrics")
        pc = eval_result["per_class"]
        pc_df = pd.DataFrame([
            {"Class": lbl, "Precision": v["precision"], "Recall": v["recall"],
             "F1": v["f1"], "Support": v["support"]}
            for lbl, v in pc.items()
        ])
        st.dataframe(pc_df, use_container_width=True, hide_index=True)

        # Confusion matrix
        st.subheader("Confusion Matrix (rows = Ground Truth, cols = Predicted)")
        order = eval_result["labels_order"]
        cm = eval_result["confusion_matrix"]
        cm_df = pd.DataFrame(
            [[cm[g][p] for p in order] for g in order],
            index=[f"GT: {g}" for g in order],
            columns=[f"Pred: {p}" for p in order],
        )
        st.dataframe(cm_df, use_container_width=True)


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
