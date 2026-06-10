"""Tests for the analysis package: sentiment summaries, weighting, evaluation."""

import pytest

from redditpulse.analysis import evaluation, sentiment

from conftest import make_comment


def test_sentiment_label_thresholds():
    assert sentiment.sentiment_label(0.5) == "positive"
    assert sentiment.sentiment_label(0.05) == "positive"
    assert sentiment.sentiment_label(0.0) == "neutral"
    assert sentiment.sentiment_label(-0.05) == "negative"


def test_analyze_sentiment_vader():
    comments = [
        make_comment("a", body="I love this, it's wonderful!", score=10),
        make_comment("b", body="This is terrible and awful.", score=1),
        make_comment("c", body="The sky has clouds.", score=1),
    ]
    result = sentiment.analyze_sentiment(comments, model="vader")
    assert result["total"] == 3
    assert result["positive"] == 1
    assert result["negative"] == 1
    assert result["neutral"] == 1
    assert len(result["scores"]) == 3


def test_upvote_weighted_summary():
    # A highly upvoted positive comment should dominate the weighted view.
    comments = [
        make_comment("a", body="pos", score=98),
        make_comment("b", body="neg", score=1),
    ]
    scores = [
        {"reddit_id": "a", "compound": 1.0, "label": "positive"},
        {"reddit_id": "b", "compound": -1.0, "label": "negative"},
    ]
    summary = sentiment.summarize(scores, comments)
    assert summary["positive"] == 1 and summary["negative"] == 1  # unweighted: tied
    weighted = summary["upvote_weighted"]
    assert weighted["pct_positive"] == pytest.approx(98.99, abs=0.1)
    assert weighted["average_compound"] > 0.9


def test_weight_floor_for_zero_score():
    # Score 0 / negative comments still count with weight 1, not 0.
    comments = [make_comment("a", body="x", score=0)]
    scores = [{"reddit_id": "a", "compound": 1.0, "label": "positive"}]
    summary = sentiment.summarize(scores, comments)
    assert summary["upvote_weighted"]["pct_positive"] == 100.0


def test_evaluation_metrics():
    gt = ["positive", "positive", "negative", "neutral"]
    preds = ["positive", "negative", "negative", "neutral"]
    m = evaluation.compute_metrics(gt, preds, "vader")
    assert m["accuracy"] == 0.75
    assert m["per_class"]["positive"]["precision"] == 1.0
    assert m["per_class"]["positive"]["recall"] == 0.5
    assert m["confusion_matrix"]["positive"]["negative"] == 1
    assert m["per_class"]["neutral"]["f1"] == 1.0


def test_evaluation_unknown_model():
    with pytest.raises(ValueError):
        evaluation.predict(["x"], "nope")
