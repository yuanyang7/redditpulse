"""Search service: fetch comments for a topic and record the session.

Every fetch is recorded as a *fetch run* with its full parameters (keywords,
subreddits, time window, source) and outcome, so data collected across
different sessions/time windows stays auditable and can be merged, trimmed
or removed later. Deduplication happens on insert (per topic, by reddit_id).
"""

from typing import Callable

from ..fetchers import TimeRange, get_fetcher
from ..storage import repo
from ..storage.db import session


def search_topic(
    topic: str,
    subreddits: list[str] | None = None,
    limit: int = 50,
    time_filter: str | None = "month",
    after: str | None = None,
    before: str | None = None,
    source: str = "arctic",
    refresh: bool = False,
    reset_comments: bool = False,
    keep_analyses: bool = False,
    min_relevance: float | None = None,
    keywords: list[str] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> dict:
    """Fetch Reddit comments for a topic and store them. Returns a status dict.

    The time window is either a relative `time_filter` ("month", "6months",
    ...) or an explicit `after`/`before` ISO date range; explicit dates win
    when both are given.
    """
    if after or before:
        time_range = TimeRange.from_dates(after, before)
        time_filter = None
    else:
        time_range = TimeRange.from_filter(time_filter or "month")

    with session() as conn:
        topic_row = repo.get_topic(conn, topic)

        if topic_row and reset_comments:
            repo.delete_comments(conn, topic_row["id"])
            if not keep_analyses:
                repo.delete_analyses(conn, topic_row["id"])
            status = "reset"
        elif topic_row and not refresh:
            return {
                "status": "exists",
                "keywords": topic_row["keywords"].split(","),
                "new_comments": 0,
                "total_comments": repo.count_comments(conn, topic_row["id"]),
            }
        else:
            status = "refresh" if topic_row else "new"

        # Generate or reuse keywords (an explicit `keywords` list always wins)
        if not topic_row:
            if not keywords:
                from ..analysis import llm
                keywords = llm.generate_keywords(topic)
            topic_id = repo.create_topic(conn, topic, keywords)
        else:
            topic_id = topic_row["id"]
            if keywords:
                repo.set_topic_keywords(conn, topic_id, keywords)
            else:
                keywords = topic_row["keywords"].split(",")

        run_id = repo.create_fetch_run(
            conn, topic_id,
            source=source,
            keywords=keywords,
            subreddits=subreddits,
            time_filter=time_filter,
            after_utc=time_range.after_utc,
            before_utc=time_range.before_utc,
            limit_per_keyword=limit,
            min_relevance=min_relevance,
        )

        try:
            fetcher = get_fetcher(source)
            comments = fetcher.search_comments(
                keywords,
                subreddits=subreddits,
                limit_per_keyword=min(limit, 100) if source == "arctic" else limit,
                time_range=time_range,
                progress_callback=progress_callback,
                stop_check=stop_check,
            )

            # Optional semantic relevance filtering
            pre_filter_count = len(comments)
            if min_relevance is not None and comments:
                from ..analysis import relevance
                comments = relevance.filter_by_relevance(
                    topic, comments, threshold=min_relevance)

            inserted = repo.insert_comments(conn, topic_id, comments, run_id=run_id)
        except Exception as e:
            repo.finish_fetch_run(conn, run_id, status="error", error=str(e))
            raise

        stopped = bool(stop_check and stop_check())
        repo.finish_fetch_run(
            conn, run_id,
            status="stopped" if stopped else "done",
            fetched=pre_filter_count,
            inserted=inserted,
        )

        result = {
            "status": status,
            "run_id": run_id,
            "keywords": keywords,
            "fetched": pre_filter_count,
            "new_comments": inserted,
            "total_comments": repo.count_comments(conn, topic_id),
        }
        if min_relevance is not None:
            result["filtered_out"] = pre_filter_count - len(comments)
        if stopped:
            result["stopped"] = True
        return result
