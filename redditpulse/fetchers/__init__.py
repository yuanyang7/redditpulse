"""Comment fetchers for the different Reddit data sources.

Each fetcher module exposes::

    search_comments(keywords, subreddits=None, limit_per_keyword=...,
                    time_range=TimeRange(...), progress_callback=None,
                    stop_check=None) -> list[dict]

returning normalized comment dicts (see ``base.normalize_comment``).
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
