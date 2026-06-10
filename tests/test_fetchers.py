"""Tests for fetcher utilities and the Arctic Shift fetcher (HTTP mocked)."""

import time as _time
from unittest import mock

import pytest

from redditpulse.exceptions import FetchError
from redditpulse.fetchers import arctic, get_fetcher
from redditpulse.fetchers.base import (
    TimeRange, is_valid_comment, keyword_words, mentions_any_keyword,
)


# ---------------------------------------------------------------------------
# TimeRange
# ---------------------------------------------------------------------------

def test_time_range_from_filter():
    rng = TimeRange.from_filter("week")
    assert rng.before_utc is None
    assert _time.time() - rng.after_utc == pytest.approx(7 * 86400, abs=60)
    assert TimeRange.from_filter("all") == TimeRange()


def test_time_range_from_dates_inclusive_before():
    rng = TimeRange.from_dates("2025-01-01", "2025-01-31")
    assert rng.after_date() == "2025-01-01"
    # "before 2025-01-31" includes the whole day, so the bound is Feb 1.
    assert rng.before_date() == "2025-02-01"
    # Jan 31 noon is inside the range.
    from datetime import datetime, timezone
    assert rng.contains(datetime(2025, 1, 31, 12, tzinfo=timezone.utc).timestamp())
    assert not rng.contains(datetime(2025, 2, 2, tzinfo=timezone.utc).timestamp())
    assert not rng.contains(datetime(2024, 12, 31, tzinfo=timezone.utc).timestamp())


def test_time_range_open_sides():
    assert TimeRange.from_dates(None, None) == TimeRange()
    rng = TimeRange.from_dates("2025-06-01", None)
    assert rng.before_utc is None
    assert rng.contains(_time.time())


# ---------------------------------------------------------------------------
# Validation / relevance helpers
# ---------------------------------------------------------------------------

def test_is_valid_comment():
    assert is_valid_comment("id1", "real text", "user")
    assert not is_valid_comment(None, "text", "user")
    assert not is_valid_comment("id1", "", "user")
    assert not is_valid_comment("id1", "[deleted]", "user")
    assert not is_valid_comment("id1", "[removed]", "user")
    assert not is_valid_comment("id1", "bot text", "AutoModerator")


def test_keyword_relevance():
    words = keyword_words(["electric cars", "the EV market"])
    assert "electric" in words and "cars" in words and "market" in words
    assert "the" not in words
    assert mentions_any_keyword("I love my electric vehicle", words)
    assert not mentions_any_keyword("totally unrelated text", words)
    assert mentions_any_keyword("anything", set())  # no words -> no filtering


def test_get_fetcher_registry():
    assert get_fetcher("arctic") is arctic
    with pytest.raises(ValueError):
        get_fetcher("nope")


# ---------------------------------------------------------------------------
# Arctic Shift fetcher (mocked HTTP)
# ---------------------------------------------------------------------------

def _response(status=200, data=None, error=""):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = {"data": data or []} if status == 200 else {"error": error}
    resp.text = error
    return resp


@mock.patch("redditpulse.fetchers.arctic.time.sleep")
@mock.patch("redditpulse.fetchers.arctic.requests.get")
def test_arctic_search_normalizes_and_dedupes(mock_get, _sleep):
    raw = [
        {"id": "c1", "author": "u1", "body": "great point", "score": 7,
         "controversiality": 0, "subreddit": "tech", "created_utc": 1700000000,
         "link_id": "t3_post1"},
        {"id": "c1", "author": "u1", "body": "great point", "score": 7,
         "subreddit": "tech", "created_utc": 1700000000},  # duplicate id
        {"id": "c2", "author": "AutoModerator", "body": "bot", "score": 1,
         "subreddit": "tech", "created_utc": 1700000001},  # filtered
        {"id": "c3", "author": "u2", "body": "[removed]", "score": 1,
         "subreddit": "tech", "created_utc": 1700000002},  # filtered
    ]
    mock_get.return_value = _response(data=raw)

    comments = arctic.search_comments(["kw"], subreddits=["tech"])
    assert len(comments) == 1
    c = comments[0]
    assert c["reddit_id"] == "c1"
    assert c["controversiality"] == 0
    assert c["permalink"] == "https://reddit.com/r/tech/comments/post1/_/c1/"


@mock.patch("redditpulse.fetchers.arctic.time.sleep")
@mock.patch("redditpulse.fetchers.arctic.requests.get")
def test_arctic_passes_date_range_params(mock_get, _sleep):
    mock_get.return_value = _response(data=[])
    rng = TimeRange.from_dates("2025-01-01", "2025-03-01")
    arctic.search_comments(["kw"], subreddits=["tech"], time_range=rng)
    params = mock_get.call_args.kwargs["params"]
    assert params["after"] == "2025-01-01"
    assert params["before"] == "2025-03-02"  # inclusive end of Mar 1


@mock.patch("redditpulse.fetchers.arctic.time.sleep")
@mock.patch("redditpulse.fetchers.arctic.requests.get")
def test_arctic_all_timeouts_raise(mock_get, _sleep):
    mock_get.return_value = _response(status=422, error="Timeout")
    with pytest.raises(FetchError):
        arctic.search_comments(["kw"], subreddits=["tech"])


@mock.patch("redditpulse.fetchers.arctic.time.sleep")
@mock.patch("redditpulse.fetchers.arctic.requests.get")
def test_arctic_stop_check(mock_get, _sleep):
    mock_get.return_value = _response(data=[])
    comments = arctic.search_comments(
        ["k1", "k2"], subreddits=["a", "b"], stop_check=lambda: True
    )
    assert comments == []
    assert mock_get.call_count == 0
