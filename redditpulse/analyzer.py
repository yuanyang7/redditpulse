"""Analysis pipeline: VADER for sentiment, Claude API for themes and insights."""

import json
import os
from collections import Counter
from anthropic import Anthropic
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from dotenv import load_dotenv

load_dotenv()

vader = SentimentIntensityAnalyzer()


def analyze_sentiment(comments: list[dict]) -> dict:
    """Run VADER sentiment on each comment. Returns summary stats + per-comment scores."""
    scores = []
    for c in comments:
        vs = vader.polarity_scores(c["body"])
        scores.append({
            "reddit_id": c["reddit_id"],
            "compound": vs["compound"],
            "label": _label(vs["compound"]),
        })

    pos = sum(1 for s in scores if s["label"] == "positive")
    neg = sum(1 for s in scores if s["label"] == "negative")
    neu = sum(1 for s in scores if s["label"] == "neutral")
    avg = sum(s["compound"] for s in scores) / len(scores) if scores else 0

    return {
        "total": len(scores),
        "positive": pos,
        "negative": neg,
        "neutral": neu,
        "average_compound": round(avg, 4),
        "scores": scores,
    }


def _label(compound: float) -> str:
    if compound >= 0.05:
        return "positive"
    elif compound <= -0.05:
        return "negative"
    return "neutral"


# Nominal compound score per Claude label, so downstream code that expects a
# numeric compound (averages, sorting) keeps working.
_LABEL_COMPOUND = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}


def analyze_sentiment_claude(comments: list[dict]) -> dict:
    """Classify each comment's sentiment with Claude. Same shape as analyze_sentiment."""
    labels = classify_sentiment_batch([c["body"] for c in comments])
    scores = []
    for c, label in zip(comments, labels):
        label = label if label in _LABEL_COMPOUND else "neutral"
        scores.append({
            "reddit_id": c["reddit_id"],
            "compound": _LABEL_COMPOUND[label],
            "label": label,
        })

    pos = sum(1 for s in scores if s["label"] == "positive")
    neg = sum(1 for s in scores if s["label"] == "negative")
    neu = sum(1 for s in scores if s["label"] == "neutral")
    avg = sum(s["compound"] for s in scores) / len(scores) if scores else 0

    return {
        "total": len(scores),
        "positive": pos,
        "negative": neg,
        "neutral": neu,
        "average_compound": round(avg, 4),
        "scores": scores,
    }


def generate_keywords(topic: str) -> list[str]:
    """Use Claude to generate optimal Reddit search keywords for a topic."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                f"Generate 5-8 effective Reddit search keywords/phrases for the topic: \"{topic}\"\n\n"
                "Keep the keywords neutral and balanced. Avoid phrases that presuppose a "
                "negative or positive outcome (e.g. prefer \"hiring\" over \"hiring freeze\", "
                "\"job market\" over \"job market crash\") so the search doesn't skew the "
                "fetched comments toward one sentiment.\n\n"
                "Return ONLY a JSON array of strings, no explanation. Example: [\"keyword1\", \"keyword2\"]"
            ),
        }],
    )
    text = response.content[0].text.strip()
    # Extract JSON array from response
    start = text.index("[")
    end = text.rindex("]") + 1
    return json.loads(text[start:end])


def generate_subreddits(topic: str) -> list[str]:
    """Use Claude to suggest relevant subreddits to search for a topic."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                f"Suggest 5-8 active subreddits where people would discuss the topic: "
                f"\"{topic}\"\n\n"
                "Prefer subreddits dedicated to or closely related to the topic over "
                "broad general-discussion subreddits, but include a couple of broad "
                "ones (e.g. AskReddit) if they'd plausibly carry relevant discussion too.\n\n"
                "Return ONLY a JSON array of subreddit names without the \"r/\" prefix, "
                "no explanation. Example: [\"technology\", \"privacy\"]"
            ),
        }],
    )
    text = response.content[0].text.strip()
    start = text.index("[")
    end = text.rindex("]") + 1
    return json.loads(text[start:end])


def analyze_themes(topic: str, comments: list[dict]) -> dict:
    """Use Claude to extract themes, ranked opinions, and key insights from comments."""
    # Sample comments to stay within token limits
    sampled = _sample_comments(comments, max_chars=12000)
    comments_text = "\n---\n".join(
        f"[score:{c['score']}] {c['body'][:500]}" for c in sampled
    )

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": (
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
                "Return ONLY valid JSON, no explanation outside the JSON."
            ),
        }],
    )
    text = response.content[0].text.strip()
    start = text.index("{")
    end = text.rindex("}") + 1
    return json.loads(text[start:end])


def classify_sentiment_batch(texts: list[str], batch_size: int = 50) -> list[str]:
    """Use Claude (Haiku) to classify each text as positive/negative/neutral."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    labels = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        numbered = "\n".join(f"{j + 1}. {t[:500]}" for j, t in enumerate(batch))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=batch_size * 15 + 100,
            messages=[{
                "role": "user",
                "content": (
                    "Classify the sentiment of each numbered Reddit comment below as "
                    "\"positive\", \"negative\", or \"neutral\".\n\n"
                    f"{numbered}\n\n"
                    "Return ONLY a JSON array of strings, one label per comment in order, "
                    "no explanation. Example: [\"positive\", \"negative\", \"neutral\"]"
                ),
            }],
        )
        text = response.content[0].text.strip()
        start = text.index("[")
        end = text.rindex("]") + 1
        labels.extend(json.loads(text[start:end]))
    return labels


def classify_subtopics_batch(texts: list[str], dimension: str, categories: list[str],
                             batch_size: int = 50) -> list[str]:
    """Use Claude (Haiku) to classify each text into one of `categories`, or "Other"."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    options = categories + ["Other"]
    labels = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        numbered = "\n".join(f"{j + 1}. {t[:500]}" for j, t in enumerate(batch))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=batch_size * 20 + 100,
            messages=[{
                "role": "user",
                "content": (
                    f"Classify each numbered Reddit comment below by \"{dimension}\" "
                    f"into exactly one of these categories: {json.dumps(options)}.\n\n"
                    "If a comment doesn't clearly fit any named category, use \"Other\".\n\n"
                    f"{numbered}\n\n"
                    "Return ONLY a JSON array of strings (one category per comment, in "
                    "order), no explanation."
                ),
            }],
        )
        text = response.content[0].text.strip()
        start = text.index("[")
        end = text.rindex("]") + 1
        labels.extend(json.loads(text[start:end]))
    return labels


def _compute_subtopic_breakdown(comments: list[dict], breakdown: dict) -> dict | None:
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


def run_full_analysis(topic: str, comments: list[dict], skip_claude: bool = False,
                      sentiment_model: str = "vader") -> dict:
    """Run sentiment analysis, and optionally theme analysis via Claude.

    sentiment_model: "vader" (local, fast) or "claude" (LLM, more nuanced).
    """
    if sentiment_model == "claude":
        sentiment = analyze_sentiment_claude(comments)
    else:
        sentiment = analyze_sentiment(comments)
    themes = analyze_themes(topic, comments) if not skip_claude else {}
    if themes.get("subtopic_breakdown"):
        recomputed = _compute_subtopic_breakdown(comments, themes["subtopic_breakdown"])
        if recomputed:
            themes["subtopic_breakdown"] = recomputed
        else:
            themes.pop("subtopic_breakdown", None)
    return {
        "sentiment": {k: v for k, v in sentiment.items() if k != "scores"},
        "themes": themes,
        "per_comment_sentiment": sentiment["scores"],
    }


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
