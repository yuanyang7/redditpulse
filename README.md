# RedditPulse

### 📊 [View the live showcase](https://yuanyang7.github.io/redditpulse/)

See what Reddit really thinks about AI, jobs, gaming, and more — sentiment,
top opinions, and themes mined from real discussions.

---

RedditPulse fetches Reddit comments on any topic and uses AI to figure out
what people actually think: sentiment, themes, opinions, and emotions. Run
your own analyses and publish the results as a clean, shareable website.

## Getting started

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add your Anthropic API key
redditpulse-gui
```

The GUI walks you through searching a topic, running the analysis, and
publishing it to the showcase site.

## Learn more

- [USAGE.md](USAGE.md) — full setup, CLI reference, and showcase details
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the codebase is organized
