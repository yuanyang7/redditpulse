"""Tests for the storage layer: migrations and repository functions."""

from redditpulse.storage import db as dbmod
from redditpulse.storage import repo

from conftest import make_comment


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

def test_fresh_db_reaches_current_schema(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == dbmod.SCHEMA_VERSION
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"topics", "comments", "analyses", "fetch_runs",
            "fetch_run_comments"} <= tables


def test_legacy_db_migrates_preserving_data(legacy_conn):
    dbmod.migrate(legacy_conn)
    assert legacy_conn.execute("PRAGMA user_version").fetchone()[0] == dbmod.SCHEMA_VERSION

    topic = repo.get_topic(legacy_conn, "old topic")
    assert topic["note"] == "a note"
    comments = repo.get_comments(legacy_conn, topic["id"])
    assert len(comments) == 1
    assert comments[0]["reddit_id"] == "abc"
    assert comments[0]["manual_label"] == "positive"
    assert repo.get_latest_analysis(legacy_conn, topic["id"]) is not None


def test_migration_is_idempotent(legacy_conn):
    dbmod.migrate(legacy_conn)
    dbmod.migrate(legacy_conn)  # no-op second time
    assert repo.count_comments(legacy_conn, 1) == 1


# ---------------------------------------------------------------------------
# Comments: per-topic dedupe
# ---------------------------------------------------------------------------

def test_insert_comments_dedupes_within_topic(conn):
    tid = repo.create_topic(conn, "t", ["k"])
    n = repo.insert_comments(conn, tid, [make_comment("a"), make_comment("a")])
    assert n == 1
    assert repo.count_comments(conn, tid) == 1


def test_same_reddit_id_allowed_across_topics(conn):
    t1 = repo.create_topic(conn, "t1", ["k"])
    t2 = repo.create_topic(conn, "t2", ["k"])
    assert repo.insert_comments(conn, t1, [make_comment("shared")]) == 1
    assert repo.insert_comments(conn, t2, [make_comment("shared")]) == 1


def test_get_comments_filters(conn):
    tid = repo.create_topic(conn, "t", ["k"])
    repo.insert_comments(conn, tid, [
        make_comment("a", score=10, created_utc=100),
        make_comment("b", score=-2, created_utc=200),
        make_comment("c", score=5, created_utc=300),
    ])
    assert {c["reddit_id"] for c in repo.get_comments(conn, tid, min_score=0)} == {"a", "c"}
    assert {c["reddit_id"] for c in repo.get_comments(conn, tid, after_utc=150)} == {"b", "c"}
    assert {c["reddit_id"] for c in repo.get_comments(conn, tid, before_utc=250)} == {"a", "b"}
    newest_first = repo.get_comments(conn, tid, order_by="newest")
    assert [c["reddit_id"] for c in newest_first] == ["c", "b", "a"]


def test_trim_comments(conn):
    tid = repo.create_topic(conn, "t", ["k"])
    repo.insert_comments(conn, tid, [
        make_comment("a", score=10, created_utc=100),
        make_comment("b", score=1, created_utc=200),
        make_comment("c", score=5, created_utc=300),
    ])
    deleted = repo.delete_comments(conn, tid, before_utc=150)
    assert deleted == 1
    deleted = repo.delete_comments(conn, tid, max_score=5)
    assert deleted == 1  # only "b" (score 1 < 5)
    assert repo.count_comments(conn, tid) == 1


def test_comment_stats(conn):
    tid = repo.create_topic(conn, "t", ["k"])
    repo.insert_comments(conn, tid, [
        make_comment("a", score=4, created_utc=100),
        make_comment("b", score=-1, created_utc=0),
    ])
    stats = repo.comment_stats(conn, tid)
    assert stats["total"] == 2
    assert stats["missing_ts"] == 1
    assert stats["negative_score"] == 1


# ---------------------------------------------------------------------------
# Fetch runs
# ---------------------------------------------------------------------------

def test_fetch_run_lifecycle(conn):
    tid = repo.create_topic(conn, "t", ["k1", "k2"])
    run_id = repo.create_fetch_run(
        conn, tid, source="arctic", keywords=["k1", "k2"],
        subreddits=["tech"], time_filter=None,
        after_utc=100.0, before_utc=200.0, limit_per_keyword=50,
    )
    repo.insert_comments(conn, tid, [make_comment("a"), make_comment("b")],
                         run_id=run_id)
    repo.finish_fetch_run(conn, run_id, status="done", fetched=2, inserted=2)

    runs = repo.get_fetch_runs(conn, tid)
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "done"
    assert run["keywords"] == ["k1", "k2"]
    assert run["subreddits"] == ["tech"]
    assert run["after_utc"] == 100.0
    assert run["inserted"] == 2


def test_overlapping_runs_link_existing_comments(conn):
    tid = repo.create_topic(conn, "t", ["k"])
    r1 = repo.create_fetch_run(conn, tid, "arctic", ["k"])
    repo.insert_comments(conn, tid, [make_comment("a")], run_id=r1)
    r2 = repo.create_fetch_run(conn, tid, "arctic", ["k"])
    inserted = repo.insert_comments(conn, tid, [make_comment("a"), make_comment("b")],
                                    run_id=r2)
    assert inserted == 1  # "a" deduped
    links = conn.execute(
        "SELECT COUNT(*) FROM fetch_run_comments WHERE run_id = ?", (r2,)
    ).fetchone()[0]
    assert links == 2  # but both linked to run 2


def test_delete_run_with_exclusive_comments(conn):
    tid = repo.create_topic(conn, "t", ["k"])
    r1 = repo.create_fetch_run(conn, tid, "arctic", ["k"])
    repo.insert_comments(conn, tid, [make_comment("shared")], run_id=r1)
    r2 = repo.create_fetch_run(conn, tid, "arctic", ["k"])
    repo.insert_comments(conn, tid, [make_comment("shared"), make_comment("only2")],
                         run_id=r2)

    deleted = repo.delete_fetch_run(conn, r2, delete_exclusive_comments=True)
    assert deleted == 1  # "only2" removed, "shared" kept (run 1 also saw it)
    assert repo.count_comments(conn, tid) == 1
    assert len(repo.get_fetch_runs(conn, tid)) == 1


# ---------------------------------------------------------------------------
# Analyses: signature caching support
# ---------------------------------------------------------------------------

def test_find_analysis_by_signature(conn):
    tid = repo.create_topic(conn, "t", ["k"])
    repo.save_analysis(conn, tid, 5, "{}", "{}", '{"ok": true}',
                       params={"model": "vader"}, signature="sig123")
    assert repo.find_analysis_by_signature(conn, tid, "sig123") is not None
    assert repo.find_analysis_by_signature(conn, tid, "other") is None


def test_label_counts(conn):
    tid = repo.create_topic(conn, "t", ["k"])
    repo.insert_comments(conn, tid, [make_comment("a"), make_comment("b")])
    comments = repo.get_comments(conn, tid)
    repo.set_comment_label(conn, comments[0]["id"], "positive")
    counts = repo.count_comments_by_label(conn, tid)
    assert counts == {"total": 2, "labeled": 1,
                      "breakdown": {"positive": 1, "unlabeled": 1}}
