"""Browse tab: read comments filtered by sentiment and score."""

import streamlit as st

from redditpulse import services


def render(topic: str) -> None:
    st.subheader(f"Browse Comments: {topic}")

    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        browse_sentiment = st.radio(
            "Sentiment filter",
            ["negative", "positive", "neutral"],
            horizontal=True,
            key="browse_sentiment",
        )
    with bc2:
        browse_limit = st.number_input("Max comments", min_value=5, max_value=200,
                                       value=20, key="browse_limit")
    with bc3:
        browse_min_score = st.number_input(
            "Min upvotes (0 = off)", min_value=0, max_value=1000, value=0,
            key="browse_min_score",
        )

    if st.button("Load Comments", use_container_width=True):
        with st.spinner("Loading comments..."):
            try:
                data = services.browse_comments(
                    topic=topic,
                    sentiment_filter=browse_sentiment,
                    limit=browse_limit,
                    min_score=browse_min_score if browse_min_score > 0 else None,
                )
                st.session_state["browse_data"] = data
            except services.TopicNotFoundError as e:
                st.error(str(e))

    data = st.session_state.get("browse_data")
    if data:
        st.caption(f"Showing {data['total']} {data['sentiment']} comments")
        color_map = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}
        icon = color_map.get(data["sentiment"], "")

        for c in data["comments"]:
            with st.container(border=True):
                meta = (
                    f"{icon} **r/{c['subreddit']}** · "
                    f"score: {c['score']} · "
                    f"sentiment: {c['compound']:+.2f}"
                )
                if c.get("permalink"):
                    meta += f" · [source]({c['permalink']})"
                st.markdown(meta)
                st.markdown(c["body"])
