"""Build a static showcase site from saved analyses.

The output is a plain directory of HTML files (default ``docs/``) with no
server-side requirements — push it to GitHub and enable Pages on the /docs
folder to publish. All data is embedded in the pages and charts render
client-side via vega-lite from a CDN.

What each topic page shows is driven by its *showcase config* (stored on the
topic, editable in the GUI's Showcase tab or via services.set_showcase_config):

    {
        "enabled": true,            # include this topic on the site
        "title": "Custom title",    # defaults to the topic name
        "description": "...",       # intro text under the title
        "sections": [...],          # which sections to render, in order
        "section_notes": {          # optional commentary per section
            "trends": "Spike in March follows the keynote."
        }
    }

No API calls are made: the site is built entirely from stored analyses.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..exceptions import NoAnalysisError, NoCommentsError
from .. import services
from . import templates

# All known sections, in default render order.
SECTIONS = [
    "sentiment", "trends", "themes", "emotions", "breakdown",
    "opinions", "insights", "top_comments",
]

SITE_TITLE = "RedditPulse Showcase"
SITE_SUBTITLE = "What Reddit thinks — sentiment and themes mined from real discussions."


def default_config(topic_name: str) -> dict:
    return {
        "enabled": True,
        "title": topic_name,
        "description": "",
        "sections": list(SECTIONS),
        "section_notes": {},
    }


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "topic"


def _topic_payload(topic_name: str, config: dict) -> dict | None:
    """Assemble everything a topic page needs, or None if it has no analysis."""
    try:
        analysis = services.export_analysis(topic_name)
    except NoAnalysisError:
        return None

    result = analysis["result"]

    try:
        trends = services.get_sentiment_trends(topic_name)
    except NoCommentsError:
        trends = None

    summary = services.get_topic_summary(topic_name)

    # Strongest comments per sentiment, labeled like the Analyze/Browse tabs.
    top_comments = []
    for label in ("positive", "negative"):
        data = services.browse_comments(topic_name, sentiment_filter=label, limit=3)
        for c in data["comments"]:
            top_comments.append({
                "body": c["body"][:600],
                "score": c["score"],
                "subreddit": c["subreddit"],
                "permalink": c["permalink"],
                "label": label,
            })
    top_comments.sort(key=lambda c: c["score"], reverse=True)

    return {
        "name": topic_name,
        "title": config.get("title") or topic_name,
        "description": config.get("description", ""),
        "sections": config.get("sections") or list(SECTIONS),
        "section_notes": config.get("section_notes") or {},
        "comment_count": summary["comment_count"],
        "run_at": analysis["run_at"][:10],
        "analysis": {
            "sentiment": result.get("sentiment", {}),
            "themes": result.get("themes", {}),
        },
        "trends": {
            "bucket": trends["bucket"],
            "points": trends["points"],
        } if trends else None,
        "top_comments": top_comments[:6],
    }


def build_site(output_dir: str | Path | None = None) -> Path:
    """Render the showcase site. Returns the output directory path.

    Topics are included when they have at least one saved analysis and their
    showcase config doesn't disable them.
    """
    out = Path(output_dir) if output_dir else get_settings().showcase_output_dir
    topics_dir = out / "topics"
    if topics_dir.exists():
        shutil.rmtree(topics_dir)
    topics_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = []

    for topic in services.list_topics():
        name = topic["name"]
        config = services.get_showcase_config(name) or default_config(name)
        if not config.get("enabled", True):
            continue
        payload = _topic_payload(name, config)
        if payload is None:
            continue

        slug = slugify(name)
        page = (
            templates.TOPIC_TEMPLATE
            .replace("__PAYLOAD_JSON__", json.dumps(payload).replace("</", "<\\/"))
            .replace("__SITE_TITLE__", SITE_TITLE)
            .replace("__TITLE__", _esc(payload["title"]))
            .replace("__DESCRIPTION__", _esc(payload["description"]))
            .replace("__COMMENT_COUNT__", str(payload["comment_count"]))
            .replace("__RUN_AT__", payload["run_at"])
            .replace("__EXTRA_BADGES__", "")
            .replace("__GENERATED_AT__", generated_at)
        )
        (topics_dir / f"{slug}.html").write_text(page)

        sent = payload["analysis"]["sentiment"]
        total = max(sent.get("total", 0), 1)
        cards.append(
            templates.TOPIC_CARD_TEMPLATE
            .replace("__SLUG__", slug)
            .replace("__TITLE__", _esc(payload["title"]))
            .replace("__DESCRIPTION__", _esc(payload["description"]))
            .replace("__PCT_POS__", str(round(100 * sent.get("positive", 0) / total)))
            .replace("__PCT_NEU__", str(round(100 * sent.get("neutral", 0) / total)))
            .replace("__PCT_NEG__", str(round(100 * sent.get("negative", 0) / total)))
            .replace("__COMMENT_COUNT__", str(payload["comment_count"]))
            .replace("__RUN_AT__", payload["run_at"])
        )

    index = (
        templates.INDEX_TEMPLATE
        .replace("__SITE_TITLE__", SITE_TITLE)
        .replace("__SITE_SUBTITLE__", SITE_SUBTITLE)
        .replace("__TOPIC_CARDS__", "\n".join(cards) if cards else
                 '<div class="card">No showcased topics yet — run an analysis '
                 'and enable topics in the Showcase tab.</div>')
        .replace("__GENERATED_AT__", generated_at)
    )
    (out / "index.html").write_text(index)
    (out / ".nojekyll").write_text("")
    return out


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
