"""CLI interface for RedditPulse."""

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from . import services
from .exceptions import RedditPulseError

console = Console()


def cmd_search(args):
    """Create/update a topic: generate keywords, fetch comments, store them."""
    try:
        console.print(f"[bold blue]Searching for:[/bold blue] {args.topic}")
        result = services.search_topic(
            topic=args.topic,
            subreddits=args.subreddits.split(",") if args.subreddits else None,
            limit=args.limit,
            time_filter=args.time,
            after=args.after,
            before=args.before,
            source=args.source,
            refresh=args.refresh,
            reset_comments=args.reset_comments,
            min_relevance=args.min_relevance,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    if result["status"] == "exists":
        console.print(
            f"Topic [bold]{args.topic}[/bold] already exists with {result['total_comments']} comments."
        )
        console.print("Use --refresh to add more comments, or --reset-comments to clear and re-fetch.")
        return

    if result["status"] == "reset":
        console.print(f"[yellow]Cleared old comments and analyses for '{args.topic}'. Keywords kept.[/yellow]")

    console.print(f"[green]Keywords:[/green] {', '.join(result['keywords'])}")
    console.print(f"[green]Found {result['fetched']} comments[/green]")
    if "filtered_out" in result:
        console.print(f"[yellow]Filtered out {result['filtered_out']} irrelevant comments (threshold: {args.min_relevance})[/yellow]")
    console.print(f"[green]Inserted {result['new_comments']} new comments (total: {result['total_comments']})[/green]")


def cmd_analyze(args):
    """Run analysis on stored comments for a topic."""
    try:
        if args.sentiment_only:
            console.print(f"[bold blue]Running sentiment-only analysis (no Claude) for:[/bold blue] {args.topic}")
        else:
            console.print(f"[bold blue]Analyzing comments for:[/bold blue] {args.topic}")

        result = services.analyze_topic(
            topic=args.topic,
            limit=args.limit,
            sentiment_only=args.sentiment_only,
            reset_analyses=args.reset_analyses,
            sentiment_model=args.model,
            min_score=args.min_score,
        )
    except RedditPulseError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if result.get("cached"):
        console.print("[yellow]Identical analysis already exists — returning the "
                      "saved result (no API call).[/yellow]")
    if args.reset_analyses:
        console.print(f"[yellow]Cleared old analyses for '{args.topic}'.[/yellow]")

    _display_results(args.topic, result)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        console.print(f"\n[green]Full results saved to {args.output}[/green]")


def cmd_topics(args):
    """List all tracked topics."""
    topics = services.list_topics()
    if not topics:
        console.print("[yellow]No topics yet. Use 'search' to create one.[/yellow]")
        return

    table = Table(title="Tracked Topics")
    table.add_column("Name", style="bold")
    table.add_column("Keywords")
    table.add_column("Comments", justify="right")
    table.add_column("Created")

    for t in topics:
        table.add_row(t["name"], t["keywords"], str(t["comment_count"]), t["created_at"][:10])

    console.print(table)


def cmd_runs(args):
    """Show fetch-run history for a topic."""
    try:
        runs = services.list_fetch_runs(args.topic)
    except RedditPulseError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if not runs:
        console.print("[yellow]No fetch runs recorded for this topic yet.[/yellow]")
        return

    table = Table(title=f"Fetch Runs — {args.topic}")
    table.add_column("ID", justify="right")
    table.add_column("Started")
    table.add_column("Source")
    table.add_column("Window")
    table.add_column("Subreddits")
    table.add_column("Fetched", justify="right")
    table.add_column("New", justify="right")
    table.add_column("Status")

    for r in runs:
        table.add_row(
            str(r["id"]), r["started_at"][:16], r["source"], r["window"],
            ",".join(r["subreddits"] or [])[:40] or "(default)",
            str(r["fetched"]), str(r["inserted"]), r["status"],
        )
    console.print(table)


def cmd_trim(args):
    """Trim stored comments by date and/or score."""
    try:
        result = services.trim_comments(
            args.topic,
            delete_before=args.delete_before,
            delete_after=args.delete_after,
            min_score=args.min_score,
        )
    except RedditPulseError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    console.print(f"[green]Deleted {result['deleted']} comments "
                  f"({result['remaining']} remaining).[/green]")


def cmd_validate(args):
    """Print a data-quality report for a topic."""
    try:
        report = services.validate_topic_data(args.topic)
    except RedditPulseError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    rng = report["date_range"]
    console.print(Panel(
        f"Comments: {report['total']}\n"
        f"Date range: {rng[0]} → {rng[1]}\n"
        f"Average score: {report['avg_score']}\n"
        f"Missing timestamps: {report['missing_timestamp']}\n"
        f"Empty bodies: {report['empty_body']}\n"
        f"Negative-score comments: {report['negative_score']}",
        title=f"Data quality — {args.topic}",
    ))
    for issue in report["issues"]:
        console.print(f"[yellow]⚠ {issue}[/yellow]")
    if report["ok"]:
        console.print("[green]No data-quality issues found.[/green]")


def cmd_export(args):
    """Export the last saved analysis from DB to JSON — no API call."""
    try:
        data = services.export_analysis(args.topic)
    except RedditPulseError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    with open(args.output, "w") as f:
        json.dump(data["result"], f, indent=2)

    console.print(f"[green]Exported analysis from {data['run_at'][:10]} to {args.output}[/green]")
    _display_results(args.topic, data["result"])


def cmd_browse(args):
    """Browse comments filtered by sentiment label."""
    try:
        data = services.browse_comments(
            topic=args.topic,
            sentiment_filter=args.sentiment,
            limit=args.limit,
            min_score=args.min_score,
        )
    except RedditPulseError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    color = {"positive": "green", "negative": "red", "neutral": "yellow"}[data["sentiment"]]
    console.print(
        f"\n[bold]{data['sentiment'].upper()} comments for '{args.topic}'[/bold] ({data['total']} shown)\n"
    )

    for c in data["comments"]:
        console.print(Panel(
            c["body"],
            title=f"[{color}]score:{c['score']}  sentiment:{c['compound']:+.2f}  r/{c['subreddit']}[/{color}]",
            border_style=color,
        ))
        console.print()


def cmd_showcase(args):
    """Build the static showcase site."""
    from .showcase import builder
    try:
        out = builder.build_site(output_dir=args.output)
    except RedditPulseError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    console.print(f"[green]Showcase site built at {out}[/green]")
    console.print("Commit the directory and enable GitHub Pages (Settings → Pages "
                  "→ deploy from branch, /docs folder) to publish it.")


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

    weighted = s.get("upvote_weighted")
    if weighted:
        console.print(Panel(
            f"[green]Positive: {weighted['pct_positive']}%[/green]  "
            f"[yellow]Neutral: {weighted['pct_neutral']}%[/yellow]  "
            f"[red]Negative: {weighted['pct_negative']}%[/red]  "
            f"(avg: {weighted['average_compound']:.3f})",
            title="Upvote-weighted sentiment (each comment weighted by its score)",
        ))

    themes = result["themes"]

    if "themes" in themes:
        table = Table(title="Top Themes")
        table.add_column("Theme", style="bold")
        table.add_column("Mentions", justify="right")
        table.add_column("Summary")
        for t in themes["themes"][:10]:
            table.add_row(t["theme"], str(t.get("count", "?")), t.get("summary", ""))
        console.print(table)

    if "emotions" in themes:
        table = Table(title="Emotions")
        table.add_column("Emotion", style="bold")
        table.add_column("Prevalence", justify="right")
        for e in themes["emotions"][:8]:
            table.add_row(e["emotion"], str(e.get("prevalence", "?")))
        console.print(table)

    if "opinions" in themes:
        table = Table(title="Key Opinions")
        table.add_column("Stance", style="bold")
        table.add_column("Strength")
        table.add_column("Prevalence", justify="right")
        for o in themes["opinions"][:8]:
            table.add_row(o["stance"], o.get("strength", "?"), str(o.get("prevalence", "?")))
        console.print(table)

    breakdown = themes.get("subtopic_breakdown")
    if breakdown and breakdown.get("categories"):
        dimension = breakdown.get("dimension", "Breakdown")
        table = Table(title=dimension)
        table.add_column(dimension, style="bold")
        table.add_column("%", justify="right")
        for c in breakdown["categories"]:
            table.add_row(c["category"], str(c.get("percentage", "?")))
        console.print(table)

    if "controversy_level" in themes:
        level = themes["controversy_level"]
        if isinstance(level, dict):
            text = f"{level.get('level', '?')} — {level.get('explanation', '')}"
        else:
            text = str(level)
        console.print(Panel(text, title="Controversy Level"))

    if "key_insights" in themes:
        console.print(Panel(
            "\n".join(f"• {i}" for i in themes["key_insights"]),
            title="Key Insights",
        ))


def main():
    parser = argparse.ArgumentParser(prog="redditpulse", description="Fetch and analyze Reddit discussions")
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="Fetch comments for a topic")
    p_search.add_argument("topic", help="Topic to search (e.g. 'AI and privacy')")
    p_search.add_argument("--subreddits", "-s", help="Comma-separated subreddits (default: source-specific)")
    p_search.add_argument("--limit", "-l", type=int, default=50, help="Results per keyword (default: 50)")
    p_search.add_argument("--time", "-t", default="month",
                          choices=["hour", "day", "week", "month", "6months", "year", "all"],
                          help="Relative lookback window (ignored if --after/--before given)")
    p_search.add_argument("--after", help="Explicit range start, ISO date (YYYY-MM-DD)")
    p_search.add_argument("--before", help="Explicit range end, ISO date (YYYY-MM-DD), inclusive")
    p_search.add_argument("--source", default="arctic", choices=["arctic", "praw", "rss"],
                          help="Data source (default: arctic — no credentials needed)")
    p_search.add_argument("--refresh", action="store_true", help="Fetch more comments for existing topic")
    p_search.add_argument("--reset-comments", action="store_true", help="Delete old comments and re-fetch (keeps keywords)")
    p_search.add_argument("--min-relevance", type=float, default=None,
                          help="Filter comments by semantic relevance (0.0-1.0, e.g. 0.3). Uses sentence-transformers.")
    p_search.set_defaults(func=cmd_search)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze stored comments")
    p_analyze.add_argument("topic", help="Topic name to analyze")
    p_analyze.add_argument("--limit", "-l", type=int, default=500, help="Max comments to analyze")
    p_analyze.add_argument("--model", "-m", default="vader", choices=["vader", "claude"],
                           help="Sentiment model (default: vader, local & free)")
    p_analyze.add_argument("--min-score", type=int, default=None,
                           help="Only analyze comments with at least this many upvotes")
    p_analyze.add_argument("--reset-analyses", action="store_true", help="Delete old analysis results before running")
    p_analyze.add_argument("--sentiment-only", action="store_true", help="Sentiment only, skip Claude themes call")
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
    p_browse.add_argument("--min-score", type=int, default=None,
                          help="Only show comments with at least this many upvotes")
    p_browse.set_defaults(func=cmd_browse)

    # topics
    p_topics = sub.add_parser("topics", help="List all tracked topics")
    p_topics.set_defaults(func=cmd_topics)

    # runs
    p_runs = sub.add_parser("runs", help="Show fetch-run history for a topic")
    p_runs.add_argument("topic", help="Topic name")
    p_runs.set_defaults(func=cmd_runs)

    # trim
    p_trim = sub.add_parser("trim", help="Trim stored comments by date/score")
    p_trim.add_argument("topic", help="Topic name")
    p_trim.add_argument("--delete-before", help="Delete comments created before this ISO date")
    p_trim.add_argument("--delete-after", help="Delete comments created after this ISO date")
    p_trim.add_argument("--min-score", type=int, help="Delete comments scoring below this")
    p_trim.set_defaults(func=cmd_trim)

    # validate
    p_validate = sub.add_parser("validate", help="Data-quality report for a topic")
    p_validate.add_argument("topic", help="Topic name")
    p_validate.set_defaults(func=cmd_validate)

    # showcase
    p_showcase = sub.add_parser("showcase", help="Build the static showcase site (GitHub Pages-ready)")
    p_showcase.add_argument("--output", "-o", default=None, help="Output directory (default: docs/)")
    p_showcase.set_defaults(func=cmd_showcase)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
