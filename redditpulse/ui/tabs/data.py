"""Data tab: fetch-run history, data-quality validation, and trimming.

This is the home of multi-session data management: every fetch session is
listed with its exact parameters (keywords, subreddits, time window, source)
and outcome, duplicate handling is automatic, and the accumulated dataset can
be validated and trimmed by date or score.
"""

import pandas as pd
import streamlit as st

from redditpulse import services
from .. import state


def _runs_section(topic: str) -> None:
    st.subheader("Fetch History")
    st.caption(
        "Every fetch session with its parameters and outcome. Comments from "
        "overlapping sessions are merged automatically (deduplicated by "
        "Reddit id). Deleting a run removes only comments no other run found."
    )
    runs = services.list_fetch_runs(topic)
    if not runs:
        st.info("No fetch runs recorded yet — runs are tracked for fetches "
                "made after the data-management upgrade.")
        return

    df = pd.DataFrame([{
        "ID": r["id"],
        "Started": r["started_at"][:16].replace("T", " "),
        "Source": r["source"],
        "Window": r["window"],
        "Subreddits": ", ".join(r["subreddits"] or []) or "(default)",
        "Keywords": ", ".join(r["keywords"])[:60],
        "Fetched": r["fetched"],
        "New": r["inserted"],
        "Status": r["status"],
        "Truncated": ", ".join(r["truncated_subreddits"] or []),
        "Skipped": ", ".join(r["skipped_keywords"] or []),
    } for r in runs])
    st.dataframe(df, use_container_width=True, hide_index=True)

    errored = [r for r in runs if r["status"] == "error" and r.get("error")]
    if errored:
        with st.expander(f"Error details ({len(errored)})"):
            for r in errored:
                st.markdown(f"**Run {r['id']}** ({r['started_at'][:16].replace('T', ' ')})")
                st.code(r["error"], language=None)

    truncated = [r for r in runs if r.get("truncated_subreddits")]
    if truncated:
        with st.expander(f"Truncated queries ({len(truncated)} run(s))"):
            st.caption(
                "These runs hit their per-query result cap for at least one "
                "subreddit/keyword combination, sorted newest-first — so "
                "older matching comments exist but weren't fetched. Re-run "
                "with a narrower time window or a higher limit to fill the gap."
            )
            for r in truncated:
                started = r["started_at"][:16].replace("T", " ")
                st.markdown(
                    f"**Run {r['id']}** ({started}): "
                    + ", ".join(f"r/{s}" for s in r["truncated_subreddits"])
                )

    skipped = [r for r in runs if r.get("skipped_keywords")]
    if skipped:
        with st.expander(f"Skipped keywords from early stops ({len(skipped)} run(s))"):
            st.caption(
                "These runs were stopped before finishing — the keywords "
                "below got no results, or only partial results across "
                "subreddits, because the run ended before reaching them."
            )
            for r in skipped:
                started = r["started_at"][:16].replace("T", " ")
                st.markdown(
                    f"**Run {r['id']}** ({started}): "
                    + ", ".join(f"\"{k}\"" for k in r["skipped_keywords"])
                )

    rc1, rc2 = st.columns([2, 1])
    with rc1:
        run_id = st.selectbox("Run to delete", [r["id"] for r in runs],
                              format_func=lambda i: f"Run {i}", key="run_delete_select")
    with rc2:
        st.markdown("<div style='height: 1.8em'></div>", unsafe_allow_html=True)
        if st.button("Delete run", key="delete_run_btn",
                     help="Removes the run and any comments only it contributed."):
            result = services.delete_fetch_run(topic, run_id)
            state.refresh_topics()
            st.success(f"Deleted run {run_id} "
                       f"({result['comments_deleted']} exclusive comments removed).")
            st.rerun()


def _validation_section(topic: str) -> None:
    st.subheader("Data Quality")
    report = services.validate_topic_data(topic)

    vc1, vc2, vc3, vc4 = st.columns(4)
    vc1.metric("Comments", report["total"])
    vc2.metric("Avg score", report["avg_score"] if report["avg_score"] is not None else "—")
    vc3.metric("No timestamp", report["missing_timestamp"])
    vc4.metric("Empty body", report["empty_body"])
    rng = report["date_range"]
    if rng[0]:
        st.caption(f"Date range: **{rng[0]} → {rng[1]}** · "
                   f"{report['negative_score']} downvoted comment(s)")

    if report["ok"]:
        st.success("No data-quality issues found.")
    else:
        for issue in report["issues"]:
            st.warning(issue)


def _trim_section(topic: str) -> None:
    st.subheader("Trim Dataset")
    st.caption("Permanently delete comments outside a date range or below a score.")

    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        delete_before = st.date_input("Delete created before", value=None,
                                      key="trim_before")
    with tc2:
        delete_after = st.date_input("Delete created after", value=None,
                                     key="trim_after")
    with tc3:
        trim_min_score = st.number_input("Delete score below (0 = off)",
                                         min_value=0, max_value=1000, value=0,
                                         key="trim_min_score")

    if st.button("Trim comments", key="trim_btn"):
        if not delete_before and not delete_after and trim_min_score == 0:
            st.warning("Set at least one trim condition first.")
        else:
            result = services.trim_comments(
                topic,
                delete_before=delete_before.isoformat() if delete_before else None,
                delete_after=delete_after.isoformat() if delete_after else None,
                min_score=trim_min_score if trim_min_score > 0 else None,
            )
            state.refresh_topics()
            st.success(f"Deleted {result['deleted']} comments "
                       f"({result['remaining']} remaining).")


def render(topic: str) -> None:
    st.subheader(f"Data Management: {topic}")
    try:
        _validation_section(topic)
        st.markdown("---")
        _runs_section(topic)
        st.markdown("---")
        _trim_section(topic)
    except services.TopicNotFoundError as e:
        st.error(str(e))
