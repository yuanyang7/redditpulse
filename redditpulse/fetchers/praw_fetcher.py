"""Fetch Reddit comments live via PRAW (requires Reddit API credentials)."""

import time as _time
from typing import Callable

import praw

from ..config import get_settings
from .base import TimeRange, is_valid_comment, keyword_words, \
    mentions_any_keyword, normalize_comment

# Reddit's search API only accepts these relative filters; arbitrary ranges
# are emulated by searching the narrowest covering filter and dropping
# comments outside the requested range afterwards.
_REDDIT_FILTERS = [
    ("hour", 3600),
    ("day", 86400),
    ("week", 7 * 86400),
    ("month", 31 * 86400),
    ("year", 366 * 86400),
    ("all", None),
]


def get_reddit() -> praw.Reddit:
    settings = get_settings()
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        raise RuntimeError(
            "Reddit credentials missing. Set REDDIT_CLIENT_ID and "
            "REDDIT_CLIENT_SECRET in .env, or use the Arctic Shift source."
        )
    return praw.Reddit(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )


def _covering_filter(time_range: TimeRange) -> str:
    """Smallest Reddit time_filter that covers the requested range."""
    if time_range.after_utc is None:
        return "all"
    lookback = _time.time() - time_range.after_utc
    for name, seconds in _REDDIT_FILTERS:
        if seconds is not None and lookback <= seconds:
            return name
    return "all"


def search_comments(
    keywords: list[str],
    subreddits: list[str] | None = None,
    limit_per_keyword: int = 50,
    time_range: TimeRange | None = None,
    sort: str = "relevance",
    progress_callback: Callable[[int, int, str], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
    on_truncated: Callable[[str], None] | None = None,
    on_skipped: Callable[[str], None] | None = None,
    reddit: praw.Reddit | None = None,
) -> list[dict]:
    """Search Reddit for submissions matching keywords, then collect their comments."""
    reddit = reddit or get_reddit()
    time_range = time_range or TimeRange()
    target = "+".join(s.strip() for s in subreddits if s.strip()) if subreddits else "all"
    subreddit = reddit.subreddit(target)
    search_filter = _covering_filter(time_range)

    seen_ids: set[str] = set()
    comments: list[dict] = []
    words = keyword_words(keywords)

    for i, keyword in enumerate(keywords):
        if stop_check and stop_check():
            if progress_callback:
                progress_callback(i, len(keywords), "Stopped")
            if on_skipped:
                for kw in keywords[i:]:
                    on_skipped(kw)
            return comments
        if progress_callback:
            progress_callback(i, len(keywords), f"\"{keyword}\"")
        num_submissions = 0
        for submission in subreddit.search(keyword, sort=sort,
                                           time_filter=search_filter,
                                           limit=limit_per_keyword):
            num_submissions += 1
            submission.comments.replace_more(limit=0)  # skip "load more" stubs
            for comment in submission.comments.list():
                if comment.id in seen_ids:
                    continue
                if not time_range.contains(comment.created_utc):
                    continue
                author = str(comment.author) if comment.author else None
                if not is_valid_comment(comment.id, comment.body, author):
                    continue
                if not mentions_any_keyword(comment.body, words):
                    continue
                seen_ids.add(comment.id)
                comments.append(normalize_comment(
                    reddit_id=comment.id,
                    subreddit=str(comment.subreddit),
                    author=author,
                    body=comment.body,
                    score=comment.score,
                    controversiality=getattr(comment, "controversiality", None),
                    permalink=f"https://reddit.com{comment.permalink}",
                    created_utc=comment.created_utc,
                ))

        if num_submissions >= limit_per_keyword and on_truncated:
            on_truncated(target)

    if progress_callback:
        progress_callback(len(keywords), len(keywords), "Done")

    return comments
