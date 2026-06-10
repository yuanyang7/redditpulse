"""Deprecated compatibility facade over the services layer.

Kept only so older entry points (the pre-refactor GUI) keep working; new code
should import from ``redditpulse.services`` directly.
"""

from .exceptions import (  # noqa: F401
    NoAnalysisError, NoCommentsError, TopicNotFoundError,
)
from .services import (  # noqa: F401
    analyze_topic, delete_topic, evaluate_sentiment, export_analysis,
    generate_keywords, generate_subreddits, get_comments_for_labeling,
    get_sentiment_trends, get_topic_summary, label_comment, list_topics,
    next_available_topic_name, set_topic_note,
)
from .services import browse_comments as _browse_comments
from .services import search_topic as _search_topic


def search_topic(*args, public: bool = False, **kwargs):
    """Old signature used `public=True` for the credential-free source."""
    kwargs["source"] = "arctic" if public else "praw"
    return _search_topic(*args, **kwargs)


def browse_comments(topic: str, sentiment: str = "negative", limit: int = 20):
    return _browse_comments(topic, sentiment_filter=sentiment, limit=limit)
