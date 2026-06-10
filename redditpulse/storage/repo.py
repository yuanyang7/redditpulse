"""Repository functions: all SQL lives here.

Every function takes an open connection as its first argument; transaction
boundaries (commit) are handled here so callers never touch SQL or cursors.
"""

import json
import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

def create_topic(conn: sqlite3.Connection, name: str, keywords: list[str]) -> int:
    cur = conn.execute(
        "INSERT INTO topics (name, keywords, created_at) VALUES (?, ?, ?)",
        (name, ",".join(keywords), _now()),
    )
    conn.commit()
    return cur.lastrowid


def get_topic(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM topics WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def get_all_topics(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM topics ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def set_topic_keywords(conn: sqlite3.Connection, topic_id: int, keywords: list[str]) -> None:
    conn.execute("UPDATE topics SET keywords = ? WHERE id = ?",
                 (",".join(keywords), topic_id))
    conn.commit()


def set_topic_note(conn: sqlite3.Connection, topic_id: int, note: str | None) -> None:
    conn.execute("UPDATE topics SET note = ? WHERE id = ?", (note, topic_id))
    conn.commit()


def get_showcase_config(conn: sqlite3.Connection, topic_id: int) -> dict | None:
    row = conn.execute(
        "SELECT showcase_config FROM topics WHERE id = ?", (topic_id,)
    ).fetchone()
    if row and row["showcase_config"]:
        try:
            return json.loads(row["showcase_config"])
        except ValueError:
            return None
    return None


def set_showcase_config(conn: sqlite3.Connection, topic_id: int,
                        config: dict | None) -> None:
    conn.execute(
        "UPDATE topics SET showcase_config = ? WHERE id = ?",
        (json.dumps(config) if config is not None else None, topic_id),
    )
    conn.commit()


def delete_topic(conn: sqlite3.Connection, topic_id: int) -> None:
    """Delete a topic and everything attached to it."""
    conn.execute(
        "DELETE FROM fetch_run_comments WHERE run_id IN "
        "(SELECT id FROM fetch_runs WHERE topic_id = ?)", (topic_id,))
    conn.execute("DELETE FROM fetch_runs WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM comments WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM analyses WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

def insert_comments(conn: sqlite3.Connection, topic_id: int, comments: list[dict],
                    run_id: int | None = None) -> int:
    """Insert comments, deduplicating per topic by reddit_id.

    If `run_id` is given, every comment in `comments` (new or pre-existing) is
    linked to that fetch run, so overlapping query sessions stay auditable.
    Returns the number of newly inserted comments.
    """
    inserted = 0
    fetched_at = _now()
    for c in comments:
        cur = conn.execute(
            """INSERT INTO comments
               (topic_id, reddit_id, subreddit, author, body, score,
                controversiality, permalink, created_utc, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (topic_id, reddit_id) DO NOTHING""",
            (
                topic_id,
                c["reddit_id"],
                c["subreddit"],
                c.get("author"),
                c["body"],
                c.get("score", 0),
                c.get("controversiality"),
                c.get("permalink"),
                c.get("created_utc", 0),
                fetched_at,
            ),
        )
        if cur.rowcount:
            inserted += 1
        if run_id is not None:
            row = conn.execute(
                "SELECT id FROM comments WHERE topic_id = ? AND reddit_id = ?",
                (topic_id, c["reddit_id"]),
            ).fetchone()
            if row:
                conn.execute(
                    """INSERT OR IGNORE INTO fetch_run_comments (run_id, comment_id)
                       VALUES (?, ?)""",
                    (run_id, row["id"]),
                )
    conn.commit()
    return inserted


def get_comments(
    conn: sqlite3.Connection,
    topic_id: int,
    limit: int = 500,
    min_score: int | None = None,
    after_utc: float | None = None,
    before_utc: float | None = None,
    order_by: str = "score",
) -> list[dict]:
    """Fetch a topic's comments with optional score/time filters."""
    clauses = ["topic_id = ?"]
    params: list = [topic_id]
    if min_score is not None:
        clauses.append("score >= ?")
        params.append(min_score)
    if after_utc is not None:
        clauses.append("created_utc >= ?")
        params.append(after_utc)
    if before_utc is not None:
        clauses.append("created_utc <= ?")
        params.append(before_utc)
    order = {"score": "score DESC", "newest": "created_utc DESC",
             "oldest": "created_utc ASC"}.get(order_by, "score DESC")
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM comments WHERE {' AND '.join(clauses)} "
        f"ORDER BY {order} LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def count_comments(conn: sqlite3.Connection, topic_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM comments WHERE topic_id = ?", (topic_id,)
    ).fetchone()
    return row["cnt"]


def delete_comments(conn: sqlite3.Connection, topic_id: int,
                    before_utc: float | None = None,
                    after_utc: float | None = None,
                    max_score: int | None = None) -> int:
    """Trim comments by time range and/or score. Returns rows deleted.

    With no filters, deletes all of the topic's comments.
    """
    clauses = ["topic_id = ?"]
    params: list = [topic_id]
    if before_utc is not None:
        clauses.append("created_utc < ?")
        params.append(before_utc)
    if after_utc is not None:
        clauses.append("created_utc > ?")
        params.append(after_utc)
    if max_score is not None:
        clauses.append("score < ?")
        params.append(max_score)
    cur = conn.execute(
        f"DELETE FROM comments WHERE {' AND '.join(clauses)}", params
    )
    conn.commit()
    return cur.rowcount


def comment_stats(conn: sqlite3.Connection, topic_id: int) -> dict:
    """Aggregate stats used for data-quality validation."""
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN created_utc <= 0 THEN 1 ELSE 0 END) AS missing_ts,
                  SUM(CASE WHEN body = '' OR body IN ('[deleted]', '[removed]')
                      THEN 1 ELSE 0 END) AS empty_body,
                  SUM(CASE WHEN score < 0 THEN 1 ELSE 0 END) AS negative_score,
                  MIN(created_utc) AS oldest_utc,
                  MAX(created_utc) AS newest_utc,
                  AVG(score) AS avg_score
           FROM comments WHERE topic_id = ?""",
        (topic_id,),
    ).fetchone()
    return dict(row)


def set_comment_label(conn: sqlite3.Connection, comment_id: int,
                      label: str | None) -> None:
    conn.execute("UPDATE comments SET manual_label = ? WHERE id = ?",
                 (label, comment_id))
    conn.commit()


def get_comments_for_labeling(
    conn: sqlite3.Connection,
    topic_id: int,
    unlabeled_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    where = "topic_id = ?" + (" AND manual_label IS NULL" if unlabeled_only else "")
    rows = conn.execute(
        f"""SELECT id, reddit_id, subreddit, author, body, score, permalink, manual_label
            FROM comments WHERE {where}
            ORDER BY score DESC LIMIT ? OFFSET ?""",
        (topic_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def get_labeled_comments(conn: sqlite3.Connection, topic_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT id, body, score, manual_label
           FROM comments WHERE topic_id = ? AND manual_label IS NOT NULL""",
        (topic_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def count_comments_by_label(conn: sqlite3.Connection, topic_id: int) -> dict:
    total = count_comments(conn, topic_id)
    rows = conn.execute(
        """SELECT manual_label, COUNT(*) AS cnt FROM comments
           WHERE topic_id = ? GROUP BY manual_label""",
        (topic_id,),
    ).fetchall()
    breakdown = {r["manual_label"] or "unlabeled": r["cnt"] for r in rows}
    labeled = total - breakdown.get("unlabeled", 0)
    return {"total": total, "labeled": labeled, "breakdown": breakdown}


# ---------------------------------------------------------------------------
# Fetch runs
# ---------------------------------------------------------------------------

def create_fetch_run(
    conn: sqlite3.Connection,
    topic_id: int,
    source: str,
    keywords: list[str],
    subreddits: list[str] | None = None,
    time_filter: str | None = None,
    after_utc: float | None = None,
    before_utc: float | None = None,
    limit_per_keyword: int | None = None,
    min_relevance: float | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO fetch_runs
           (topic_id, source, keywords, subreddits, time_filter, after_utc,
            before_utc, limit_per_keyword, min_relevance, started_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')""",
        (
            topic_id, source, json.dumps(keywords),
            json.dumps(subreddits) if subreddits else None,
            time_filter, after_utc, before_utc, limit_per_keyword,
            min_relevance, _now(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def finish_fetch_run(conn: sqlite3.Connection, run_id: int, status: str,
                     fetched: int = 0, inserted: int = 0,
                     error: str | None = None) -> None:
    conn.execute(
        """UPDATE fetch_runs SET finished_at = ?, status = ?, fetched = ?,
           inserted = ?, error = ? WHERE id = ?""",
        (_now(), status, fetched, inserted, error, run_id),
    )
    conn.commit()


def get_fetch_runs(conn: sqlite3.Connection, topic_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM fetch_runs WHERE topic_id = ? ORDER BY started_at DESC",
        (topic_id,),
    ).fetchall()
    runs = []
    for r in rows:
        run = dict(r)
        run["keywords"] = json.loads(run["keywords"]) if run["keywords"] else []
        run["subreddits"] = json.loads(run["subreddits"]) if run["subreddits"] else None
        runs.append(run)
    return runs


def delete_fetch_run(conn: sqlite3.Connection, run_id: int,
                     delete_exclusive_comments: bool = False) -> int:
    """Delete a fetch run. Optionally remove comments only this run produced.

    Returns the number of comments deleted alongside the run.
    """
    deleted = 0
    if delete_exclusive_comments:
        cur = conn.execute(
            """DELETE FROM comments WHERE id IN (
                   SELECT comment_id FROM fetch_run_comments WHERE run_id = ?
               ) AND id NOT IN (
                   SELECT comment_id FROM fetch_run_comments WHERE run_id != ?
               )""",
            (run_id, run_id),
        )
        deleted = cur.rowcount
    conn.execute("DELETE FROM fetch_run_comments WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM fetch_runs WHERE id = ?", (run_id,))
    conn.commit()
    return deleted


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def save_analysis(conn: sqlite3.Connection, topic_id: int, num_comments: int,
                  sentiment_summary: str, themes: str, raw_result: str,
                  params: dict | None = None, signature: str | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO analyses (topic_id, run_at, num_comments, sentiment_summary,
                                 themes, raw_result, params, signature)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (topic_id, _now(), num_comments, sentiment_summary, themes, raw_result,
         json.dumps(params) if params else None, signature),
    )
    conn.commit()
    return cur.lastrowid


def get_latest_analysis(conn: sqlite3.Connection, topic_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM analyses WHERE topic_id = ? ORDER BY run_at DESC LIMIT 1",
        (topic_id,),
    ).fetchone()
    return dict(row) if row else None


def find_analysis_by_signature(conn: sqlite3.Connection, topic_id: int,
                               signature: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM analyses WHERE topic_id = ? AND signature = ?
           ORDER BY run_at DESC LIMIT 1""",
        (topic_id, signature),
    ).fetchone()
    return dict(row) if row else None


def delete_analyses(conn: sqlite3.Connection, topic_id: int) -> None:
    conn.execute("DELETE FROM analyses WHERE topic_id = ?", (topic_id,))
    conn.commit()
