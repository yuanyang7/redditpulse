"""Topic management: listing, summaries, notes, naming, showcase config."""

import json
import re

from ..exceptions import TopicNotFoundError
from ..storage import repo
from ..storage.db import session


def generate_keywords(topic: str) -> list[str]:
    """Generate suggested Reddit search keywords (for review before fetching)."""
    from ..analysis import llm
    return llm.generate_keywords(topic)


def generate_subreddits(topic: str) -> list[str]:
    """Generate suggested subreddits to search (for review before fetching)."""
    from ..analysis import llm
    return llm.generate_subreddits(topic)


def _require_topic(conn, topic: str) -> dict:
    row = repo.get_topic(conn, topic)
    if not row:
        raise TopicNotFoundError(f"Topic '{topic}' not found. Run 'search' first.")
    return row


def list_topics() -> list[dict]:
    """Return all topics with comment counts."""
    with session() as conn:
        topics = repo.get_all_topics(conn)
        return [{
            "name": t["name"],
            "keywords": t["keywords"],
            "comment_count": repo.count_comments(conn, t["id"]),
            "created_at": t["created_at"],
            "note": t["note"] or "",
        } for t in topics]


def get_topic_summary(topic: str) -> dict:
    """Return topic info, comment count, and latest analysis summary."""
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        count = repo.count_comments(conn, topic_row["id"])
        analysis = repo.get_latest_analysis(conn, topic_row["id"])

        summary = {
            "name": topic_row["name"],
            "keywords": topic_row["keywords"],
            "comment_count": count,
            "created_at": topic_row["created_at"],
            "note": topic_row["note"] or "",
            "latest_analysis": None,
        }
        if analysis:
            summary["latest_analysis"] = {
                "run_at": analysis["run_at"],
                "num_comments": analysis["num_comments"],
                "sentiment": json.loads(analysis["sentiment_summary"])
                if analysis["sentiment_summary"] else None,
                "themes": json.loads(analysis["themes"]) if analysis["themes"] else None,
            }
        return summary


def set_topic_note(topic: str, note: str) -> None:
    """Set or clear the freeform note for a topic."""
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        repo.set_topic_note(conn, topic_row["id"], note.strip() or None)


def delete_topic(topic: str) -> None:
    """Delete a topic and all its comments, runs and analyses."""
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        repo.delete_topic(conn, topic_row["id"])


def get_showcase_config(topic: str) -> dict | None:
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        return repo.get_showcase_config(conn, topic_row["id"])


def set_showcase_config(topic: str, config: dict | None) -> None:
    with session() as conn:
        topic_row = _require_topic(conn, topic)
        repo.set_showcase_config(conn, topic_row["id"], config)


def next_available_topic_name(name: str, existing_names: list[str]) -> str:
    """If `name` is already taken, return a "<base> v{n}" variant that isn't.

    Strips any existing " vN" suffix to find the base name, then picks the
    next unused version number across all existing "<base> vN" names.
    """
    name = name.strip()
    if name not in existing_names:
        return name

    match = re.match(r"^(.*) v(\d+)$", name)
    base = match.group(1) if match else name

    max_version = 1
    pattern = re.compile(rf"^{re.escape(base)} v(\d+)$")
    for existing in existing_names:
        m = pattern.match(existing)
        if m:
            max_version = max(max_version, int(m.group(1)))

    return f"{base} v{max_version + 1}"
