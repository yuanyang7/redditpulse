"""Fetch Reddit comments via public RSS feeds — no credentials required.

Reddit blocked anonymous access to its `.json` endpoints (HTTP 403) in 2025.
The `.rss` (Atom) feeds remain publicly accessible for now and are used here
as a last-resort fallback. RSS feeds do NOT expose comment scores, so `score`
defaults to 0 in this path, and the anonymous quota is tiny, so totals are
deliberately capped.
"""

import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Callable

import requests

from ..exceptions import FetchError
from .base import TimeRange, is_valid_comment, keyword_words, \
    mentions_any_keyword, normalize_comment

# A browser-like User-Agent is required; Reddit blocks generic/bot agents.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
BASE = "https://www.reddit.com"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# If Reddit says the rate-limit window resets in <= this many seconds, we wait
# it out inline; longer than this we fail fast so the user isn't stuck staring
# at a frozen spinner for minutes.
MAX_INLINE_WAIT = 30.0

# Anonymous RSS quota is only a few dozen requests per ~10-minute window, so
# keep total requests small: at most a few keywords, a few posts each.
MAX_KEYWORDS = 3
MAX_POSTS_PER_KEYWORD = 4


def search_comments(
    keywords: list[str],
    subreddits: list[str] | None = None,
    limit_per_keyword: int = 25,
    time_range: TimeRange | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> list[dict]:
    """Search Reddit via public RSS feeds, no OAuth needed."""
    time_range = time_range or TimeRange()
    seen_ids: set[str] = set()
    comments: list[dict] = []
    words = keyword_words(keywords)
    use_keywords = keywords[:MAX_KEYWORDS]

    for i, keyword in enumerate(use_keywords):
        if stop_check and stop_check():
            break
        if progress_callback:
            progress_callback(i, len(use_keywords), f"\"{keyword}\"")
        if subreddits:
            permalinks = []
            for sr in subreddits:
                permalinks += _search_submissions(keyword, subreddit=sr,
                                                  limit=limit_per_keyword)
        else:
            permalinks = _search_submissions(keyword, subreddit=None,
                                             limit=limit_per_keyword)

        for permalink in permalinks[:MAX_POSTS_PER_KEYWORD]:
            for c in _fetch_comments(permalink):
                if c["reddit_id"] in seen_ids:
                    continue
                if not time_range.contains(c["created_utc"]):
                    continue
                if not mentions_any_keyword(c["body"], words):
                    continue
                seen_ids.add(c["reddit_id"])
                comments.append(c)
            time.sleep(0.5)  # be polite to Reddit's servers

    if progress_callback:
        progress_callback(len(use_keywords), len(use_keywords), "Done")

    return comments


def _retry_after_seconds(resp: requests.Response) -> float | None:
    """Seconds to wait before retrying a 429, from Reddit's rate-limit headers."""
    retry_after = resp.headers.get("Retry-After")
    if retry_after and retry_after.replace(".", "", 1).isdigit():
        return float(retry_after)
    reset = resp.headers.get("x-ratelimit-reset")
    if reset and reset.replace(".", "", 1).isdigit():
        return float(reset)
    return None


def _get(url: str, params: dict, max_retries: int = 4) -> requests.Response:
    """GET a Reddit RSS URL, retrying 429s with backoff.

    429 (Too Many Requests) is transient: we honor Reddit's rate-limit reset
    header and wait it out if it's short, otherwise fail fast with the exact
    wait time. 401/403 are hard blocks and raise immediately.
    """
    delay = 3.0
    for attempt in range(max_retries):
        resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if resp.status_code == 429:
            wait = _retry_after_seconds(resp)
            if attempt < max_retries - 1 and (wait is None or wait <= MAX_INLINE_WAIT):
                time.sleep(wait if wait is not None else delay)
                delay *= 2  # exponential backoff
                continue
            secs = int(wait) if wait is not None else None
            when = f"in about {secs} seconds" if secs else "in a few minutes"
            raise FetchError(
                f"Reddit's public RSS rate limit is exhausted — try again {when}. "
                "Reduce the Limit, or provide Reddit credentials in .env."
            )
        if resp.status_code in (401, 403):
            raise FetchError(
                f"Reddit blocked the public RSS request (HTTP {resp.status_code}). "
                "Anonymous access is blocked — provide Reddit credentials in .env "
                "or use the Arctic Shift source instead."
            )
        resp.raise_for_status()
        return resp
    raise FetchError("Reddit RSS request failed after retries.")


def _search_submissions(keyword: str, subreddit: str | None, limit: int) -> list[str]:
    """Return list of submission permalinks matching keyword (via search.rss)."""
    if subreddit:
        url = f"{BASE}/r/{subreddit}/search.rss"
        params = {"q": keyword, "sort": "relevance", "t": "year",
                  "limit": min(limit, 25), "restrict_sr": 1}
    else:
        url = f"{BASE}/search.rss"
        params = {"q": keyword, "sort": "relevance", "t": "year",
                  "limit": min(limit, 25)}

    try:
        resp = _get(url, params)
        root = ET.fromstring(resp.content)
        permalinks = []
        for entry in root.findall("a:entry", ATOM_NS):
            link = entry.find("a:link", ATOM_NS)
            if link is not None and "/comments/" in link.get("href", ""):
                permalinks.append(link.get("href"))
        return permalinks
    finally:
        time.sleep(1)  # respect rate limit


def _fetch_comments(permalink: str) -> list[dict]:
    """Fetch comments for a submission via its .rss feed."""
    rss_url = permalink.split("?")[0].rstrip("/") + ".rss"
    try:
        resp = _get(rss_url, {"limit": 100})
        root = ET.fromstring(resp.content)

        sr_match = re.search(r"/r/([^/]+)/", permalink)
        subreddit = sr_match.group(1) if sr_match else "unknown"

        comments = []
        for entry in root.findall("a:entry", ATOM_NS):
            eid = (entry.findtext("a:id", default="", namespaces=ATOM_NS) or "")
            if not eid.startswith("t1_"):  # skip the t3_ submission entry
                continue
            comment_id = eid[3:]

            author_el = entry.find("a:author/a:name", ATOM_NS)
            author = author_el.text if author_el is not None else None
            if author and author.startswith("/u/"):
                author = author[3:]

            content = entry.findtext("a:content", default="", namespaces=ATOM_NS) or ""
            body = _html_to_text(content)
            if not is_valid_comment(comment_id, body, author):
                continue

            link_el = entry.find("a:link", ATOM_NS)
            comment_permalink = link_el.get("href") if link_el is not None else permalink

            published = entry.findtext("a:published", default="", namespaces=ATOM_NS)

            comments.append(normalize_comment(
                reddit_id=comment_id,
                subreddit=subreddit,
                author=author,
                body=body,
                score=0,  # not available via RSS
                permalink=comment_permalink,
                created_utc=_parse_ts(published),
            ))
        return comments
    except ET.ParseError:
        return []
    finally:
        time.sleep(0.5)


def _html_to_text(content: str) -> str:
    """Strip HTML tags from Reddit's RSS content field and unescape entities."""
    text = html.unescape(content)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)  # SC_OFF/SC_ON markers
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_ts(value: str) -> float:
    """Parse an ISO8601 timestamp from RSS into an epoch float."""
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc).timestamp()
