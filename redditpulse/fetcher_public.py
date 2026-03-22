"""Fetch Reddit comments via public JSON API — no credentials required."""

import time
import requests

HEADERS = {"User-Agent": "redditpulse/0.1 (personal research tool)"}
BASE = "https://www.reddit.com"


def search_comments(
    keywords: list[str],
    subreddits: list[str] | None = None,
    limit_per_keyword: int = 25,
    time_filter: str = "year",
) -> list[dict]:
    """Search Reddit via public JSON API, no OAuth needed.

    Note: Reddit caps public search at 25 results per query.
    """
    seen_ids: set[str] = set()
    comments: list[dict] = []

    for keyword in keywords:
        if subreddits:
            submission_ids = []
            for sr in subreddits:
                submission_ids += _search_submissions(keyword, subreddit=sr,
                                                      limit=limit_per_keyword, time_filter=time_filter)
        else:
            submission_ids = _search_submissions(keyword, subreddit=None,
                                                 limit=limit_per_keyword, time_filter=time_filter)

        for post_id in submission_ids:
            post_comments = _fetch_comments(post_id)
            kw_words = _extract_words(keywords)
            for c in post_comments:
                if c["reddit_id"] in seen_ids:
                    continue
                body_lower = c["body"].lower()
                if not any(w.lower() in body_lower for w in kw_words):
                    continue
                seen_ids.add(c["reddit_id"])
                comments.append(c)
            time.sleep(0.5)  # be polite to Reddit's servers

    return comments


def _search_submissions(keyword: str, subreddit: str | None, limit: int, time_filter: str) -> list[str]:
    """Return list of submission IDs matching keyword."""
    if subreddit:
        url = f"{BASE}/r/{subreddit}/search.json"
        params = {"q": keyword, "sort": "relevance", "t": time_filter,
                  "limit": min(limit, 25), "restrict_sr": 1}
    else:
        url = f"{BASE}/search.json"
        params = {"q": keyword, "sort": "relevance", "t": time_filter, "limit": min(limit, 25)}

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        posts = data.get("data", {}).get("children", [])
        return [p["data"]["id"] for p in posts]
    except Exception:
        return []
    finally:
        time.sleep(1)  # respect rate limit


def _fetch_comments(post_id: str) -> list[dict]:
    """Fetch all top-level comments for a submission."""
    url = f"{BASE}/comments/{post_id}.json"
    try:
        resp = requests.get(url, headers=HEADERS, params={"limit": 100}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if len(data) < 2:
            return []

        comments = []
        subreddit = data[0]["data"]["children"][0]["data"].get("subreddit", "unknown")
        for child in data[1]["data"]["children"]:
            c = child.get("data", {})
            if child.get("kind") != "t1":
                continue
            body = c.get("body", "").strip()
            if not body or body == "[deleted]" or body == "[removed]":
                continue
            comments.append({
                "reddit_id": c["id"],
                "subreddit": subreddit,
                "author": c.get("author", "[deleted]"),
                "body": body,
                "score": c.get("score", 0),
                "permalink": f"https://reddit.com{c.get('permalink', '')}",
                "created_utc": c.get("created_utc", 0),
            })
        return comments
    except Exception:
        return []


def _extract_words(keywords: list[str]) -> list[str]:
    stopwords = {"the", "a", "an", "and", "or", "of", "in", "on", "is", "it", "to", "for", "with", "about"}
    words = set()
    for kw in keywords:
        for word in kw.split():
            if word.lower() not in stopwords and len(word) > 2:
                words.add(word)
    return list(words)
