# RedditPulse

Fetch and analyze Reddit comments on any topic. Auto-generates search keywords, collects comments, runs sentiment analysis (VADER), and extracts themes/opinions/emotions via Claude API.

## Setup

```bash
# 1. Create and activate virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Install
pip install -e .

# 3. Configure credentials
cp .env.example .env
# Edit .env with your Reddit API + Anthropic API keys
```

### Getting API Keys

**Reddit**: Go to https://www.reddit.com/prefs/apps → create a "script" app → copy client ID and secret. Note: Reddit requires developer registration approval, which may take a few days.

**Anthropic**: Go to https://console.anthropic.com → create an API key.

## Usage

### Search (fetch comments)

```bash
# Search for a topic — auto-generates keywords via Claude, fetches comments
.venv/bin/redditpulse search "AI and privacy"

# Use public JSON API instead of PRAW (no Reddit credentials needed)
.venv/bin/redditpulse search "AI and privacy" --public

# Search in specific subreddits
.venv/bin/redditpulse search "AI and privacy" -s technology,privacy -t week

# Fetch more comments for an existing topic
.venv/bin/redditpulse search "AI and privacy" --refresh

# Clear old comments and re-fetch fresh ones (keeps keywords, clears analyses too)
.venv/bin/redditpulse search "AI and privacy" --reset-comments
```

**Time filter options** (`-t`): `hour`, `day`, `week`, `month`, `year`, `all`

### Analyze

```bash
# Full analysis — VADER sentiment + Claude themes/opinions/insights
.venv/bin/redditpulse analyze "AI and privacy"

# Sentiment only — free, no Claude API call
.venv/bin/redditpulse analyze "AI and privacy" --sentiment-only

# Clear old analyses before running
.venv/bin/redditpulse analyze "AI and privacy" --reset-analyses
```

### Export

```bash
# Export last saved analysis to JSON without re-running Claude
.venv/bin/redditpulse export "AI and privacy" -o results.json
```

### Browse

```bash
# Browse comments by sentiment (default: negative)
.venv/bin/redditpulse browse "AI and privacy" --sentiment negative
.venv/bin/redditpulse browse "AI and privacy" --sentiment positive
.venv/bin/redditpulse browse "AI and privacy" --sentiment neutral

# Limit how many comments to show
.venv/bin/redditpulse browse "AI and privacy" --sentiment negative --limit 10
```

### Topics

```bash
# List all tracked topics with comment counts
.venv/bin/redditpulse topics
```

## Output

Full analysis produces:
- **Sentiment breakdown** — positive/neutral/negative counts + average VADER score
- **Top themes** — ranked by prevalence with summaries
- **Emotions** — ranked emotional tones in the discussion
- **Key opinions** — stances with strength ratings
- **Controversy level** — how divisive the topic is
- **Key insights** — 3-5 main takeaways

## Notes

- **VADER sentiment** runs fully locally — free, no API needed
- **Claude API** is only called for keyword generation and theme analysis (~$0.01 per run)
- Comments are deduplicated by Reddit ID across fetches
- The SQLite database (`redditpulse.db`) stores all comments and analysis history locally
