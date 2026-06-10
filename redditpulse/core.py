"""Shared service layer — pure business logic used by both CLI and GUI."""

import json

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from . import db, fetcher, fetcher_public, fetcher_arctic, analyzer, relevance

vader = SentimentIntensityAnalyzer()


class TopicNotFoundError(Exception):
    pass


class NoCommentsError(Exception):
    pass


class NoAnalysisError(Exception):
    pass


class DuplicateTopicError(Exception):
    pass


def search_topic(
    topic: str,
    subreddits: list[str] | None = None,
    limit: int = 30,
    time_filter: str = "month",
    public: bool = False,
    refresh: bool = False,
    reset_comments: bool = False,
    keep_analyses: bool = False,
    min_relevance: float | None = None,
) -> dict:
    """Fetch Reddit comments for a topic. Returns status info dict."""
    conn = db.get_connection()
    db.init_db(conn)

    topic_row = db.get_topic(conn, topic)

    if topic_row and reset_comments:
        conn.execute("DELETE FROM comments WHERE topic_id = ?", (topic_row["id"],))
        conn.commit()
        if not keep_analyses:
            db.delete_analyses(conn, topic_row["id"])
        status = "reset"
    elif topic_row and not refresh:
        count = _count_comments(conn, topic_row["id"])
        return {
            "status": "exists",
            "keywords": topic_row["keywords"].split(","),
            "new_comments": 0,
            "total_comments": count,
        }
    else:
        status = "refresh" if topic_row else "new"

    # Generate or reuse keywords
    if not topic_row:
        keywords = analyzer.generate_keywords(topic)
        topic_id = db.create_topic(conn, topic, keywords)
    else:
        topic_id = topic_row["id"]
        keywords = topic_row["keywords"].split(",")

    # Fetch comments
    if public:
        comments = fetcher_arctic.search_comments(
            keywords,
            subreddits=subreddits,
            limit_per_keyword=min(limit, 100),
            time_filter=time_filter,
        )
    else:
        reddit = fetcher.get_reddit()
        comments = fetcher.search_comments(
            reddit,
            keywords,
            subreddits=subreddits,
            limit_per_keyword=limit,
            time_filter=time_filter,
        )

    # Optional semantic relevance filtering
    pre_filter_count = len(comments)
    if min_relevance is not None and comments:
        comments = relevance.filter_by_relevance(topic, comments, threshold=min_relevance)

    inserted = db.insert_comments(conn, topic_id, comments)
    total = _count_comments(conn, topic_id)

    result = {
        "status": status,
        "keywords": keywords,
        "fetched": pre_filter_count,
        "new_comments": inserted,
        "total_comments": total,
    }
    if min_relevance is not None:
        result["filtered_out"] = pre_filter_count - len(comments)
    return result


def duplicate_topic(source_topic: str, new_name: str) -> dict:
    """Create a new topic that reuses an existing topic's keywords.

    Lets you fetch a fresh "version" of a topic (new comments, new analyses)
    under a different name, while leaving the original topic untouched.
    Use search_topic(new_name, refresh=True) afterwards to fetch comments.
    """
    conn = db.get_connection()
    db.init_db(conn)

    source = db.get_topic(conn, source_topic)
    if not source:
        raise TopicNotFoundError(f"Topic '{source_topic}' not found.")

    new_name = new_name.strip()
    if db.get_topic(conn, new_name):
        raise DuplicateTopicError(f"Topic '{new_name}' already exists.")

    keywords = source["keywords"].split(",")
    db.create_topic(conn, new_name, keywords)
    return {"name": new_name, "keywords": keywords}


def analyze_topic(
    topic: str,
    limit: int = 500,
    sentiment_only: bool = False,
    reset_analyses: bool = False,
    sentiment_model: str = "vader",
) -> dict:
    """Run sentiment + optional theme analysis. Returns full result dict."""
    conn = db.get_connection()
    db.init_db(conn)

    topic_row = db.get_topic(conn, topic)
    if not topic_row:
        raise TopicNotFoundError(f"Topic '{topic}' not found. Run 'search' first.")

    if reset_analyses:
        db.delete_analyses(conn, topic_row["id"])

    comments = db.get_comments_for_topic(conn, topic_row["id"], limit=limit)
    if not comments:
        raise NoCommentsError(f"No comments found for '{topic}'.")

    result = analyzer.run_full_analysis(topic, comments, skip_claude=sentiment_only,
                                        sentiment_model=sentiment_model)

    db.save_analysis(
        conn,
        topic_row["id"],
        num_comments=len(comments),
        sentiment_summary=json.dumps(result["sentiment"]),
        themes=json.dumps(result["themes"]),
        raw_result=json.dumps(result),
    )

    return result


def delete_topic(topic: str) -> None:
    """Delete a topic and all its comments and analyses."""
    conn = db.get_connection()
    db.init_db(conn)

    topic_row = db.get_topic(conn, topic)
    if not topic_row:
        raise TopicNotFoundError(f"Topic '{topic}' not found.")

    db.delete_topic(conn, topic_row["id"])


def list_topics() -> list[dict]:
    """Return all topics with comment counts."""
    conn = db.get_connection()
    db.init_db(conn)

    topics = db.get_all_topics(conn)
    result = []
    for t in topics:
        count = _count_comments(conn, t["id"])
        result.append({
            "name": t["name"],
            "keywords": t["keywords"],
            "comment_count": count,
            "created_at": t["created_at"],
        })
    return result


