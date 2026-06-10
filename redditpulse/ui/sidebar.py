"""Sidebar: live job progress, topic selection, and search controls."""

import streamlit as st

from redditpulse import services
from . import state


@st.fragment(run_every=0.5)
def _search_progress():
    """Render the live progress/Stop UI for a background search job, if any."""
    job = st.session_state.get("search_job")
    if not job:
        return

    with st.status(job["label"], expanded=True) as status_box:
        total = job["total"]
        st.progress(job["done"] / total if total else 0.0, text=job["desc"])

        if not job["finished"]:
            if st.button("Stop", use_container_width=True, key="stop_search_job"):
                job["stop_event"].set()
            # st.status auto-completes (spinner -> check) when the `with` block
            # exits unless told otherwise — re-assert "running" each fragment
            # tick so the icon doesn't flicker between loading and done.
            status_box.update(state="running")
        else:
            level, msg = state.job_message(job)
            if level == "error":
                status_box.update(label="Failed", state="error", expanded=False)
            elif level == "warning":
                status_box.update(label="Stopped", state="error", expanded=False)
            else:
                status_box.update(label="Done", state="complete", expanded=False)

            st.session_state["search_flash"] = (level, msg)
            if job["kind"] == "search" and level != "error":
                st.session_state.pop("keyword_review", None)
                st.session_state["pending_topic_select"] = job["extra"]["topic_to_use"]
            del st.session_state["search_job"]
            state.refresh_topics()
            st.rerun()


def _keyword_review_ui(new_topic: str) -> list[str] | None:
    """Generate/review/edit keywords before fetching. Returns the edited list."""
    review = st.session_state.get("keyword_review")
    if st.button("Generate Keywords", use_container_width=True):
        if not new_topic.strip():
            st.warning("Enter a topic first.")
        else:
            with st.spinner("Generating keywords and subreddits..."):
                try:
                    keywords = services.generate_keywords(new_topic.strip())
                    subreddits_sugg = services.generate_subreddits(new_topic.strip())
                    st.session_state["keyword_review"] = {
                        "topic": new_topic.strip(),
                        "text": ", ".join(keywords),
                        "subreddits_text": ", ".join(subreddits_sugg),
                        "kw_version": 0,
                        "sr_version": 0,
                    }
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    keyword_override = None
    if review and review["topic"] == new_topic.strip():
        kw_version = review.get("kw_version", 0)
        kw_col, kw_btn_col = st.columns([5, 1])
        with kw_col:
            edited = st.text_area(
                "Keywords (review and edit before fetching)",
                value=review["text"],
                key=f"search_keywords_text_{kw_version}",
                help="Comma-separated. Edit out anything outdated or irrelevant "
                     "(e.g. drop a stale year) before fetching.",
            )
        with kw_btn_col:
            st.markdown("<div style='height: 1.8em'></div>", unsafe_allow_html=True)
            if st.button("🔄", key="regen_keywords", help="Regenerate keywords"):
                with st.spinner("Regenerating keywords..."):
                    try:
                        keywords = services.generate_keywords(new_topic.strip())
                        review["text"] = ", ".join(keywords)
                        review["kw_version"] = kw_version + 1
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
        keyword_override = [k.strip() for k in edited.split(",") if k.strip()]
    return keyword_override


def _subreddits_ui(new_topic: str) -> str:
    """Subreddits input, auto-filled from the keyword review when available."""
    review = st.session_state.get("keyword_review")
    help_text = ("Comma-separated. Auto-filled from \"Generate Keywords\" with "
                 "subreddits suggested for this topic — edit as needed.")
    if review and review["topic"] == new_topic.strip():
        sr_version = review.get("sr_version", 0)
        sr_col, sr_btn_col = st.columns([5, 1])
        with sr_col:
            subreddits = st.text_input(
                "Subreddits", value=review.get("subreddits_text", ""),
                key=f"search_subreddits_text_{sr_version}",
                placeholder="all (comma-separated)", help=help_text,
            )
        with sr_btn_col:
            st.markdown("<div style='height: 1.8em'></div>", unsafe_allow_html=True)
            if st.button("🔄", key="regen_subreddits", help="Regenerate subreddits"):
                with st.spinner("Regenerating subreddits..."):
                    try:
                        subreddits_sugg = services.generate_subreddits(new_topic.strip())
                        review["subreddits_text"] = ", ".join(subreddits_sugg)
                        review["sr_version"] = sr_version + 1
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
    else:
        subreddits = st.text_input("Subreddits", placeholder="all (comma-separated)",
                                   help=help_text)
    return subreddits


