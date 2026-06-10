"""Session-state helpers shared by sidebar and tabs."""

import threading

import streamlit as st

from redditpulse import services


def refresh_topics() -> None:
    """Fetch all topics from DB and cache in session state."""
    st.session_state["topics"] = services.list_topics()


def get_topics() -> list[dict]:
    if "topics" not in st.session_state:
        refresh_topics()
    return st.session_state["topics"]


def start_search_job(label: str, kind: str, extra: dict | None = None, **kwargs):
    """Kick off services.search_topic in a background thread.

    Progress and the eventual result are tracked in
    st.session_state["search_job"] and rendered live by the sidebar's
    progress fragment. `kind`/`extra` carry enough context to build the
    right summary message once the job finishes.
    """
    stop_event = threading.Event()
    job = {
        "label": label,
        "kind": kind,
        "extra": extra or {},
        "stop_event": stop_event,
        "done": 0,
        "total": 0,
        "desc": "Starting...",
        "result": None,
        "error": None,
        "finished": False,
    }

    def _on_progress(done, total, desc):
        job["done"] = done
        job["total"] = total
        job["desc"] = desc

    def _worker():
        try:
            job["result"] = services.search_topic(
                progress_callback=_on_progress,
                stop_check=stop_event.is_set,
                **kwargs,
            )
        except Exception as e:
            job["error"] = e
        finally:
            job["finished"] = True

    job["thread"] = threading.Thread(target=_worker, daemon=True)
    st.session_state["search_job"] = job
    job["thread"].start()


def job_message(job: dict) -> tuple[str, str]:
    """Build a (level, message) pair summarizing a finished search job."""
    if job["error"]:
        return "error", str(job["error"])

    result = job["result"]
    extra = job["extra"]
    stopped = result.get("stopped", False)

    if job["kind"] == "search":
        msg = (
            f"Found {result['fetched']} comments, "
            f"inserted {result['new_comments']} new "
            f"(total: {result['total_comments']})"
        )
        if "filtered_out" in result:
            msg += f" — filtered out {result['filtered_out']} irrelevant"
        if extra["topic_to_use"] != extra["new_topic_text"]:
            msg = f"Created '{extra['topic_to_use']}' — " + msg
    elif job["kind"] == "refresh":
        msg = f"+{result['new_comments']} new comments"
    elif job["kind"] == "refetch":
        msg = f"Re-fetched: {result['new_comments']} comments (analyses kept)"
    else:  # reset
        msg = "Comments & analyses cleared, re-fetched"

    if stopped:
        return "warning", "Stopped early — " + msg
    return "success", msg
