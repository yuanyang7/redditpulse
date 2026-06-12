"""Tests for the service layer: search w/ fetch runs, analyze caching, data mgmt."""

from unittest import mock

import pytest

from redditpulse import services
from redditpulse.config import Settings, override_settings
from redditpulse.exceptions import NoCommentsError, TopicNotFoundError

from conftest import make_comment


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Point the whole service layer at a throwaway database."""
    override_settings(Settings(db_path=tmp_path / "svc.db"))
    yield
    override_settings(Settings())


class FakeFetcher:
    """Stands in for a fetcher module; returns a fixed list of comments."""

    def __init__(self, comments):
        self.comments = comments
        self.calls = []

    def search_comments(self, keywords, subreddits=None, limit_per_keyword=25,
                        time_range=None, progress_callback=None, stop_check=None,
                        on_truncated=None, on_skipped=None):
        self.calls.append({
            "keywords": keywords, "subreddits": subreddits,
            "time_range": time_range,
        })
        return list(self.comments)


def _search(comments, **kwargs):
    fake = FakeFetcher(comments)
    with mock.patch("redditpulse.services.search.get_fetcher", return_value=fake):
        result = services.search_topic(keywords=["kw"], **kwargs)
    return result, fake


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_search_creates_topic_and_records_run():
    result, fake = _search(
        [make_comment("a"), make_comment("b")],
        topic="my topic", subreddits=["tech"], time_filter="month",
    )
    assert result["status"] == "new"
    assert result["new_comments"] == 2
    assert result["total_comments"] == 2

    runs = services.list_fetch_runs("my topic")
    assert len(runs) == 1
    assert runs[0]["status"] == "done"
    assert runs[0]["keywords"] == ["kw"]
    assert runs[0]["subreddits"] == ["tech"]
    assert runs[0]["inserted"] == 2
    assert runs[0]["window"] == "month"


def test_search_merge_dedupes_across_sessions():
    _search([make_comment("a"), make_comment("b")], topic="t")
    result, _ = _search([make_comment("b"), make_comment("c")], topic="t",
                        refresh=True)
    assert result["new_comments"] == 1  # "b" merged away
    assert result["total_comments"] == 3
    assert len(services.list_fetch_runs("t")) == 2


def test_search_refresh_inherits_subreddits_from_last_run():
    _search([make_comment("a")], topic="t", subreddits=["technology", "privacy"])
    result, fake = _search([make_comment("b")], topic="t", refresh=True)
    assert result["new_comments"] == 1
    assert fake.calls[0]["subreddits"] == ["technology", "privacy"]
    runs = services.list_fetch_runs("t")
    assert runs[0]["subreddits"] == ["technology", "privacy"]


def test_search_refresh_explicit_subreddits_override_last_run():
    _search([make_comment("a")], topic="t", subreddits=["technology"])
    result, fake = _search([make_comment("b")], topic="t", refresh=True,
                           subreddits=["worldnews"])
    assert fake.calls[0]["subreddits"] == ["worldnews"]


def test_search_explicit_date_range_recorded():
    result, fake = _search(
        [make_comment("a")], topic="ranged",
        after="2025-01-01", before="2025-02-01",
    )
    rng = fake.calls[0]["time_range"]
    assert rng.after_date() == "2025-01-01"
    run = services.list_fetch_runs("ranged")[0]
    assert run["time_filter"] is None
    assert run["after_utc"] == rng.after_utc
    assert "2025-01-01" in run["window"]


def test_search_existing_topic_without_refresh():
    _search([make_comment("a")], topic="t")
    result, fake = _search([make_comment("b")], topic="t")
    assert result["status"] == "exists"
    assert fake.calls == []  # no fetch happened


def test_search_failure_marks_run_error():
    failing = mock.Mock()
    failing.search_comments.side_effect = RuntimeError("boom")
    with mock.patch("redditpulse.services.search.get_fetcher", return_value=failing):
        with pytest.raises(RuntimeError):
            services.search_topic(topic="t", keywords=["kw"])
    runs = services.list_fetch_runs("t")
    assert runs[0]["status"] == "error"
    assert "boom" in runs[0]["error"]


# ---------------------------------------------------------------------------
# Analyze: caching & score filters
# ---------------------------------------------------------------------------

def _seeded_topic(name="t"):
    comments = [
        make_comment("a", body="I love this, wonderful!", score=50),
        make_comment("b", body="This is terrible.", score=2),
        make_comment("c", body="The sky has clouds.", score=0),
    ]
    _search(comments, topic=name)
    return name


def test_analyze_sentiment_only_and_cache():
    topic = _seeded_topic()
    first = services.analyze_topic(topic, sentiment_only=True)
    assert "cached" not in first
    assert first["sentiment"]["total"] == 3
    assert "upvote_weighted" in first["sentiment"]

    second = services.analyze_topic(topic, sentiment_only=True)
    assert second["cached"] is True
    assert second["sentiment"] == first["sentiment"]


def test_analyze_cache_miss_on_new_data_or_params():
    topic = _seeded_topic()
    services.analyze_topic(topic, sentiment_only=True)

    # Different params -> new analysis, not the cached one
    other = services.analyze_topic(topic, sentiment_only=True, min_score=1)
    assert "cached" not in other
    assert other["sentiment"]["total"] == 2  # comment "c" (score 0) excluded

    # New comment arrives -> signature changes
    _search([make_comment("d", body="new info", score=1)], topic=topic, refresh=True)
    again = services.analyze_topic(topic, sentiment_only=True)
    assert "cached" not in again
    assert again["sentiment"]["total"] == 4


def test_analyze_min_score_no_comments():
    topic = _seeded_topic()
    with pytest.raises(NoCommentsError):
        services.analyze_topic(topic, sentiment_only=True, min_score=1000)


def test_browse_min_score():
    topic = _seeded_topic()
    services.analyze_topic(topic, sentiment_only=True)
    data = services.browse_comments(topic, sentiment_filter="positive", min_score=10)
    assert all(c["score"] >= 10 for c in data["comments"])


# ---------------------------------------------------------------------------
# Data management
# ---------------------------------------------------------------------------

def test_trim_by_score():
    topic = _seeded_topic()
    result = services.trim_comments(topic, min_score=1)
    assert result["deleted"] == 1  # score-0 comment removed
    assert result["remaining"] == 2


def test_trim_noop_without_filters():
    topic = _seeded_topic()
    result = services.trim_comments(topic)
    assert result["deleted"] == 0
    assert result["remaining"] == 3


def test_validate_reports():
    topic = _seeded_topic()
    report = services.validate_topic_data(topic)
    assert report["total"] == 3
    assert report["ok"] is True

    # Damage the data: comment with no timestamp
    _search([make_comment("z", created_utc=0)], topic=topic, refresh=True)
    report = services.validate_topic_data(topic)
    assert report["missing_timestamp"] == 1
    assert report["ok"] is False


def test_delete_fetch_run_removes_exclusive_comments():
    _search([make_comment("a"), make_comment("b")], topic="t")
    _search([make_comment("b"), make_comment("c")], topic="t", refresh=True)
    runs = services.list_fetch_runs("t")  # newest first
    result = services.delete_fetch_run("t", runs[0]["id"])
    assert result["comments_deleted"] == 1  # only "c" was exclusive
    assert services.get_topic_summary("t")["comment_count"] == 2


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

def test_topic_not_found():
    with pytest.raises(TopicNotFoundError):
        services.get_topic_summary("missing")


def test_next_available_topic_name():
    existing = ["AI", "AI v2"]
    assert services.next_available_topic_name("new", existing) == "new"
    assert services.next_available_topic_name("AI", existing) == "AI v3"
    assert services.next_available_topic_name("AI v2", existing) == "AI v3"


def test_showcase_config_roundtrip():
    topic = _seeded_topic()
    assert services.get_showcase_config(topic) is None
    cfg = {"title": "Custom", "sections": ["sentiment"]}
    services.set_showcase_config(topic, cfg)
    assert services.get_showcase_config(topic) == cfg
