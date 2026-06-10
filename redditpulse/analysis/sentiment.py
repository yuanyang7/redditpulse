"""Sentiment scoring: VADER locally, Claude optionally, score-weighted summaries."""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_vader = SentimentIntensityAnalyzer()

# Nominal compound score per Claude label, so downstream code that expects a
# numeric compound (averages, sorting) keeps working.
_LABEL_COMPOUND = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}


def sentiment_label(compound: float) -> str:
    if compound >= 0.05:
        return "positive"
    elif compound <= -0.05:
        return "negative"
    return "neutral"


def vader_compound(text: str) -> float:
    return _vader.polarity_scores(text)["compound"]


def score_comments_vader(comments: list[dict]) -> list[dict]:
    """Per-comment VADER scores: [{reddit_id, compound, label}, ...]."""
    scores = []
    for c in comments:
        compound = vader_compound(c["body"])
        scores.append({
            "reddit_id": c["reddit_id"],
            "compound": compound,
            "label": sentiment_label(compound),
        })
    return scores


def score_comments_claude(comments: list[dict]) -> list[dict]:
    """Per-comment Claude labels, same shape as score_comments_vader."""
    from . import llm

    labels = llm.classify_sentiment_batch([c["body"] for c in comments])
    scores = []
    for c, label in zip(comments, labels):
        label = label if label in _LABEL_COMPOUND else "neutral"
        scores.append({
            "reddit_id": c["reddit_id"],
            "compound": _LABEL_COMPOUND[label],
            "label": label,
        })
    return scores


def summarize(scores: list[dict], comments: list[dict] | None = None) -> dict:
    """Aggregate per-comment scores into a summary.

    When `comments` is provided, also computes an upvote-weighted breakdown:
    each comment is weighted by max(score, 1), so heavily upvoted comments —
    the opinions the community actually endorsed — count proportionally more.
    """
    pos = sum(1 for s in scores if s["label"] == "positive")
    neg = sum(1 for s in scores if s["label"] == "negative")
    neu = sum(1 for s in scores if s["label"] == "neutral")
    avg = sum(s["compound"] for s in scores) / len(scores) if scores else 0

    summary = {
        "total": len(scores),
        "positive": pos,
        "negative": neg,
        "neutral": neu,
        "average_compound": round(avg, 4),
    }

    if comments:
        by_id = {c["reddit_id"]: c for c in comments}
        weights = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
        weighted_compound = 0.0
        total_weight = 0.0
        for s in scores:
            c = by_id.get(s["reddit_id"])
            if c is None:
                continue
            w = max(c.get("score", 0), 1)
            weights[s["label"]] += w
            weighted_compound += s["compound"] * w
            total_weight += w
        if total_weight:
            summary["upvote_weighted"] = {
                "pct_positive": round(100 * weights["positive"] / total_weight, 1),
                "pct_negative": round(100 * weights["negative"] / total_weight, 1),
                "pct_neutral": round(100 * weights["neutral"] / total_weight, 1),
                "average_compound": round(weighted_compound / total_weight, 4),
            }

    return summary


def analyze_sentiment(comments: list[dict], model: str = "vader") -> dict:
    """Score every comment and summarize. Returns summary + per-comment scores."""
    if model == "claude":
        scores = score_comments_claude(comments)
    else:
        scores = score_comments_vader(comments)
    summary = summarize(scores, comments)
    summary["scores"] = scores
    return summary
