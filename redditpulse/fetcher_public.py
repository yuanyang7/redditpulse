"""Fetch Reddit comments via public RSS feeds — no credentials required.

Reddit blocked anonymous access to its `.json` endpoints (HTTP 403) in 2025.
The `.rss` (Atom) feeds remain publicly accessible for now and are used here as
a fallback. Note: RSS feeds do NOT expose comment scores, so `score` defaults
to 0 in this path (unlike the authenticated PRAW fetcher).
"""

import re
import time
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

# A browser-like User-Agent is required; Reddit blocks generic/bot agents.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
BASE = "https://www.reddit.com"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


def _get(url: str, params: dict, max_retries: int = 4) -> requests.Response:
    """GET a Reddit RSS URL, retrying 429s with exponential backoff.

    429 (Too Many Requests) is transient, so we back off and retry. 401/403
    are hard blocks and raise immediately.
    """
    delay = 3.0
    for attempt in range(max_retries):
        resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if resp.status_code == 429:
            if attempt < max_retries - 1:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                time.sleep(wait)
                delay *= 2  # exponential backoff
                continue
            raise RuntimeError(
                "Reddit is rate-limiting public RSS requests (HTTP 429) even after "
                "retries. Wait a few minutes and try again, reduce the Limit, or "
                "provide Reddit credentials in .env and uncheck 'Use public API'."
            )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"Reddit blocked the public RSS request (HTTP {resp.status_code}). "
                "Anonymous access is blocked — uncheck 'Use public API' and provide "
                "Reddit credentials in .env instead."
            )
        resp.raise_for_status()
        return resp
    raise RuntimeError("Reddit RSS request failed after retries.")


def search_comments(
    keywords: list[str],
    subreddits: list[str] | None = None,
    limit_per_keyword: int = 25,
    time_filter: str = "year",
) -> list[dict]:
    """Search Reddit via public RSS feeds, no OAuth needed.

    Note: Reddit caps public search at 25 results per query, and RSS feeds
    do not include comment scores (all scores default to 0).
    """
    seen_ids: set[str] = set()
    comments: list[dict] = []

    for keyword in keywords:
        if subreddits:
            permalinks = []
            for sr in subreddits:
                permalinks += _search_submissions(keyword, subreddit=sr,
                                                   limit=limit_per_keyword, time_filter=time_filter)
        else:
            permalinks = _search_submissions(keyword, subreddit=None,
                                             limit=limit_per_keyword, time_filter=time_filter)

        topic_words, context_words = _extract_word_groups(keywords)
        for permalink in permalinks:
            post_comments = _fetch_comments(permalink)
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
    """Return list of submission permalinks matching keyword (via search.rss)."""
    if subreddit:
        url = f"{BASE}/r/{subreddit}/search.rss"
        params = {"q": keyword, "sort": "relevance", "t": time_filter,
                  "limit": min(limit, 25), "restrict_sr": 1}
    else:
        url = f"{BASE}/search.rss"
        params = {"q": keyword, "sort": "relevance", "t": time_filter, "limit": min(limit, 25)}

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
            author = author_el.text if author_el is not None else "[deleted]"
            if author and author.startswith("/u/"):
                author = author[3:]

            if author == "AutoModerator":
                continue  # bot boilerplate, not real discussion

            content = entry.findtext("a:content", default="", namespaces=ATOM_NS) or ""
            body = _html_to_text(content)
            if not body or body in ("[deleted]", "[removed]"):
                continue

            link_el = entry.find("a:link", ATOM_NS)
            comment_permalink = link_el.get("href") if link_el is not None else permalink

            published = entry.findtext("a:published", default="", namespaces=ATOM_NS)
            created_utc = _parse_ts(published)

            comments.append({
                "reddit_id": comment_id,
                "subreddit": subreddit,
                "author": author,
                "body": body,
                "score": 0,  # not available via RSS
                "permalink": comment_permalink,
                "created_utc": created_utc,
            })
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
