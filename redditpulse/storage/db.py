"""SQLite connection handling and versioned schema migrations.

The schema version is tracked with ``PRAGMA user_version``. Each migration
step upgrades exactly one version; ``migrate()`` runs whatever steps are
needed, so both fresh databases and databases created by older versions of
RedditPulse end up at ``SCHEMA_VERSION``.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..config import get_settings

SCHEMA_VERSION = 4


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection to the given (or configured) database and migrate it."""
    path = Path(db_path) if db_path is not None else get_settings().db_path
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


# Back-compat alias — older modules call get_connection().
get_connection = connect


@contextmanager
def session(db_path: Path | str | None = None):
    """Context manager yielding a migrated connection, closed on exit."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    while version < SCHEMA_VERSION:
        version += 1
        _MIGRATIONS[version](conn)
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Baseline schema (matches what pre-versioning releases created)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            keywords    TEXT NOT NULL,
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
            sentiment_summary TEXT,
            themes      TEXT,
            raw_result  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_comments_topic ON comments(topic_id);
        CREATE INDEX IF NOT EXISTS idx_analyses_topic ON analyses(topic_id);
    """)
    _add_column_if_missing(conn, "comments", "manual_label", "TEXT")
    _add_column_if_missing(conn, "topics", "note", "TEXT")


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Multi-session data management.

    - comments: uniqueness becomes per-topic (the same Reddit comment may be
      relevant to several topics), and gains an upvote-rate proxy column.
    - fetch_runs: records every fetch session's full parameters and outcome.
    - fetch_run_comments: which run(s) returned which comment, so data from
      different query sessions can be merged, trimmed and audited.
    - analyses: records parameters and a comment-set signature so identical
      re-analyses can be served from cache instead of re-calling the API.
    - topics: per-topic showcase configuration (JSON).
    """
    conn.executescript("""
        ALTER TABLE comments RENAME TO comments_old;

        CREATE TABLE comments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id        INTEGER NOT NULL REFERENCES topics(id),
            reddit_id       TEXT NOT NULL,
            subreddit       TEXT NOT NULL,
            author          TEXT,
            body            TEXT NOT NULL,
            score           INTEGER NOT NULL DEFAULT 0,
            controversiality INTEGER,
            permalink       TEXT,
            created_utc     REAL NOT NULL,
            fetched_at      TEXT NOT NULL,
            manual_label    TEXT,
            UNIQUE (topic_id, reddit_id)
        );

        INSERT INTO comments (id, topic_id, reddit_id, subreddit, author, body,
                              score, permalink, created_utc, fetched_at, manual_label)
        SELECT id, topic_id, reddit_id, subreddit, author, body,
               score, permalink, created_utc, fetched_at, manual_label
        FROM comments_old;

        DROP TABLE comments_old;
        CREATE INDEX IF NOT EXISTS idx_comments_topic ON comments(topic_id);
        CREATE INDEX IF NOT EXISTS idx_comments_created ON comments(topic_id, created_utc);

        CREATE TABLE IF NOT EXISTS fetch_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id        INTEGER NOT NULL REFERENCES topics(id),
            source          TEXT NOT NULL,          -- arctic | praw | rss
            keywords        TEXT NOT NULL,          -- JSON array
            subreddits      TEXT,                   -- JSON array or NULL
            time_filter     TEXT,                   -- hour/day/.../all or NULL
            after_utc       REAL,                   -- explicit range start (epoch)
            before_utc      REAL,                   -- explicit range end (epoch)
            limit_per_keyword INTEGER,
            min_relevance   REAL,
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            status          TEXT NOT NULL DEFAULT 'running',  -- running|done|stopped|error
            fetched         INTEGER NOT NULL DEFAULT 0,  -- raw results from source
            inserted        INTEGER NOT NULL DEFAULT 0,  -- new rows after dedupe
            error           TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_fetch_runs_topic ON fetch_runs(topic_id);

        CREATE TABLE IF NOT EXISTS fetch_run_comments (
            run_id      INTEGER NOT NULL REFERENCES fetch_runs(id) ON DELETE CASCADE,
            comment_id  INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
            PRIMARY KEY (run_id, comment_id)
        );
    """)
    _add_column_if_missing(conn, "analyses", "params", "TEXT")
    _add_column_if_missing(conn, "analyses", "signature", "TEXT")
    _add_column_if_missing(conn, "topics", "showcase_config", "TEXT")


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Track per-run query truncation, so fetches that silently dropped
    results (a query hit its per-keyword/subreddit cap) are visible."""
    _add_column_if_missing(conn, "fetch_runs", "truncated_subreddits", "TEXT")


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """Track keywords left unprocessed (or partially processed) by an early
    stop, so runs ended via the Stop button show what's missing."""
    _add_column_if_missing(conn, "fetch_runs", "skipped_keywords", "TEXT")


_MIGRATIONS = {
    1: _migrate_v1,
    2: _migrate_v2,
    3: _migrate_v3,
    4: _migrate_v4,
}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str,
                           decl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
