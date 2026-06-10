"""Data management: fetch-run history, trimming, validation.

Supports the multi-session workflow: query the same topic over different
time windows, then inspect, merge (automatic via dedupe), trim and validate
the accumulated data.
"""

from ..exceptions import TopicNotFoundError
from ..fetchers import TimeRange
from ..storage import repo
from ..storage.db import session


def _require_topic(conn, topic: str) -> dict:
    row = repo.get_topic(conn, topic)
    if not row:
        raise TopicNotFoundError(f"Topic '{topic}' not found.")
    return row


def list_fetch_runs(topic: str) -> list[dict]:
    """All fetch runs for a topic, newest first, with readable time windows."""
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        runs = repo.get_fetch_runs(conn, topic_row["id"])
    for run in runs:
        rng = TimeRange(run["after_utc"], run["before_utc"])
        run["window"] = run["time_filter"] or (
            f"{rng.after_date() or '...'} → {rng.before_date() or '...'}"
        )
    return runs


def delete_fetch_run(topic: str, run_id: int,
                     delete_exclusive_comments: bool = True) -> dict:
    """Remove a fetch run, dropping comments only that run contributed."""
    with session() as conn:
        _require_topic(conn, topic)
        deleted = repo.delete_fetch_run(
            conn, run_id, delete_exclusive_comments=delete_exclusive_comments)
        return {"run_id": run_id, "comments_deleted": deleted}


def trim_comments(topic: str, delete_before: str | None = None,
                  delete_after: str | None = None,
                  min_score: int | None = None) -> dict:
    """Trim a topic's comments by date and/or score.

    - `delete_before`: ISO date; comments created before it are deleted.
    - `delete_after`: ISO date; comments created after it (end of day) are deleted.
    - `min_score`: comments scoring below it are deleted.
    """
    rng = TimeRange.from_dates(delete_before, delete_after)
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        deleted = repo.delete_comments(
            conn, topic_row["id"],
            before_utc=rng.after_utc,   # parsed from delete_before
            after_utc=rng.before_utc,   # parsed from delete_after (end of day)
            max_score=min_score,
        ) if (delete_before or delete_after or min_score is not None) else 0
        return {
            "deleted": deleted,
            "remaining": repo.count_comments(conn, topic_row["id"]),
        }


def validate_topic_data(topic: str) -> dict:
    """Data-quality report: totals, missing fields, suspect rows, date range."""
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        stats = repo.comment_stats(conn, topic_row["id"])

    issues = []
    if stats["total"]:
        if stats["missing_ts"]:
            issues.append(f"{stats['missing_ts']} comment(s) have no timestamp "
                          "(they're excluded from trends).")
        if stats["empty_body"]:
            issues.append(f"{stats['empty_body']} comment(s) have empty/removed bodies.")
    rng = TimeRange(stats["oldest_utc"] or None, stats["newest_utc"] or None)
    return {
        "total": stats["total"],
        "missing_timestamp": stats["missing_ts"] or 0,
        "empty_body": stats["empty_body"] or 0,
        "negative_score": stats["negative_score"] or 0,
        "avg_score": round(stats["avg_score"], 2) if stats["avg_score"] is not None else None,
        "date_range": [rng.after_date(), rng.before_date()],
        "issues": issues,
        "ok": not issues,
    }


def get_data_overview(topic: str) -> dict:
    """Everything the Data tab needs in one call: runs + validation."""
    return {
        "runs": list_fetch_runs(topic),
        "validation": validate_topic_data(topic),
    }
