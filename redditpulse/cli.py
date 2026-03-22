"""CLI interface for RedditPulse."""

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from . import db, fetcher, fetcher_public, analyzer

console = Console()


def cmd_search(args):
    """Create/update a topic: generate keywords, fetch comments, store them."""
    conn = db.get_connection()
    db.init_db(conn)

    topic_name = args.topic

    # Check if topic already exists
    topic = db.get_topic(conn, topic_name)

    if topic and args.reset_comments:
        conn.execute("DELETE FROM comments WHERE topic_id = ?", (topic["id"],))
        conn.commit()
        db.delete_analyses(conn, topic["id"])
        console.print(f"[yellow]Cleared old comments and analyses for '{topic_name}'. Keywords kept.[/yellow]")
    elif topic and not args.refresh:
        console.print(f"Topic [bold]{topic_name}[/bold] already exists with {_count_comments(conn, topic['id'])} comments.")
        console.print("Use --refresh to add more comments, or --reset-comments to clear and re-fetch.")
        return

    # Generate keywords via Claude
    if not topic:
        console.print(f"[bold blue]Generating search keywords for:[/bold blue] {topic_name}")
        keywords = analyzer.generate_keywords(topic_name)
        console.print(f"[green]Keywords:[/green] {', '.join(keywords)}")
        topic_id = db.create_topic(conn, topic_name, keywords)
    else:
        topic_id = topic["id"]
        keywords = topic["keywords"].split(",")
        console.print(f"[green]Using existing keywords:[/green] {', '.join(keywords)}")

    # Fetch comments
    subreddits = args.subreddits.split(",") if args.subreddits else None
    if args.public:
        console.print("[bold blue]Fetching comments via public JSON API (no auth)...[/bold blue]")
        comments = fetcher_public.search_comments(
            keywords,
            subreddits=subreddits,
            limit_per_keyword=min(args.limit, 25),
            time_filter=args.time,
        )
    else:
        console.print("[bold blue]Fetching comments via PRAW (OAuth)...[/bold blue]")
        reddit = fetcher.get_reddit()
        comments = fetcher.search_comments(
            reddit,
            keywords,
            subreddits=subreddits,
            limit_per_keyword=args.limit,
            time_filter=args.time,
        )
    console.print(f"[green]Found {len(comments)} relevant comments[/green]")

    # Store
    inserted = db.insert_comments(conn, topic_id, comments)
    total = _count_comments(conn, topic_id)
    console.print(f"[green]Inserted {inserted} new comments (total: {total})[/green]")


def cmd_analyze(args):
    """Run analysis on stored comments for a topic."""
    conn = db.get_connection()
    db.init_db(conn)

    topic = db.get_topic(conn, args.topic)
    if not topic:
        console.print(f"[red]Topic '{args.topic}' not found. Run 'search' first.[/red]")
        sys.exit(1)

    if args.reset_analyses:
        db.delete_analyses(conn, topic["id"])
        console.print(f"[yellow]Cleared old analyses for '{args.topic}'.[/yellow]")

    comments = db.get_comments_for_topic(conn, topic["id"], limit=args.limit)
    if not comments:
        console.print("[red]No comments found for this topic.[/red]")
        sys.exit(1)

    console.print(f"[bold blue]Analyzing {len(comments)} comments for:[/bold blue] {args.topic}")

    result = analyzer.run_full_analysis(args.topic, comments)

    # Save to DB
    db.save_analysis(
        conn,
        topic["id"],
        num_comments=len(comments),
        sentiment_summary=json.dumps(result["sentiment"]),
        themes=json.dumps(result["themes"]),
        raw_result=json.dumps(result),
    )

    # Display results
    _display_results(args.topic, result)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        console.print(f"\n[green]Full results saved to {args.output}[/green]")


def cmd_topics(args):
    """List all tracked topics."""
    conn = db.get_connection()
    db.init_db(conn)

    topics = db.get_all_topics(conn)
    if not topics:
        console.print("[yellow]No topics yet. Use 'search' to create one.[/yellow]")
        return

    table = Table(title="Tracked Topics")
    table.add_column("Name", style="bold")
    table.add_column("Keywords")
    table.add_column("Comments", justify="right")
    table.add_column("Created")

    for t in topics:
        count = _count_comments(conn, t["id"])
        table.add_row(t["name"], t["keywords"], str(count), t["created_at"][:10])

    console.print(table)


def cmd_export(args):
    """Export the last saved analysis from DB to JSON — no API call."""
    conn = db.get_connection()
    db.init_db(conn)

    topic = db.get_topic(conn, args.topic)
    if not topic:
        console.print(f"[red]Topic '{args.topic}' not found.[/red]")
        sys.exit(1)

    analysis = db.get_latest_analysis(conn, topic["id"])
    if not analysis:
        console.print(f"[red]No analysis found for '{args.topic}'. Run 'analyze' first.[/red]")
        sys.exit(1)

    result = json.loads(analysis["raw_result"])
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    console.print(f"[green]Exported analysis from {analysis['run_at'][:10]} to {args.output}[/green]")
    _display_results(args.topic, result)


