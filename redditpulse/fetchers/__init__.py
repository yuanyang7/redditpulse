"""Comment fetchers for the different Reddit data sources.

Each fetcher module exposes::

    search_comments(keywords, subreddits=None, limit_per_keyword=...,
                    time_range=TimeRange(...), progress_callback=None,
                    stop_check=None, on_truncated=None,
                    on_skipped=None) -> list[dict]

returning normalized comment dicts (see ``base.normalize_comment``).

``on_truncated``, if given, is called with a subreddit name (or other
descriptive label) each time a query hits its result cap — i.e. more
matching data exists than was fetched for that pair.

``on_skipped``, if given, is called with a keyword for each keyword that
got no results (or incomplete results) because `stop_check` returned true
before it could be fully processed.
"""

from .base import TimeRange  # noqa: F401
from . import arctic, praw_fetcher, rss

SOURCES = {
    "arctic": arctic,
    "praw": praw_fetcher,
    "rss": rss,
}


def get_fetcher(source: str):
    """Return the fetcher module for a source name."""
    try:
        return SOURCES[source]
    except KeyError:
        raise ValueError(f"Unknown fetch source '{source}'. "
                         f"Available: {', '.join(SOURCES)}") from None
