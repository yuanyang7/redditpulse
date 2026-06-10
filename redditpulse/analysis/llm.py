"""All Claude API calls live here: keyword/subreddit generation, themes,
batch classification. Centralizing them makes API usage (and cost) auditable.
"""

import json
from collections import Counter

from anthropic import Anthropic

from ..config import get_settings


def _client() -> Anthropic:
    return Anthropic(api_key=get_settings().require_anthropic_key())


def _ask(prompt: str, max_tokens: int) -> str:
    response = _client().messages.create(
        model=get_settings().claude_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _extract_json(text: str, open_ch: str, close_ch: str):
    start = text.index(open_ch)
    end = text.rindex(close_ch) + 1
    return json.loads(text[start:end])


def generate_keywords(topic: str) -> list[str]:
    """Use Claude to generate optimal Reddit search keywords for a topic."""
    text = _ask(
        f"Generate 5-8 effective Reddit search keywords/phrases for the topic: \"{topic}\"\n\n"
        "Keep the keywords neutral and balanced. Avoid phrases that presuppose a "
        "negative or positive outcome (e.g. prefer \"hiring\" over \"hiring freeze\", "
        "\"job market\" over \"job market crash\") so the search doesn't skew the "
        "fetched comments toward one sentiment.\n\n"
        "Return ONLY a JSON array of strings, no explanation. Example: [\"keyword1\", \"keyword2\"]",
        max_tokens=300,
    )
    return _extract_json(text, "[", "]")


def generate_subreddits(topic: str) -> list[str]:
    """Use Claude to suggest relevant subreddits to search for a topic."""
    text = _ask(
        f"Suggest 5-8 active subreddits where people would discuss the topic: "
        f"\"{topic}\"\n\n"
        "Prefer subreddits dedicated to or closely related to the topic over "
        "broad general-discussion subreddits, but include a couple of broad "
        "ones (e.g. AskReddit) if they'd plausibly carry relevant discussion too.\n\n"
        "Return ONLY a JSON array of subreddit names without the \"r/\" prefix, "
        "no explanation. Example: [\"technology\", \"privacy\"]",
        max_tokens=300,
    )
    return _extract_json(text, "[", "]")


def analyze_themes(topic: str, comments: list[dict]) -> dict:
    """Use Claude to extract themes, ranked opinions, and key insights from comments."""
    sampled = _sample_comments(comments, max_chars=12000)
    comments_text = "\n---\n".join(
        f"[score:{c['score']}] {c['body'][:500]}" for c in sampled
    )
    text = _ask(
        f"Analyze these Reddit comments about \"{topic}\".\n\n"
        f"Comments ({len(sampled)} sampled from {len(comments)} total):\n"
        f"{comments_text}\n\n"
        "Return a JSON object with these fields:\n"
        "- themes: array of {{\"theme\": string, \"count\": number, \"summary\": string}} ranked by prevalence\n"
        "- opinions: array of {{\"stance\": string, \"strength\": \"strong\"|\"moderate\"|\"weak\", \"prevalence\": number}} ranked\n"
        "- emotions: array of {{\"emotion\": string, \"prevalence\": number}} ranked, "
        "where emotion is a single word or short universal label (e.g. \"Anger\", "
        "\"Fear\", \"Frustration\", \"Distrust\", \"Resignation\") with no extra "
        "context or qualifiers\n"
        "- key_insights: array of strings (3-5 most important takeaways)\n"
        "- controversy_level: \"low\"|\"medium\"|\"high\" with brief explanation\n"
        "- subtopic_breakdown: if the comments naturally cluster into named "
        "categories along some shared dimension relevant to this topic (e.g. for "
        "a topic about music, genres like \"Rock\", \"Hip-Hop\", \"Pop\"; for a "
        "topic about phones, brands like \"iPhone\", \"Samsung\"; for a topic "
        "about diets, types like \"Keto\", \"Vegan\"), return "
        "{{\"dimension\": short label naming the category type (e.g. \"Genre\", "
        "\"Brand\", \"Diet Type\"), \"categories\": array of 3-6 category name "
        "strings that comments could be classified into}}. Do not estimate "
        "percentages — just name the categories. Omit this field entirely if no "
        "such breakdown is meaningful for this topic.\n\n"
        "Return ONLY valid JSON, no explanation outside the JSON.",
        max_tokens=2000,
    )
    return _extract_json(text, "{", "}")


def classify_sentiment_batch(texts: list[str], batch_size: int = 50) -> list[str]:
    """Use Claude to classify each text as positive/negative/neutral."""
    labels = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        numbered = "\n".join(f"{j + 1}. {t[:500]}" for j, t in enumerate(batch))
        text = _ask(
            "Classify the sentiment of each numbered Reddit comment below as "
            "\"positive\", \"negative\", or \"neutral\".\n\n"
            f"{numbered}\n\n"
            "Return ONLY a JSON array of strings, one label per comment in order, "
            "no explanation. Example: [\"positive\", \"negative\", \"neutral\"]",
            max_tokens=batch_size * 15 + 100,
        )
        labels.extend(_extract_json(text, "[", "]"))
    return labels


def classify_subtopics_batch(texts: list[str], dimension: str, categories: list[str],
                             batch_size: int = 50) -> list[str]:
    """Use Claude to classify each text into one of `categories`, or "Other"."""
    options = categories + ["Other"]
    labels = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        numbered = "\n".join(f"{j + 1}. {t[:500]}" for j, t in enumerate(batch))
        text = _ask(
            f"Classify each numbered Reddit comment below by \"{dimension}\" "
            f"into exactly one of these categories: {json.dumps(options)}.\n\n"
            "If a comment doesn't clearly fit any named category, use \"Other\".\n\n"
            f"{numbered}\n\n"
            "Return ONLY a JSON array of strings (one category per comment, in "
            "order), no explanation.",
            max_tokens=batch_size * 20 + 100,
        )
        labels.extend(_extract_json(text, "[", "]"))
    return labels


def compute_subtopic_breakdown(comments: list[dict], breakdown: dict) -> dict | None:
    """Replace estimated category names with real percentages via classify-then-count."""
    categories = breakdown.get("categories")
    if not categories:
        return None
    dimension = breakdown.get("dimension", "Category")
    labels = classify_subtopics_batch([c["body"] for c in comments], dimension, categories)
    counts = Counter(labels)
    total = len(labels)
    if not total:
        return None
    result = []
    for name in categories + ["Other"]:
        pct = round(counts.get(name, 0) / total * 100, 1)
        if pct > 0:
            result.append({"category": name, "percentage": pct})
    result.sort(key=lambda c: c["percentage"], reverse=True)
    return {"dimension": dimension, "categories": result}


def _sample_comments(comments: list[dict], max_chars: int = 12000) -> list[dict]:
    """Pick top-scored comments that fit within the character budget."""
    sorted_comments = sorted(comments, key=lambda c: c["score"], reverse=True)
    sampled = []
    total_chars = 0
    for c in sorted_comments:
        text_len = min(len(c["body"]), 500)
        if total_chars + text_len > max_chars:
            break
        sampled.append(c)
        total_chars += text_len
    return sampled