def _display_results(topic: str, result: dict):
    """Pretty-print analysis results."""
    s = result["sentiment"]
    console.print(Panel(
        f"[green]Positive: {s['positive']}[/green]  "
        f"[yellow]Neutral: {s['neutral']}[/yellow]  "
        f"[red]Negative: {s['negative']}[/red]  "
        f"(avg: {s['average_compound']:.3f})",
        title=f"Sentiment — {s['total']} comments",
    ))

    themes = result["themes"]

    # Themes table
    if "themes" in themes:
        table = Table(title="Top Themes")
        table.add_column("Theme", style="bold")
        table.add_column("Mentions", justify="right")
        table.add_column("Summary")
        for t in themes["themes"][:10]:
            table.add_row(t["theme"], str(t.get("count", "?")), t.get("summary", ""))
        console.print(table)

    # Emotions
    if "emotions" in themes:
        table = Table(title="Emotions")
        table.add_column("Emotion", style="bold")
        table.add_column("Prevalence", justify="right")
        for e in themes["emotions"][:8]:
            table.add_row(e["emotion"], str(e.get("prevalence", "?")))
        console.print(table)

    # Opinions
    if "opinions" in themes:
        table = Table(title="Key Opinions")
        table.add_column("Stance", style="bold")
        table.add_column("Strength")
        table.add_column("Prevalence", justify="right")
        for o in themes["opinions"][:8]:
            table.add_row(o["stance"], o.get("strength", "?"), str(o.get("prevalence", "?")))
        console.print(table)

    # Controversy
    if "controversy_level" in themes:
        level = themes["controversy_level"]
        if isinstance(level, dict):
            text = f"{level.get('level', '?')} — {level.get('explanation', '')}"
        else:
            text = str(level)
        console.print(Panel(text, title="Controversy Level"))

    # Key insights
    if "key_insights" in themes:
        console.print(Panel(
            "\n".join(f"• {i}" for i in themes["key_insights"]),
            title="Key Insights",
        ))


def cmd_browse(args):
    """Browse comments filtered by sentiment label."""
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    vader = SentimentIntensityAnalyzer()

    conn = db.get_connection()
    db.init_db(conn)

    topic = db.get_topic(conn, args.topic)
    if not topic:
        console.print(f"[red]Topic '{args.topic}' not found.[/red]")
        sys.exit(1)

    comments = db.get_comments_for_topic(conn, topic["id"], limit=2000)

    # Filter by sentiment
    def label(score):
        if score >= 0.05:
            return "positive"
        elif score <= -0.05:
            return "negative"
        return "neutral"

    filtered = []
    for c in comments:
        compound = vader.polarity_scores(c["body"])["compound"]
        if label(compound) == args.sentiment:
            filtered.append((compound, c))

    # Sort strongest sentiment first
    filtered.sort(key=lambda x: abs(x[0]), reverse=True)
    filtered = filtered[:args.limit]

    color = {"positive": "green", "negative": "red", "neutral": "yellow"}[args.sentiment]
    console.print(f"\n[bold]{args.sentiment.upper()} comments for '{args.topic}'[/bold] ({len(filtered)} shown)\n")

    for compound, c in filtered:
        console.print(Panel(
            c["body"],
            title=f"[{color}]score:{c['score']}  vader:{compound:+.2f}  r/{c['subreddit']}[/{color}]",
            border_style=color,
        ))
        console.print()


def _count_comments(conn, topic_id: int) -> int:
    row = conn.execute("SELECT COUNT(*) as cnt FROM comments WHERE topic_id = ?", (topic_id,)).fetchone()
    return row["cnt"]


def main():
    parser = argparse.ArgumentParser(prog="redditpulse", description="Fetch and analyze Reddit discussions")
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Fetch comments for a topic")
    p_search.add_argument("topic", help="Topic to search (e.g. 'AI and privacy')")
    p_search.add_argument("--subreddits", "-s", help="Comma-separated subreddits (default: all)")
    p_search.add_argument("--limit", "-l", type=int, default=30, help="Submissions per keyword (default: 30)")
    p_search.add_argument("--time", "-t", default="month", choices=["hour", "day", "week", "month", "year", "all"])
    p_search.add_argument("--refresh", action="store_true", help="Fetch more comments for existing topic")
    p_search.add_argument("--reset-comments", action="store_true", help="Delete old comments and re-fetch (keeps keywords)")
    p_search.add_argument("--public", action="store_true", help="Use public JSON API (no Reddit credentials needed)")
    p_search.set_defaults(func=cmd_search)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze stored comments")
    p_analyze.add_argument("topic", help="Topic name to analyze")
    p_analyze.add_argument("--limit", "-l", type=int, default=500, help="Max comments to analyze")
    p_analyze.add_argument("--reset-analyses", action="store_true", help="Delete old analysis results before running")
    p_analyze.add_argument("--output", "-o", help="Save full JSON results to file")
    p_analyze.set_defaults(func=cmd_analyze)

    # export
    p_export = sub.add_parser("export", help="Export last saved analysis to JSON without re-running Claude")
    p_export.add_argument("topic", help="Topic name to export")
    p_export.add_argument("--output", "-o", default="results.json", help="Output file (default: results.json)")
    p_export.set_defaults(func=cmd_export)

    # browse
    p_browse = sub.add_parser("browse", help="Browse comments filtered by sentiment")
    p_browse.add_argument("topic", help="Topic name")
    p_browse.add_argument("--sentiment", "-s", default="negative", choices=["positive", "negative", "neutral"],
                          help="Sentiment to filter by (default: negative)")
    p_browse.add_argument("--limit", "-l", type=int, default=20, help="Max comments to show (default: 20)")
    p_browse.set_defaults(func=cmd_browse)

    # topics
    p_topics = sub.add_parser("topics", help="List all tracked topics")
    p_topics.set_defaults(func=cmd_topics)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
