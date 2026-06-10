"""Analysis services: sentiment + themes with result caching, browsing,
trends, labeling and evaluation.

Caching: every analysis stores a signature of (comment ids, parameters).
Re-running an identical analysis — e.g. after merging a fetch that added
nothing new — is served from the stored result instead of re-calling the
Claude API.
"""

import hashlib
import json
from datetime import datetime, timezone

from ..exceptions import NoAnalysisError, NoCommentsError, TopicNotFoundError
from ..analysis import evaluation, sentiment
from ..storage import repo
from ..storage.db import session


def _require_topic(conn, topic: str) -> dict:
    row = repo.get_topic(conn, topic)
    if not row:
        raise TopicNotFoundError(f"Topic '{topic}' not found. Run 'search' first.")
    return row


def _analysis_signature(comments: list[dict], params: dict) -> str:
    """Stable hash of the analyzed comment set + analysis parameters."""
    ids = sorted(c["reddit_id"] for c in comments)
    payload = json.dumps({"ids": ids, "params": params}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def analyze_topic(
    topic: str,
    limit: int = 500,
    sentiment_only: bool = False,
    reset_analyses: bool = False,
    sentiment_model: str = "vader",
    min_score: int | None = None,
    use_cache: bool = True,
) -> dict:
    """Run sentiment + optional theme analysis. Returns the full result dict.

    `min_score` drops low-vote comments before analysis, so conclusions rest
    on comments the community actually engaged with. If an identical analysis
    (same comments, same parameters) already exists, it's returned from the
    database instead of re-calling the API (`cached: true` in the result).
    """
    with session() as conn:
        topic_row = _require_topic(conn, topic)

        if reset_analyses:
            repo.delete_analyses(conn, topic_row["id"])

        comments = repo.get_comments(conn, topic_row["id"], limit=limit,
                                     min_score=min_score)
        if not comments:
            raise NoCommentsError(
                f"No comments found for '{topic}'"
                + (f" with score >= {min_score}" if min_score is not None else "")
                + "."
            )

        params = {
            "sentiment_model": sentiment_model,
            "sentiment_only": sentiment_only,
            "min_score": min_score,
            "limit": limit,
        }
        signature = _analysis_signature(comments, params)

        if use_cache and not reset_analyses:
            cached = repo.find_analysis_by_signature(conn, topic_row["id"], signature)
            if cached and cached.get("raw_result"):
                result = json.loads(cached["raw_result"])
                result["cached"] = True
                result["run_at"] = cached["run_at"]
                return result

        sent = sentiment.analyze_sentiment(comments, model=sentiment_model)

        themes: dict = {}
        if not sentiment_only:
            from ..analysis import llm
            themes = llm.analyze_themes(topic, comments)
            if themes.get("subtopic_breakdown"):
                recomputed = llm.compute_subtopic_breakdown(
                    comments, themes["subtopic_breakdown"])
                if recomputed:
                    themes["subtopic_breakdown"] = recomputed
                else:
                    themes.pop("subtopic_breakdown", None)

        result = {
            "sentiment": {k: v for k, v in sent.items() if k != "scores"},
            "themes": themes,
            "per_comment_sentiment": sent["scores"],
            "params": params,
        }

        repo.save_analysis(
            conn, topic_row["id"],
            num_comments=len(comments),
            sentiment_summary=json.dumps(result["sentiment"]),
            themes=json.dumps(result["themes"]),
            raw_result=json.dumps(result),
            params=params,
            signature=signature,
        )
        return result


def export_analysis(topic: str) -> dict:
    """Return the latest saved analysis for a topic."""
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        analysis = repo.get_latest_analysis(conn, topic_row["id"])
        if not analysis:
            raise NoAnalysisError(f"No analysis found for '{topic}'. Run 'analyze' first.")
        return {
            "result": json.loads(analysis["raw_result"]),
            "run_at": analysis["run_at"],
        }


def _stored_sentiment(conn, topic_id: int) -> dict:
    """Per-comment sentiment from the latest analysis, keyed by reddit_id."""
    latest = repo.get_latest_analysis(conn, topic_id)
    if latest and latest.get("raw_result"):
        try:
            raw = json.loads(latest["raw_result"])
            return {s["reddit_id"]: s for s in raw.get("per_comment_sentiment", [])}
        except (ValueError, KeyError):
            pass
    return {}


def browse_comments(
    topic: str,
    sentiment_filter: str = "negative",
    limit: int = 20,
    min_score: int | None = None,
) -> dict:
    """Return comments filtered by sentiment label (and optionally min score).

    Reuses the latest analysis's per-comment labels (which reflect whichever
    model was used — VADER or Claude) so Browse matches the Analyze tab,
    falling back to computing VADER on the fly when no analysis exists yet.
    """
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        comments = repo.get_comments(conn, topic_row["id"], limit=2000,
                                     min_score=min_score)
        stored = _stored_sentiment(conn, topic_row["id"])

        filtered = []
        for c in comments:
            s = stored.get(c["reddit_id"])
            if s is not None:
                compound = s.get("compound", 0.0)
                lbl = s.get("label", sentiment.sentiment_label(compound))
            else:
                compound = sentiment.vader_compound(c["body"])
                lbl = sentiment.sentiment_label(compound)
            if lbl == sentiment_filter:
                filtered.append({
                    "body": c["body"],
                    "score": c["score"],
                    "compound": compound,
                    "subreddit": c["subreddit"],
                    "author": c.get("author", ""),
                    "permalink": c.get("permalink", ""),
                })

        # Sort strongest sentiment first
        filtered.sort(key=lambda x: abs(x["compound"]), reverse=True)
        filtered = filtered[:limit]

        return {"sentiment": sentiment_filter, "comments": filtered,
                "total": len(filtered)}


def get_sentiment_trends(topic: str, min_comments: int = 3,
                         bucket: str = "auto") -> dict:
    """Bucket a topic's comments over time and summarize sentiment per bucket.

    Sentiment per comment reuses the latest analysis's stored labels (so it
    matches the Analyze/Browse tabs), falling back to VADER on the fly.
    Bucket size adapts to the data's date span unless forced
    ("day"|"week"|"month").
    """
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        comments = repo.get_comments(conn, topic_row["id"], limit=5000)
        comments = [c for c in comments if c.get("created_utc")]
        if not comments:
            raise NoCommentsError(f"No timestamped comments found for '{topic}'.")

        stored = _stored_sentiment(conn, topic_row["id"])
        source = "analysis" if stored else "vader"

        # Choose bucket size from the data span unless forced.
        times = [c["created_utc"] for c in comments]
        span_days = (max(times) - min(times)) / 86400
        if bucket == "auto":
            bucket = "day" if span_days <= 45 else "week" if span_days <= 400 else "month"

        def _key(ts: float) -> str:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            if bucket == "day":
                return dt.strftime("%Y-%m-%d")
            if bucket == "week":
                iso = dt.isocalendar()
                return f"{iso.year}-W{iso.week:02d}"
            return dt.strftime("%Y-%m")

        buckets: dict[str, dict] = {}
        for c in comments:
            s = stored.get(c["reddit_id"])
            if s is not None:
                lbl = s.get("label") or sentiment.sentiment_label(s.get("compound", 0.0))
                compound = s.get("compound", 0.0)
            else:
                compound = sentiment.vader_compound(c["body"])
                lbl = sentiment.sentiment_label(compound)

            key = _key(c["created_utc"])
            b = buckets.setdefault(key, {
                "period": key, "first_ts": c["created_utc"],
                "positive": 0, "neutral": 0, "negative": 0,
                "count": 0, "compound_sum": 0.0,
            })
            b[lbl] = b.get(lbl, 0) + 1
            b["count"] += 1
            b["compound_sum"] += compound
            b["first_ts"] = min(b["first_ts"], c["created_utc"])

        points = []
        for b in sorted(buckets.values(), key=lambda x: x["first_ts"]):
            n = b["count"]
            points.append({
                "period": b["period"],
                "date": datetime.fromtimestamp(
                    b["first_ts"], tz=timezone.utc).strftime("%Y-%m-%d"),
                "count": n,
                "positive": b["positive"],
                "neutral": b["neutral"],
                "negative": b["negative"],
                "pct_positive": round(100 * b["positive"] / n, 1),
                "pct_negative": round(100 * b["negative"] / n, 1),
                "pct_neutral": round(100 * b["neutral"] / n, 1),
                "avg_compound": round(b["compound_sum"] / n, 3),
                "sparse": n < min_comments,
            })

        return {
            "bucket": bucket,
            "source": source,
            "points": points,
            "total": len(comments),
            "min_comments": min_comments,
            "date_range": [
                datetime.fromtimestamp(min(times), tz=timezone.utc).strftime("%Y-%m-%d"),
                datetime.fromtimestamp(max(times), tz=timezone.utc).strftime("%Y-%m-%d"),
            ],
        }


def label_comment(topic: str, comment_id: int, label: str | None) -> None:
    """Set or clear the manual ground-truth label for a comment."""
    if label is not None and label not in ("positive", "negative", "neutral"):
        raise ValueError(
            f"Invalid label '{label}'. Must be positive, negative, neutral, or None.")
    with session() as conn:
        repo.set_comment_label(conn, comment_id, label)


def get_comments_for_labeling(
    topic: str,
    unlabeled_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        comments = repo.get_comments_for_labeling(
            conn, topic_row["id"], unlabeled_only=unlabeled_only,
            limit=limit, offset=offset,
        )
        counts = repo.count_comments_by_label(conn, topic_row["id"])
        return {"comments": comments, "counts": counts}


def evaluate_sentiment(topic: str, model: str = "vader") -> dict:
    """Compare model sentiment predictions against manual GT labels."""
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        labeled = repo.get_labeled_comments(conn, topic_row["id"])
    if not labeled:
        raise NoCommentsError(
            "No manually labeled comments found. Label some comments first.")

    gt = [c["manual_label"] for c in labeled]
    preds = evaluation.predict([c["body"] for c in labeled], model)
    return evaluation.compute_metrics(gt, preds, model)
