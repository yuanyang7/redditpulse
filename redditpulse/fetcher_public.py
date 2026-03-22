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

        topic_words, context_words = _extract_word_groups(keywords)
        for post_id in submission_ids:
            post_comments = _fetch_comments(post_id)
            for c in post_comments:
                if c["reddit_id"] in seen_ids:
                    continue
                body_lower = c["body"].lower()
                has_topic = any(w in body_lower for w in topic_words)
                has_context = any(w in body_lower for w in context_words)
                if not (has_topic and has_context):
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


def _extract_word_groups(keywords: list[str]) -> tuple[set[str], set[str]]:
    """Split keywords into two groups for AND-style filtering.

    Returns (topic_words, context_words) where a comment must contain
    at least one word from each group to be considered relevant.

    Topic words: AI/technology terms
    Context words: privacy/ethics/data terms
    """
    topic_words = {"ai", "artificial", "intelligence", "machine", "learning", "algorithm",
                   "facial", "recognition", "model", "llm", "chatgpt", "deepfake", "neural"}
    context_words = {"privacy", "surveillance", "data", "personal", "rights", "ethics",
                     "consent", "tracking", "collection", "security", "breach", "biometric"}

    # Also extract any significant words from the actual keywords
    stopwords = {"the", "a", "an", "and", "or", "of", "in", "on", "is", "it", "to", "for", "with", "about"}
    for kw in keywords:
        words = [w.lower() for w in kw.split() if w.lower() not in stopwords and len(w) > 2]
        # First word tends to be the topic, rest tend to be context
        if words:
            topic_words.add(words[0])
            context_words.update(words[1:])

    return topic_words, context_words


def _extract_words(keywords: list[str]) -> list[str]:
    stopwords = {"the", "a", "an", "and", "or", "of", "in", "on", "is", "it", "to", "for", "with", "about"}
    words = set()
    for kw in keywords:
        for word in kw.split():
            if word.lower() not in stopwords and len(word) > 2:
                words.add(word)
    return list(words)
