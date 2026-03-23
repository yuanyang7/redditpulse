"""SQLite database layer for storing Reddit comments and analysis results."""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DEFAULT_DB_PATH = Path("redditpulse.db")


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            keywords    TEXT NOT NULL,  -- comma-separated
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS comments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id        INTEGER NOT NULL REFERENCES topics(id),
            reddit_id       TEXT NOT NULL UNIQUE,
            subreddit       TEXT NOT NULL,
            author          TEXT,
            body            TEXT NOT NULL,
            score           INTEGER NOT NULL DEFAULT 0,
            permalink       TEXT,
            created_utc     REAL NOT NULL,
            fetched_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id    INTEGER NOT NULL REFERENCES topics(id),
            run_at      TEXT NOT NULL,
            num_comments INTEGER NOT NULL,
            sentiment_summary TEXT,  -- JSON
            themes      TEXT,        -- JSON
            raw_result  TEXT         -- full JSON from Claude
        );

        CREATE INDEX IF NOT EXISTS idx_comments_topic ON comments(topic_id);
        CREATE INDEX IF NOT EXISTS idx_analyses_topic ON analyses(topic_id);
    """)
    # Migrate: add manual_label column if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE comments ADD COLUMN manual_label TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


def create_topic(conn: sqlite3.Connection, name: str, keywords: list[str]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO topics (name, keywords, created_at) VALUES (?, ?, ?)",
        (name, ",".join(keywords), now),
    )
    conn.commit()
    return cur.lastrowid


def get_topic(conn: sqlite3.Connection, name: str) -> dict | None:
    row = conn.execute("SELECT * FROM topics WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def get_all_topics(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM topics ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def insert_comments(conn: sqlite3.Connection, topic_id: int, comments: list[dict]) -> int:
    """Insert comments, skipping duplicates. Returns number of new comments inserted."""
    inserted = 0
    for c in comments:
        try:
            conn.execute(
                """INSERT INTO comments
                   (topic_id, reddit_id, subreddit, author, body, score, permalink, created_utc, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    topic_id,
                    c["reddit_id"],
                    c["subreddit"],
                    c["author"],
                    c["body"],
                    c["score"],
                    c["permalink"],
                    c["created_utc"],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass  # duplicate reddit_id
    conn.commit()
    return inserted


def get_comments_for_topic(conn: sqlite3.Connection, topic_id: int, limit: int = 500) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM comments WHERE topic_id = ? ORDER BY score DESC LIMIT ?",
        (topic_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def save_analysis(conn: sqlite3.Connection, topic_id: int, num_comments: int,
                  sentiment_summary: str, themes: str, raw_result: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO analyses (topic_id, run_at, num_comments, sentiment_summary, themes, raw_result)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (topic_id, now, num_comments, sentiment_summary, themes, raw_result),
    )
    conn.commit()
    return cur.lastrowid


def delete_analyses(conn: sqlite3.Connection, topic_id: int) -> None:
    conn.execute("DELETE FROM analyses WHERE topic_id = ?", (topic_id,))
    conn.commit()


def get_latest_analysis(conn: sqlite3.Connection, topic_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM analyses WHERE topic_id = ? ORDER BY run_at DESC LIMIT 1",
        (topic_id,),
    ).fetchone()
    return dict(row) if row else None


def set_comment_label(conn: sqlite3.Connection, comment_id: int, label: str | None) -> None:
    """Set or clear the manual label for a comment."""
    conn.execute("UPDATE comments SET manual_label = ? WHERE id = ?", (label, comment_id))
    conn.commit()


def get_comments_for_labeling(
    conn: sqlite3.Connection,
    topic_id: int,
    unlabeled_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return comments for labeling, optionally filtered to unlabeled ones."""
    if unlabeled_only:
        rows = conn.execute(
            """SELECT id, reddit_id, subreddit, author, body, score, permalink, manual_label
               FROM comments WHERE topic_id = ? AND manual_label IS NULL
               ORDER BY score DESC LIMIT ? OFFSET ?""",
            (topic_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, reddit_id, subreddit, author, body, score, permalink, manual_label
               FROM comments WHERE topic_id = ?
               ORDER BY score DESC LIMIT ? OFFSET ?""",
            (topic_id, limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def get_labeled_comments(conn: sqlite3.Connection, topic_id: int) -> list[dict]:
    """Return only comments that have a manual label."""
    rows = conn.execute(
        """SELECT id, body, score, manual_label
           FROM comments WHERE topic_id = ? AND manual_label IS NOT NULL""",
        (topic_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def count_comments_by_label(conn: sqlite3.Connection, topic_id: int) -> dict:
    """Return counts: total, labeled, and per-label breakdown."""
    total = conn.execute(
        "SELECT COUNT(*) FROM comments WHERE topic_id = ?", (topic_id,)
    ).fetchone()[0]
    rows = conn.execute(
        """SELECT manual_label, COUNT(*) as cnt FROM comments
           WHERE topic_id = ? GROUP BY manual_label""",
        (topic_id,),
    ).fetchall()
    breakdown = {r["manual_label"] or "unlabeled": r["cnt"] for r in rows}
    labeled = total - breakdown.get("unlabeled", breakdown.get(None, 0))
    return {"total": total, "labeled": labeled, "breakdown": breakdown}
