"""Domain exceptions shared across the package."""


class RedditPulseError(Exception):
    """Base class for all RedditPulse domain errors."""


class TopicNotFoundError(RedditPulseError):
    pass


class NoCommentsError(RedditPulseError):
    pass


class NoAnalysisError(RedditPulseError):
    pass


class FetchError(RedditPulseError):
    """A fetcher failed in a way the user should see (rate limit, blocked, ...)."""
