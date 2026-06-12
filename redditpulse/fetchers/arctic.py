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

# When a (subreddit, keyword) query comes back full (truncated), fetch up to
# this many additional older pages by narrowing `before` to just past the
# oldest comment seen. Bounds the extra cost of backfilling a busy pair.
MAX_EXTRA_PAGES = 2


def search_comments(
    keywords: list[str],
    subreddits: list[str] | None = None,
    limit_per_keyword: int = 25,
    time_range: TimeRange | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
    on_truncated: Callable[[str], None] | None = None,
    on_skipped: Callable[[str], None] | None = None,
) -> list[dict]:
    """Search Arctic Shift for comments matching keywords across subreddits.

    For each subreddit x keyword pair, runs a body keyword search. Results are
    deduplicated by comment id.

    If `progress_callback` is given, it's called before each query as
    `progress_callback(done, total, description)`. If `stop_check` is given
    and returns truthy, the search stops early and returns what it has.

    Each (subreddit, keyword) query is capped at `limit_per_keyword` results,
    newest first (`sort=desc`). If a query returns a full page of results,
    older matching comments for that pair exist but weren't fetched yet — up
    to `MAX_EXTRA_PAGES` additional older pages are fetched automatically to
    backfill them. If the pair is still truncated after that (a genuinely
    very high-volume pair), `on_truncated` is called once per affected
    subreddit with the subreddit name.

    If a stop is requested partway through, the current keyword (whose
    subreddit loop was interrupted) and every keyword after it have no results
    at all for some or all subreddits. When `on_skipped` is given, it's called
    once per such keyword with the keyword text.
    """
    targets = [s.strip() for s in (subreddits or DEFAULT_SUBREDDITS) if s.strip()]
    time_range = time_range or TimeRange()
    capped_limit = max(1, min(limit_per_keyword, 100))

    seen_ids: set[str] = set()
    comments: list[dict] = []
    truncated_subreddits: set[str] = set()
    queries = 0
    failed = 0
    total_queries = len(keywords) * len(targets)
    stopped = False

    for keyword in keywords:
        if stopped:
            if on_skipped:
                on_skipped(keyword)
            continue
        for subreddit in targets:
            if stop_check and stop_check():
                stopped = True
                if on_skipped:
                    on_skipped(keyword)
                break
            if progress_callback:
                progress_callback(queries, total_queries, f"r/{subreddit} — \"{keyword}\"")
            queries += 1
            paged = _search_paginated(subreddit, keyword, capped_limit, time_range)
            if paged is None:  # query gave up after repeated timeouts/errors
                failed += 1
                continue
            result, truncated_pair = paged
            if truncated_pair and subreddit not in truncated_subreddits:
                truncated_subreddits.add(subreddit)
                if on_truncated:
                    on_truncated(subreddit)
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


def _search_paginated(subreddit: str, keyword: str, capped_limit: int,
                      time_range: TimeRange) -> tuple[list[dict], bool] | None:
    """Run `_search`, backfilling older pages if the first page comes back full.

    Each page is capped at `capped_limit` results, newest first. If a page is
    full, more matching comments older than its oldest result may exist, so
    another page is fetched with `before` narrowed to that oldest comment's
    date — up to `MAX_EXTRA_PAGES` extra pages total.

    Returns `(raw_results, still_truncated)`, where `still_truncated` is True
    if the last page fetched was still full (older matches likely remain even
    after backfilling). Returns None if the very first page failed outright
    (repeated timeouts/errors) — same convention as `_search`.
    """
    seen_ids: set[str] = set()
    all_raw: list[dict] = []
    before_utc = time_range.before_utc
    truncated = False

    for page in range(1 + MAX_EXTRA_PAGES):
        page_range = TimeRange(after_utc=time_range.after_utc, before_utc=before_utc)
        result = _search(subreddit, keyword, capped_limit, page_range)
        if result is None:
            if page == 0:
                return None
            break

        for raw in result:
            cid = raw.get("id")
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_raw.append(raw)

        truncated = len(result) >= capped_limit
        if not truncated or page == MAX_EXTRA_PAGES:
            break

        oldest_ts = min((raw.get("created_utc", 0) or 0) for raw in result)
        if time_range.after_utc and oldest_ts <= time_range.after_utc:
            break  # reached the start of the requested window
        before_utc = oldest_ts

    return all_raw, truncated


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
