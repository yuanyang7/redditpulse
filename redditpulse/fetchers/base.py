"""Shared fetcher utilities: time ranges, normalization, validation."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Relative lookback windows offered in the UI/CLI. "all" means unbounded.
TIME_FILTER_WINDOWS: dict[str, timedelta | None] = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "6months": timedelta(days=182),
    "year": timedelta(days=365),
    "all": None,
}

TIME_FILTERS = list(TIME_FILTER_WINDOWS)


@dataclass(frozen=True)
class TimeRange:
    """An absolute [after, before] window in epoch seconds (either side open)."""

    after_utc: float | None = None
    before_utc: float | None = None

    @classmethod
    def from_filter(cls, time_filter: str) -> "TimeRange":
        """Build a range from a relative lookback like "month" or "6months"."""
        window = TIME_FILTER_WINDOWS.get(time_filter, TIME_FILTER_WINDOWS["month"])
        if window is None:
            return cls()
        return cls(after_utc=(datetime.now(timezone.utc) - window).timestamp())

    @classmethod
    def from_dates(cls, after: str | None, before: str | None) -> "TimeRange":
        """Build a range from ISO date strings (YYYY-MM-DD), either side optional.

        `before` is inclusive of the named day (i.e. its end of day).
        """
        def _parse(value: str, end_of_day: bool) -> float:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if end_of_day and len(value) <= 10:  # bare date, no time component
                dt = dt + timedelta(days=1)
            return dt.timestamp()

        return cls(
            after_utc=_parse(after, end_of_day=False) if after else None,
            before_utc=_parse(before, end_of_day=True) if before else None,
        )

    def contains(self, ts: float) -> bool:
        if self.after_utc is not None and ts < self.after_utc:
            return False
        if self.before_utc is not None and ts > self.before_utc:
            return False
        return True

    def after_date(self) -> str | None:
        return self._date(self.after_utc)

    def before_date(self) -> str | None:
        return self._date(self.before_utc)

    @staticmethod
    def _date(ts: float | None) -> str | None:
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def normalize_comment(
    reddit_id: str,
    subreddit: str,
    body: str,
    author: str | None = None,
    score: int = 0,
    controversiality: int | None = None,
    permalink: str = "",
    created_utc: float = 0.0,
) -> dict:
    """Build the canonical comment dict every fetcher returns."""
    return {
        "reddit_id": reddit_id,
        "subreddit": subreddit,
        "author": author or "[deleted]",
        "body": body,
        "score": score,
        "controversiality": controversiality,
        "permalink": permalink,
        "created_utc": created_utc,
    }


def is_valid_comment(reddit_id: str | None, body: str | None,
                     author: str | None) -> bool:
    """Drop deleted/removed/bot/empty comments before they enter the pipeline."""
    if not reddit_id:
        return False
    body = (body or "").strip()
    if not body or body in ("[deleted]", "[removed]"):
        return False
    if author == "AutoModerator":
        return False
    return True


def keyword_words(keywords: list[str]) -> set[str]:
    """Significant lowercase words across all keywords, for relevance checks."""
    stopwords = {"the", "a", "an", "and", "or", "of", "in", "on", "is", "it",
                 "to", "for", "with", "about", "vs", "how", "what", "why"}
    words: set[str] = set()
    for kw in keywords:
        for w in kw.lower().split():
            w = w.strip(".,!?\"'()")
            if w not in stopwords and len(w) > 2:
                words.add(w)
    return words


def mentions_any_keyword(body: str, words: set[str]) -> bool:
    """Cheap textual relevance check: the comment mentions at least one keyword word."""
    if not words:
        return True
    body_lower = body.lower()
    return any(w in body_lower for w in words)
