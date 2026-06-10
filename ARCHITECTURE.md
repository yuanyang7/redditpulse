# RedditPulse Architecture

## Layers

```
CLI (cli.py)      GUI (ui/)        Showcase builder (showcase/)
        \             |             /
         +---- services/ ----------+        ← public API, owns DB sessions
        /            |              \
 fetchers/      analysis/        storage/
 (data in)      (NLU, scoring)   (SQLite, migrations, repos)
```

Rules of the road:

- **All SQL lives in `storage/repo.py`**; transactions are committed there.
  `storage/db.py` owns connections and versioned migrations
  (`PRAGMA user_version`); both fresh and legacy databases migrate
  automatically on connect.
- **All Claude API calls live in `analysis/llm.py`** so API usage (and cost)
  is auditable in one place.
- **Callers (CLI / GUI / showcase) only import `redditpulse.services`** —
  never storage, fetchers, or the Anthropic client directly.
- `config.py` is the single place environment variables are read.
- Domain errors are defined in `exceptions.py` and shared everywhere.

## Packages

| Package | Responsibility |
|---|---|
| `storage/` | SQLite schema + migrations (`db.py`), repository functions (`repo.py`) |
| `fetchers/` | `arctic` (Arctic Shift archive, default), `praw_fetcher` (Reddit API), `rss` (public fallback). Shared `base.py`: `TimeRange`, comment normalization/validation |
| `analysis/` | `sentiment` (VADER/Claude scoring, upvote-weighted summaries), `llm` (Claude calls), `relevance` (embeddings), `evaluation` (metrics) |
| `services/` | `search` (fetch + run recording), `analyze` (analysis + caching, browse, trends, labeling, evaluation), `data` (run history, trim, validate), `topics` |
| `ui/` | Streamlit app: `app.py` entry, `sidebar.py`, `theme.py`, `tabs/` (one module per tab) |
| `showcase/` | Static-site builder (`builder.py`) + HTML templates (`templates.py`) |

## Key data flows

### Fetching (multi-session data management)

Every fetch is recorded as a row in `fetch_runs` capturing the full query:
keywords, subreddits, time window (relative filter *or* explicit
`after`/`before` epoch bounds), source, limits, started/finished timestamps,
and the fetched/inserted counts. The `fetch_run_comments` link table records
which run(s) returned which comment, so:

- overlapping sessions **merge automatically** — comments are unique per
  `(topic_id, reddit_id)` and `INSERT ... ON CONFLICT DO NOTHING` dedupes;
- a run can be **deleted** along with only the comments it exclusively
  contributed;
- the dataset can be **trimmed** by date range or minimum score, and
  **validated** (missing timestamps, empty bodies, score stats).

The same Reddit comment may legitimately belong to several topics (uniqueness
is per-topic, not global — fixed in schema v2).

### Analysis caching

`services.analyze_topic` hashes the analyzed comment ids + parameters into a
`signature` stored on each analysis row. Re-running an identical analysis
returns the saved result (`cached: true`) with **zero API calls**. Any new
comment, or a parameter change, changes the signature and triggers a fresh run.

### Upvote awareness

Comment `score` (and `controversiality` where the source provides it) is
stored. Analysis and browse accept a `min_score` filter, and every sentiment
summary includes an `upvote_weighted` breakdown where each comment is
weighted by `max(score, 1)`.

### Showcase

`showcase/builder.py` renders a fully static site (default `docs/`, ready for
GitHub Pages) from **saved** analyses only — no API calls. Per-topic
customization lives in `topics.showcase_config` (JSON): enabled flag, custom
title, description, the set/order of sections, and free-text commentary per
section. Pages embed their data as JSON and draw charts client-side with
vega-lite from a CDN, so the site works from `file://` too.

## Database schema (v2)

- `topics(id, name UNIQUE, keywords, created_at, note, showcase_config)`
- `comments(id, topic_id, reddit_id, subreddit, author, body, score,
  controversiality, permalink, created_utc, fetched_at, manual_label,
  UNIQUE(topic_id, reddit_id))`
- `fetch_runs(id, topic_id, source, keywords, subreddits, time_filter,
  after_utc, before_utc, limit_per_keyword, min_relevance, started_at,
  finished_at, status, fetched, inserted, error)`
- `fetch_run_comments(run_id, comment_id)`
- `analyses(id, topic_id, run_at, num_comments, sentiment_summary, themes,
  raw_result, params, signature)`

Migrations run in `storage/db.py::migrate()`; add a new `_migrate_vN`
function and bump `SCHEMA_VERSION` to evolve the schema. Never edit old
migrations.

## Testing

`tests/` covers storage (incl. legacy-DB migration), fetchers (HTTP mocked),
analysis math, services (fetcher/LLM mocked, temp DBs), and the showcase
builder. Run with:

```bash
.venv/bin/pytest
```

Anything touching the network or the Anthropic API must be mocked in tests.
