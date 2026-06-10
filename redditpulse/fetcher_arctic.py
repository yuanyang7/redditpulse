"""Fetch Reddit comments via the Arctic Shift archive — no credentials required.

Arctic Shift (https://arctic-shift.photon-reddit.com) is a free, actively
maintained Pushshift successor that archives Reddit posts/comments and exposes
a search API. Unlike Reddit's anonymous endpoints it isn't aggressively rate
limited, and unlike PullPush its data stays current (within ~hours).

Limitation: comment keyword (`body`) search must be scoped to a subreddit, so
this fetcher searches a list of subreddits rather than all of Reddit. When the
caller passes no subreddits, DEFAULT_SUBREDDITS is used.
"""

import time
from datetime import datetime, timezone, timedelta

import requests

BASE = "https://arctic-shift.photon-reddit.com"
HEADERS = {"User-Agent": "redditpulse/0.1 (personal research tool)"}

# Used when the caller doesn't specify subreddits — broad, discussion-heavy
# subreddits where most topics get talked about. Kept short because each
# subreddit x keyword pair is a separate (expensive) full-text search.
DEFAULT_SUBREDDITS = [
    "technology", "privacy", "artificial", "Futurology", "AskReddit",
]

# Map the GUI's time_filter values to a lookback window for the `after` param.
_WINDOWS = {
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
    "all": None,
}


def search_comments(
    keywords: list[str],
    subreddits: list[str] | None = None,
    limit_per_keyword: int = 25,
    time_filter: str = "month",
) -> list[dict]:
    """Search Arctic Shift for comments matching keywords across subreddits.

    For each subreddit x keyword pair, runs a body keyword search. Results are
    deduplicated by comment id.
    """
    targets = [s.strip() for s in (subreddits or DEFAULT_SUBREDDITS) if s.strip()]
    after = _after_param(time_filter)

    seen_ids: set[str] = set()
    comments: list[dict] = []
    queries = 0
    timed_out = 0

    for keyword in keywords:
        for subreddit in targets:
            queries += 1
            result = _search(subreddit, keyword, limit_per_keyword, after)
            if result is None:  # query gave up after repeated timeouts
                timed_out += 1
                continue
            for raw in result:
                cid = raw.get("id")
                body = (raw.get("body") or "").strip()
                if not cid or cid in seen_ids:
                    continue
                if not body or body in ("[deleted]", "[removed]"):
                    continue
                if raw.get("author") == "AutoModerator":
                    continue
                seen_ids.add(cid)
                sr = raw.get("subreddit", subreddit)
                comments.append({
                    "reddit_id": cid,
                    "subreddit": sr,
                    "author": raw.get("author") or "[deleted]",
                    "body": body,
                    "score": raw.get("score", 0) or 0,
                    "permalink": _permalink(sr, raw.get("link_id"), cid),
                    "created_utc": raw.get("created_utc", 0) or 0,
                })

    # If every query timed out, the archive is overloaded — say so instead of
    # silently returning nothing.
    if queries and timed_out == queries:
        raise RuntimeError(
            "Arctic Shift timed out on every query — its server is likely "
            "overloaded right now. Wait a minute and try again, or use fewer "
            "subreddits / a narrower time range."
        )

    return comments


def _search(subreddit: str, keyword: str, limit: int, after: str | None,
            max_retries: int = 3) -> list[dict] | None:
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
        # (permalink isn't a selectable field, so we rebuild it from link_id.)
        "fields": "id,author,body,score,subreddit,created_utc,link_id",
    }
    if after:
        params["after"] = after

    delay = 2.0
    for attempt in range(max_retries):
        try:
            resp = requests.get(f"{BASE}/api/comments/search", headers=HEADERS,
                                params=params, timeout=30)
        except requests.Timeout:
            # Server took too long on this body search — transient, retry/skip.
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            return None
        except requests.RequestException as e:
            raise RuntimeError(f"Arctic Shift request failed: {e}") from e

        if resp.status_code == 200:
            time.sleep(1.0)  # be polite between successful calls
            return resp.json().get("data", [])

        # 422/429 with a "Timeout"/"slow down" message is transient — back off.
        msg = ""
        try:
            msg = (resp.json() or {}).get("error", "")
        except ValueError:
            msg = resp.text[:120]
        transient = resp.status_code in (422, 429) and (
            "timeout" in msg.lower() or "slow down" in msg.lower()
        )
        if transient and attempt < max_retries - 1:
            time.sleep(delay)
            delay *= 2
            continue
        if transient:
            return None  # gave up on this query after repeated timeouts

        resp.raise_for_status()
        return resp.json().get("data", [])
    return []


def _permalink(subreddit: str, link_id: str | None, comment_id: str) -> str:
    """Reconstruct a comment permalink from its subreddit, post id and own id."""
    post_id = (link_id or "").removeprefix("t3_")
    if subreddit and post_id:
        return f"https://reddit.com/r/{subreddit}/comments/{post_id}/_/{comment_id}/"
    return f"https://reddit.com/comments/{comment_id}"


def _after_param(time_filter: str) -> str | None:
    """Convert a GUI time_filter into an ISO date for the `after` query param."""
    window = _WINDOWS.get(time_filter, _WINDOWS["month"])
    if window is None:  # "all"
        return None
    return (datetime.now(timezone.utc) - window).strftime("%Y-%m-%d")
