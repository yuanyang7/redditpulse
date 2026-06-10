"""Label tab: assign ground-truth sentiment labels for model evaluation."""

import streamlit as st

from redditpulse import services

LABEL_COLORS = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}


def render(topic: str) -> None:
    st.subheader(f"Label Comments: {topic}")
    st.caption("Assign ground-truth sentiment labels. These are used in the Evaluate tab to benchmark models.")

    lc1, lc2, lc3 = st.columns(3)
    with lc1:
        unlabeled_only = st.checkbox("Show unlabeled only", value=True, key="lbl_unlabeled")
    with lc2:
        label_page_size = st.number_input("Per page", min_value=5, max_value=50, value=10, key="lbl_page_size")
    with lc3:
        label_page = st.number_input("Page", min_value=1, value=1, key="lbl_page")

    try:
        data = services.get_comments_for_labeling(
            topic,
            unlabeled_only=unlabeled_only,
            limit=label_page_size,
            offset=(label_page - 1) * label_page_size,
        )
    except services.TopicNotFoundError as e:
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
        return

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
                    services.label_comment(topic, c["id"], "positive")
                    st.rerun()
            with b2:
                if st.button("Neutral", key=f"neu_{c['id']}"):
                    services.label_comment(topic, c["id"], "neutral")
                    st.rerun()
            with b3:
                if st.button("Negative", key=f"neg_{c['id']}"):
                    services.label_comment(topic, c["id"], "negative")
                    st.rerun()
            with b4:
                if current and st.button("Clear", key=f"clr_{c['id']}"):
                    services.label_comment(topic, c["id"], None)
                    st.rerun()
