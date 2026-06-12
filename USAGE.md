# Usage

Detailed setup, CLI reference, and development notes. For a quick overview,
see [README.md](README.md).

## Setup

```bash
# 1. Create and activate virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Install (add [dev] for the test suite)
pip install -e ".[dev]"

# 3. Configure credentials
cp .env.example .env
# Edit .env with your Anthropic API key (and optionally Reddit API keys)
```

### Getting API keys

**Anthropic** (required for keyword generation and theme analysis): go to
https://console.anthropic.com → create an API key.

**Reddit** (optional — only for the `praw` source): go to
https://www.reddit.com/prefs/apps → create a "script" app → copy client ID and
secret. The default `arctic` source (Arctic Shift archive) needs no
credentials.

## GUI

```bash
redditpulse-gui
```

Tabs: **Dashboard** (overview + latest analysis), **Trends** (sentiment over
time), **Analyze** (run analyses; min-upvote filter; cached results reused
automatically), **Browse**, **Data** (fetch-run history, data-quality report,
trim), **Label**/**Evaluate** (ground-truth labeling and model benchmarking),
**Showcase** (configure + build the static site), **Export**.

## CLI

### Search (fetch comments)

```bash
# Search a topic — auto-generates keywords via Claude, fetches comments
redditpulse search "AI and privacy"

# Specific subreddits, relative window
redditpulse search "AI and privacy" -s technology,privacy -t week

# A specific timeline instead of "the past N days"
redditpulse search "AI and privacy" --after 2025-01-01 --before 2025-03-31 --refresh

# Choose the data source: arctic (default, no credentials), praw, rss
redditpulse search "AI and privacy" --source praw

# Fetch more comments for an existing topic (merged + deduplicated)
redditpulse search "AI and privacy" --refresh

# Clear old comments and re-fetch fresh ones
redditpulse search "AI and privacy" --reset-comments

# Filter off-topic comments by semantic relevance
redditpulse search "AI and privacy" --min-relevance 0.3
```

Time filter options (`-t`): `hour`, `day`, `week`, `month`, `6months`,
`year`, `all` — or use `--after`/`--before` ISO dates for an exact range.

Every fetch is recorded as a *run* with its full parameters; overlapping
fetches merge automatically (deduplicated per topic by Reddit id).

### Analyze

```bash
# Full analysis — sentiment + Claude themes/opinions/insights
redditpulse analyze "AI and privacy"

# Claude-based sentiment (better at sarcasm), only well-upvoted comments
redditpulse analyze "AI and privacy" -m claude --min-score 5

# Sentiment only — free, no Claude API call
redditpulse analyze "AI and privacy" --sentiment-only
```

Results include an **upvote-weighted** sentiment breakdown (each comment
weighted by its score). Re-running an identical analysis (same comments, same
settings) returns the saved result with **no API calls**.

### Data management

```bash
redditpulse runs "AI and privacy"        # fetch-run history with parameters
redditpulse validate "AI and privacy"    # data-quality report
redditpulse trim "AI and privacy" --delete-before 2024-06-01 --min-score 1
```

### Browse / Export / Topics

```bash
redditpulse browse "AI and privacy" --sentiment negative --min-score 3
redditpulse export "AI and privacy" -o results.json
redditpulse topics
```

## Showcase site (GitHub Pages)

Build a fully static site from saved analyses (no API calls):

```bash
redditpulse showcase            # writes docs/
```

Per-topic pages show sentiment (incl. upvote-weighted), key opinions, themes,
emotions, and top comments — each section toggleable, orderable and
annotatable per topic from the GUI's **Showcase** tab (or
`services.set_showcase_config`). The same tab's "Manage published topics"
panel controls which topics appear and in what order.

To publish: commit `docs/` and enable GitHub Pages (Settings → Pages → deploy
from branch → `/docs` folder).

## Development

```bash
pytest                  # run the test suite (network and LLM calls are mocked)
```

- Layered design: `storage/` → `fetchers/`+`analysis/` → `services/` →
  CLI/GUI/showcase. Callers only import `redditpulse.services`. See
  [ARCHITECTURE.md](ARCHITECTURE.md) for details.
- Schema migrations are versioned (`PRAGMA user_version`) and run
  automatically; old databases upgrade in place.
- All Claude API calls are centralized in `analysis/llm.py`.

## Notes

- **VADER sentiment** runs fully locally — free, no API needed
- **Claude API** is used for keyword generation, theme analysis, and optional
  LLM sentiment (~$0.01 per run with the default Haiku model)
- The SQLite database (`redditpulse.db`) stores comments, fetch runs, and
  analysis history locally