def browse_comments(
    topic: str,
    sentiment: str = "negative",
    limit: int = 20,
) -> dict:
    """Return comments filtered by sentiment label."""
    conn = db.get_connection()
    db.init_db(conn)

    topic_row = db.get_topic(conn, topic)
    if not topic_row:
        raise TopicNotFoundError(f"Topic '{topic}' not found.")

    comments = db.get_comments_for_topic(conn, topic_row["id"], limit=2000)

    filtered = []
    for c in comments:
        compound = vader.polarity_scores(c["body"])["compound"]
        lbl = _sentiment_label(compound)
        if lbl == sentiment:
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

    return {"sentiment": sentiment, "comments": filtered, "total": len(filtered)}


def label_comment(topic: str, comment_id: int, label: str | None) -> None:
    """Set or clear the manual label for a comment. label must be positive/negative/neutral or None."""
    if label is not None and label not in ("positive", "negative", "neutral"):
        raise ValueError(f"Invalid label '{label}'. Must be positive, negative, neutral, or None.")
    conn = db.get_connection()
    db.init_db(conn)
    db.set_comment_label(conn, comment_id, label)


def get_comments_for_labeling(
    topic: str,
    unlabeled_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    conn = db.get_connection()
    db.init_db(conn)
    topic_row = db.get_topic(conn, topic)
    if not topic_row:
        raise TopicNotFoundError(f"Topic '{topic}' not found.")
    comments = db.get_comments_for_labeling(
        conn, topic_row["id"], unlabeled_only=unlabeled_only, limit=limit, offset=offset
    )
    counts = db.count_comments_by_label(conn, topic_row["id"])
    return {"comments": comments, "counts": counts}


def evaluate_sentiment(topic: str, model: str = "vader") -> dict:
    """Compare model sentiment predictions against manual GT labels.

    Returns accuracy, per-class precision/recall/F1, and a confusion matrix.
    """
    conn = db.get_connection()
    db.init_db(conn)
    topic_row = db.get_topic(conn, topic)
    if not topic_row:
        raise TopicNotFoundError(f"Topic '{topic}' not found.")

    labeled = db.get_labeled_comments(conn, topic_row["id"])
    if not labeled:
        raise NoCommentsError("No manually labeled comments found. Label some comments first.")

    gt = [c["manual_label"] for c in labeled]
    texts = [c["body"] for c in labeled]

    if model == "vader":
        preds = [_sentiment_label(vader.polarity_scores(t)["compound"]) for t in texts]
    elif model == "textblob":
        try:
            from textblob import TextBlob
        except ImportError:
            raise ImportError("textblob is not installed. Run: pip install textblob")
        preds = []
        for t in texts:
            pol = TextBlob(t).sentiment.polarity
            if pol >= 0.05:
                preds.append("positive")
            elif pol <= -0.05:
                preds.append("negative")
            else:
                preds.append("neutral")
    elif model == "claude":
        preds = analyzer.classify_sentiment_batch(texts)
    else:
        raise ValueError(f"Unknown model '{model}'. Supported: vader, textblob, claude")

    labels_order = ["positive", "neutral", "negative"]
    correct = sum(g == p for g, p in zip(gt, preds))
    accuracy = correct / len(gt)

    # Per-class metrics
    per_class = {}
    for lbl in labels_order:
        tp = sum(g == lbl and p == lbl for g, p in zip(gt, preds))
        fp = sum(g != lbl and p == lbl for g, p in zip(gt, preds))
        fn = sum(g == lbl and p != lbl for g, p in zip(gt, preds))
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_class[lbl] = {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3), "support": gt.count(lbl)}

    # Confusion matrix: rows = GT, cols = predicted
    matrix = {g: {p: 0 for p in labels_order} for g in labels_order}
    for g, p in zip(gt, preds):
        matrix[g][p] += 1

    return {
        "model": model,
        "total_labeled": len(gt),
        "accuracy": round(accuracy, 4),
        "per_class": per_class,
        "confusion_matrix": matrix,
        "labels_order": labels_order,
    }


def export_analysis(topic: str) -> dict:
    """Return the latest saved analysis for a topic."""
    conn = db.get_connection()
    db.init_db(conn)

    topic_row = db.get_topic(conn, topic)
    if not topic_row:
        raise TopicNotFoundError(f"Topic '{topic}' not found.")

    analysis = db.get_latest_analysis(conn, topic_row["id"])
    if not analysis:
        raise NoAnalysisError(f"No analysis found for '{topic}'. Run 'analyze' first.")

    return {
        "result": json.loads(analysis["raw_result"]),
        "run_at": analysis["run_at"],
    }


def get_topic_summary(topic: str) -> dict:
    """Return topic info, comment count, and latest analysis summary."""
    conn = db.get_connection()
    db.init_db(conn)

    topic_row = db.get_topic(conn, topic)
    if not topic_row:
        raise TopicNotFoundError(f"Topic '{topic}' not found.")

    count = _count_comments(conn, topic_row["id"])
    analysis = db.get_latest_analysis(conn, topic_row["id"])

    summary = {
        "name": topic_row["name"],
        "keywords": topic_row["keywords"],
        "comment_count": count,
        "created_at": topic_row["created_at"],
        "latest_analysis": None,
    }

    if analysis:
        summary["latest_analysis"] = {
            "run_at": analysis["run_at"],
            "num_comments": analysis["num_comments"],
            "sentiment": json.loads(analysis["sentiment_summary"]) if analysis["sentiment_summary"] else None,
            "themes": json.loads(analysis["themes"]) if analysis["themes"] else None,
        }

    return summary


def _count_comments(conn, topic_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM comments WHERE topic_id = ?", (topic_id,)
    ).fetchone()
    return row["cnt"]


def _sentiment_label(compound: float) -> str:
    if compound >= 0.05:
        return "positive"
    elif compound <= -0.05:
        return "negative"
    return "neutral"
