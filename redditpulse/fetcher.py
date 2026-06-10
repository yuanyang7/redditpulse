"""Fetch Reddit comments using PRAW based on keywords."""

import os
import time as _time
import praw
from dotenv import load_dotenv

load_dotenv()

# Reddit's search API only accepts hour/day/week/month/year/all. "6months" is a
# synthetic window: fetch with "year" and drop comments older than this cutoff.
_SIX_MONTHS_SECONDS = 182 * 24 * 60 * 60


def get_reddit() -> praw.Reddit:
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "redditpulse/0.1"),
    )


def search_comments(
    reddit: praw.Reddit,
    keywords: list[str],
    subreddits: list[str] | None = None,
    limit_per_keyword: int = 50,
    sort: str = "relevance",
    time_filter: str = "month",
) -> list[dict]:
    """Search Reddit for submissions matching keywords, then collect their comments.

    Args:
        reddit: PRAW Reddit instance.
        keywords: List of search terms.
        subreddits: Optional list of subreddits to search within. Defaults to "all".
        limit_per_keyword: Max submissions to fetch per keyword.
        sort: Sort order for search (relevance, hot, top, new, comments).
        time_filter: Time filter (hour, day, week, month, 6months, year, all).

    Returns:
        List of comment dicts ready for db.insert_comments().
    """
    target = "+".join(subreddits) if subreddits else "all"
    subreddit = reddit.subreddit(target)

    # "6months" isn't a real Reddit time_filter — search with "year" and apply a
    # timestamp cutoff to the resulting comments below.
    if time_filter == "6months":
        search_filter = "year"
        min_created = _time.time() - _SIX_MONTHS_SECONDS
    else:
        search_filter = time_filter
        min_created = None

    seen_ids: set[str] = set()
    comments: list[dict] = []
    topic_words, context_words = _extract_word_groups(keywords)

    for keyword in keywords:
        for submission in subreddit.search(keyword, sort=sort, time_filter=search_filter, limit=limit_per_keyword):
            submission.comments.replace_more(limit=0)  # skip "load more" stubs
            for comment in submission.comments.list():
                if comment.id in seen_ids:
                    continue

                if min_created is not None and comment.created_utc < min_created:
                    continue

                # Require both a topic word AND a context word for relevance
                body_lower = comment.body.lower()
                has_topic = any(w in body_lower for w in topic_words)
                has_context = any(w in body_lower for w in context_words)
                if not (has_topic and has_context):
                    continue

                seen_ids.add(comment.id)

                comments.append({
                    "reddit_id": comment.id,
                    "subreddit": str(comment.subreddit),
                    "author": str(comment.author) if comment.author else "[deleted]",
                    "body": comment.body,
                    "score": comment.score,
                    "permalink": f"https://reddit.com{comment.permalink}",
                    "created_utc": comment.created_utc,
                })

    return comments


def _extract_word_groups(keywords: list[str]) -> tuple[set[str], set[str]]:
    """Split keywords into topic words and context words for AND-style filtering.

    A comment must contain at least one word from each group to be relevant.
    """
    topic_words = {"ai", "artificial", "intelligence", "machine", "learning", "algorithm",
                   "facial", "recognition", "model", "llm", "chatgpt", "deepfake", "neural"}
    context_words = {"privacy", "surveillance", "data", "personal", "rights", "ethics",
                     "consent", "tracking", "collection", "security", "breach", "biometric"}

    stopwords = {"the", "a", "an", "and", "or", "of", "in", "on", "is", "it", "to", "for", "with", "about"}
    for kw in keywords:
        words = [w.lower() for w in kw.split() if w.lower() not in stopwords and len(w) > 2]
        if words:
            topic_words.add(words[0])
            context_words.update(words[1:])

    return topic_words, context_words
