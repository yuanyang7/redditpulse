import sqlite3

import pytest

from redditpulse.storage import db as dbmod


@pytest.fixture
def conn(tmp_path):
    """A migrated connection to a fresh temporary database."""
    connection = dbmod.connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def legacy_conn(tmp_path):
    """A connection to a database with the pre-versioning (legacy) schema and data."""
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE topics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            keywords    TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            note        TEXT
        );
        CREATE TABLE comments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id        INTEGER NOT NULL REFERENCES topics(id),
            reddit_id       TEXT NOT NULL UNIQUE,
            subreddit       TEXT NOT NULL,
            author          TEXT,
            body            TEXT NOT NULL,
            score           INTEGER NOT NULL DEFAULT 0,
            permalink       TEXT,
            created_utc     REAL NOT NULL,
            fetched_at      TEXT NOT NULL,
            manual_label    TEXT
        );
        CREATE TABLE analyses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id    INTEGER NOT NULL REFERENCES topics(id),
            run_at      TEXT NOT NULL,
            num_comments INTEGER NOT NULL,
            sentiment_summary TEXT,
            themes      TEXT,
            raw_result  TEXT
        );
        INSERT INTO topics (name, keywords, created_at, note)
        VALUES ('old topic', 'kw1,kw2', '2025-01-01T00:00:00+00:00', 'a note');
        INSERT INTO comments (topic_id, reddit_id, subreddit, author, body, score,
                              permalink, created_utc, fetched_at, manual_label)
        VALUES (1, 'abc', 'tech', 'user1', 'hello world', 5,
                'https://reddit.com/x', 1735689600, '2025-01-01T00:00:00+00:00', 'positive');
        INSERT INTO analyses (topic_id, run_at, num_comments, sentiment_summary, themes, raw_result)
        VALUES (1, '2025-01-02T00:00:00+00:00', 1, '{}', '{}', '{}');
    """)
    connection.commit()
    yield connection
    connection.close()


def make_comment(reddit_id="c1", subreddit="tech", body="some text",
                 score=1, created_utc=1735689600.0, **extra):
    c = {
        "reddit_id": reddit_id,
        "subreddit": subreddit,
        "author": "someone",
        "body": body,
        "score": score,
        "permalink": f"https://reddit.com/{reddit_id}",
        "created_utc": created_utc,
    }
    c.update(extra)
    return c
