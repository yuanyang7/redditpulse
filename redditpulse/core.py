"""Shared service layer — pure business logic used by both CLI and GUI."""

import json

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from . import db, fetcher, fetcher_public, analyzer, relevance

vader = SentimentIntensityAnalyzer()


class TopicNotFoundError(Exception):
    pass


class NoCommentsError(Exception):
    pass


class NoAnalysisError(Exception):
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
        comments = fetcher_public.search_comments(
            keywords,
            subreddits=subreddits,
            limit_per_keyword=min(limit, 25),
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


def analyze_topic(
    topic: str,
    limit: int = 500,
    sentiment_only: bool = False,
    reset_analyses: bool = False,
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

    result = analyzer.run_full_analysis(topic, comments, skip_claude=sentiment_only)

    db.save_analysis(
        conn,
        topic_row["id"],
        num_comments=len(comments),
        sentiment_summary=json.dumps(result["sentiment"]),
        themes=json.dumps(result["themes"]),
        raw_result=json.dumps(result),
    )

    return result


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