def _time_window_ui() -> dict:
    """Relative lookback or explicit date range. Returns search_topic kwargs."""
    mode = st.radio("Time window", ["Relative", "Custom range"], horizontal=True,
                    key="time_mode",
                    help="Custom range queries a specific timeline (e.g. last "
                         "January) instead of the past N days.")
    if mode == "Relative":
        time_filter = st.selectbox(
            "Lookback", ["month", "week", "day", "hour", "6months", "year", "all"],
            index=4,
            format_func=lambda v: "6 months" if v == "6months" else v,
        )
        return {"time_filter": time_filter}
    dc1, dc2 = st.columns(2)
    with dc1:
        after = st.date_input("From", value=None, key="range_after")
    with dc2:
        before = st.date_input("To (inclusive)", value=None, key="range_before")
    return {
        "after": after.isoformat() if after else None,
        "before": before.isoformat() if before else None,
    }


def render() -> str | None:
    """Render the whole sidebar; returns the selected topic name (or None)."""
    st.title("📊 RedditPulse")
    st.markdown("---")

    _search_progress()
    job_running = "search_job" in st.session_state

    flash = st.session_state.pop("search_flash", None)
    if flash:
        level, msg = flash
        getattr(st, level)(msg)

    # ------ Existing topics ------
    topics = state.get_topics()
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

    keyword_override = _keyword_review_ui(new_topic)

    limit = st.number_input("Limit per keyword", min_value=1, max_value=100, value=50)
    window_kwargs = _time_window_ui()
    subreddits = _subreddits_ui(new_topic)

    source = st.selectbox(
        "Source", ["arctic", "praw", "rss"], index=0,
        format_func=lambda v: {
            "arctic": "Arctic Shift archive (no credentials)",
            "praw": "Reddit API (needs credentials)",
            "rss": "Public RSS (limited fallback)",
        }[v],
        help="Arctic Shift needs no credentials and supports precise date "
             "ranges. Keyword search is scoped to subreddits, so set the "
             "Subreddits field for best results.",
    )
    min_relevance = st.slider("Min relevance (0 = off)", 0.0, 1.0, 0.3, 0.05,
                              help="Semantic similarity threshold. Try 0.3 to filter off-topic comments.")

    common_kwargs = {
        "source": source,
        "min_relevance": min_relevance if min_relevance > 0 else None,
        **window_kwargs,
    }

    if st.button("Search", use_container_width=True, type="primary", disabled=job_running):
        if not new_topic.strip():
            st.warning("Enter a topic first.")
        else:
            topic_to_use = services.next_available_topic_name(new_topic.strip(), topic_names)
            state.start_search_job(
                f"Searching Reddit for \"{topic_to_use}\"...",
                kind="search",
                extra={"topic_to_use": topic_to_use, "new_topic_text": new_topic.strip()},
                topic=topic_to_use,
                subreddits=subreddits.split(",") if subreddits.strip() else None,
                limit=limit,
                refresh=True,
                keywords=keyword_override,
                **common_kwargs,
            )
            st.rerun()

    # ------ Refresh / Reset for selected topic ------
    if selected:
        st.markdown("---")
        st.markdown(f"**Active:** {selected}")
        if st.button("Refresh", use_container_width=True, disabled=job_running,
                     help="Fetch more comments with the current time window; "
                          "duplicates are merged away automatically"):
            state.start_search_job(
                "Fetching more comments...",
                kind="refresh",
                topic=selected, refresh=True,
                **common_kwargs,
            )
            st.rerun()
        if st.button("Re-fetch", use_container_width=True, disabled=job_running,
                     help="Clear comments and re-fetch, keeping keywords and past analyses"):
            state.start_search_job(
                "Re-fetching comments...",
                kind="refetch",
                topic=selected, reset_comments=True, keep_analyses=True,
                **common_kwargs,
            )
            st.rerun()
        if st.button("Reset All", use_container_width=True, disabled=job_running,
                     help="Clear comments AND analyses, then re-fetch"):
            state.start_search_job(
                "Resetting...",
                kind="reset",
                topic=selected, reset_comments=True,
                **common_kwargs,
            )
            st.rerun()

        st.markdown("---")
        with st.expander("⚠️ Danger zone"):
            st.markdown(f"Permanently delete **{selected}**, including all its comments and analyses.")
            confirm_delete = st.checkbox(f"I'm sure I want to delete '{selected}'", key="confirm_delete")
            if st.button("Delete topic", use_container_width=True, disabled=not confirm_delete):
                try:
                    services.delete_topic(selected)
                    state.refresh_topics()
                    st.session_state.pop("topic_select", None)
                    st.session_state.pop("confirm_delete", None)
                    st.success(f"Deleted '{selected}'")
                    st.rerun()
                except services.TopicNotFoundError as e:
                    st.error(str(e))

    return selected
