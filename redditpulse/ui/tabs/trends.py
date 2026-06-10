"""Trends tab: sentiment over time with adaptive bucketing."""

import altair as alt
import pandas as pd
import streamlit as st

from redditpulse import services


def render(topic: str) -> None:
    st.subheader(f"Sentiment Over Time: {topic}")
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
        trends = services.get_sentiment_trends(
            topic, min_comments=int(min_per_bucket), bucket=bucket_choice
        )
    except (services.TopicNotFoundError, services.NoCommentsError) as e:
        st.info(str(e))
        return

    if not trends["points"]:
        st.info("No timestamped comments to chart yet.")
        return

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
