"""Analysis pipeline: VADER for sentiment, Claude API for themes and insights."""

import json
import os
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


def generate_keywords(topic: str) -> list[str]:
    """Use Claude to generate optimal Reddit search keywords for a topic."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": (
                f"Generate 5-8 effective Reddit search keywords/phrases for the topic: \"{topic}\"\n\n"
                "Return ONLY a JSON array of strings, no explanation. Example: [\"keyword1\", \"keyword2\"]"
            ),
        }],
    )
    text = response.content[0].text.strip()
    # Extract JSON array from response
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
        model="claude-sonnet-4-20250514",
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
                "- emotions: array of {{\"emotion\": string, \"prevalence\": number}} ranked\n"
                "- key_insights: array of strings (3-5 most important takeaways)\n"
                "- controversy_level: \"low\"|\"medium\"|\"high\" with brief explanation\n\n"
                "Return ONLY valid JSON, no explanation outside the JSON."
            ),
        }],
    )
    text = response.content[0].text.strip()
    start = text.index("{")
    end = text.rindex("}") + 1
    return json.loads(text[start:end])


def run_full_analysis(topic: str, comments: list[dict], skip_claude: bool = False) -> dict:
    """Run sentiment analysis, and optionally theme analysis via Claude."""
    sentiment = analyze_sentiment(comments)
    themes = analyze_themes(topic, comments) if not skip_claude else {}
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
