# RedditPulse

Fetch and analyze Reddit comments on any topic. Auto-generates search keywords, collects comments, runs sentiment analysis (VADER), and extracts themes/opinions/emotions via Claude API.

## Setup

```bash
# 1. Install
pip install -e .

# 2. Configure credentials
cp .env.example .env
# Edit .env with your Reddit API + Anthropic API keys
```

### Getting API Keys

**Reddit**: Go to https://www.reddit.com/prefs/apps → create a "script" app → copy client ID and secret.

**Anthropic**: Go to https://console.anthropic.com → create an API key.

## Usage

```bash
# Search for a topic (auto-generates keywords, fetches comments)
redditpulse search "AI and privacy"

# Search in specific subreddits
redditpulse search "AI and privacy" -s technology,privacy -t week

# Fetch more comments for an existing topic
redditpulse search "AI and privacy" --refresh

# Analyze stored comments
redditpulse analyze "AI and privacy"

# Save results to JSON
redditpulse analyze "AI and privacy" -o results.json

# List all tracked topics
redditpulse topics
```

## Output

The analysis produces:
- **Sentiment breakdown** — positive/neutral/negative counts + average score
- **Top themes** — ranked by prevalence with summaries
- **Emotions** — ranked emotional tones in the discussion
- **Key opinions** — stances with strength ratings
- **Controversy level** — how divisive the topic is
- **Key insights** — 3-5 main takeaways
