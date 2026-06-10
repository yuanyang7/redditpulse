"""Fetch Reddit comments via the Arctic Shift archive — no credentials required.

Arctic Shift (https://arctic-shift.photon-reddit.com) is a free, actively
maintained Pushshift successor that archives Reddit posts/comments and exposes
a search API. Unlike Reddit's anonymous endpoints it isn't aggressively rate
limited, and its data stays current (within ~hours).

Limitation: comment keyword (`body`) search must be scoped to a subreddit, so
this fetcher searches a list of subreddits rather than all of Reddit. When the
caller passes no subreddits, DEFAULT_SUBREDDITS is used.

Supports explicit time ranges (both `after` and `before`), so historical
windows can be queried precisely — not just "the past N days".
"""

import time
from typing import Callable

import requests

from ..exceptions import FetchError
from .base import TimeRange, is_valid_comment, normalize_comment

BASE = "https://arctic-shift.photon-reddit.com"
HEADERS = {"User-Agent": "redditpulse/0.2 (personal research tool)"}

# Used when the caller doesn't specify subreddits — broad, discussion-heavy
# subreddits where most topics get talked about. Kept short because each
# subreddit x keyword pair is a separate (expensive) full-text search.
DEFAULT_SUBREDDITS = [
    "technology", "privacy", "artificial", "Futurology", "AskReddit",
]


def search_comments(
    keywords: list[str],
    subreddits: list[str] | None = None,
    limit_per_keyword: int = 25,
    time_range: TimeRange | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> list[dict]:
    """Search Arctic Shift for comments matching keywords across subreddits.

    For each subreddit x keyword pair, runs a body keyword search. Results are
    deduplicated by comment id.

    If `progress_callback` is given, it's called before each query as
    `progress_callback(done, total, description)`. If `stop_check` is given
    and returns truthy, the search stops early and returns what it has.
    """
    targets = [s.strip() for s in (subreddits or DEFAULT_SUBREDDITS) if s.strip()]
    time_range = time_range or TimeRange()

    seen_ids: set[str] = set()
    comments: list[dict] = []
    queries = 0
    failed = 0
    total_queries = len(keywords) * len(targets)
    stopped = False

    for keyword in keywords:
        if stopped:
            break
        for subreddit in targets:
            if stop_check and stop_check():
                stopped = True
                break
            if progress_callback:
                progress_callback(queries, total_queries, f"r/{subreddit} — \"{keyword}\"")
            queries += 1
            result = _search(subreddit, keyword, limit_per_keyword, time_range)
            if result is None:  # query gave up after repeated timeouts/errors
                failed += 1
                continue
            for raw in result:
                cid = raw.get("id")
                body = (raw.get("body") or "").strip()
                if cid in seen_ids or not is_valid_comment(cid, body, raw.get("author")):
                    continue
                seen_ids.add(cid)
                sr = raw.get("subreddit", subreddit)
                comments.append(normalize_comment(
                    reddit_id=cid,
                    subreddit=sr,
                    author=raw.get("author"),
                    body=body,
                    score=raw.get("score", 0) or 0,
                    controversiality=raw.get("controversiality"),
                    permalink=_permalink(sr, raw.get("link_id"), cid),
                    created_utc=raw.get("created_utc", 0) or 0,
                ))

    if progress_callback:
        progress_callback(total_queries if not stopped else queries, total_queries,
                          "Stopped" if stopped else "Done")

    # If every query failed (timeout or server error), the archive is likely
    # overloaded — say so instead of silently returning nothing.
    if not stopped and queries and failed == queries:
        raise FetchError(
            "Arctic Shift failed on every query — its server is likely "
            "overloaded right now. Wait a minute and try again, or use fewer "
            "subreddits / a narrower time range."
        )

    return comments


def _search(subreddit: str, keyword: str, limit: int, time_range: TimeRange,
            max_retries: int = 4) -> list[dict] | None:
    """Run one comment body search.

    Returns a list of raw Arctic Shift comment dicts on success (possibly
    empty if there were no matches), or None if the query repeatedly timed out
    and was given up on. Arctic Shift intermittently times out on expensive
    body searches (as a 422 "Timeout" message or a read timeout); those are
    transient and retried with backoff.
    """
    params = {
        "subreddit": subreddit,
        "body": keyword,
        "limit": max(1, min(limit, 100)),
        "sort": "desc",
        # Request only the fields we use — Arctic Shift's docs note this can cut
        # response time/size, which helps avoid timeouts on slow comment search.
        # (permalink isn't a selectable field, so we rebuild it from link_id.
        # "controversiality" is not a selectable field on this API — Arctic
        # Shift returns 400 if it's requested, so we don't get it from this source.)
        "fields": "id,author,body,score,subreddit,created_utc,link_id",
    }
    if time_range.after_date():
        params["after"] = time_range.after_date()
    if time_range.before_date():
        params["before"] = time_range.before_date()

    delay = 3.0
    for attempt in range(max_retries):
        try:
            resp = requests.get(f"{BASE}/api/comments/search", headers=HEADERS,
                                params=params, timeout=60)
        except requests.Timeout:
            # Server took too long on this body search — transient, retry/skip.
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            return None
        except requests.RequestException as e:
            raise FetchError(f"Arctic Shift request failed: {e}") from e

        if resp.status_code == 200:
            time.sleep(1.0)  # be polite between successful calls
            return resp.json().get("data", [])

        # 422/429 with a "Timeout"/"slow down" message, or any 5xx server
        # error, is transient — back off and retry, then give up on just this
        # query rather than failing the whole run.
        try:
            msg = (resp.json() or {}).get("error", "")
        except ValueError:
            msg = resp.text[:120]
        transient = resp.status_code >= 500 or (
            resp.status_code in (422, 429) and (
                "timeout" in msg.lower() or "slow down" in msg.lower()
            )
        )
        if transient and attempt < max_retries - 1:
            time.sleep(delay)
            delay *= 2
            continue
        if transient:
            return None  # gave up on this query after repeated failures

        resp.raise_for_status()
        return resp.json().get("data", [])
    return []


def _permalink(subreddit: str, link_id: str | None, comment_id: str) -> str:
    """Reconstruct a comment permalink from its subreddit, post id and own id."""
    post_id = (link_id or "").removeprefix("t3_")
    if subreddit and post_id:
        return f"https://reddit.com/r/{subreddit}/comments/{post_id}/_/{comment_id}/"
    return f"https://reddit.com/comments/{comment_id}"
