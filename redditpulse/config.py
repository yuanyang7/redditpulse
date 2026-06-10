"""Central configuration for RedditPulse.

All tunables live here so the rest of the codebase never reads environment
variables or hardcodes paths/model names directly. Values come from the
environment (a local .env is loaded once at import) with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings, resolved from the environment."""

    # Storage
    db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("REDDITPULSE_DB", "redditpulse.db"))
    )

    # Anthropic / Claude
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY")
    )
    claude_model: str = field(
        default_factory=lambda: os.environ.get(
            "REDDITPULSE_CLAUDE_MODEL", "claude-haiku-4-5-20251001"
        )
    )

    # Reddit (PRAW)
    reddit_client_id: str | None = field(
        default_factory=lambda: os.environ.get("REDDIT_CLIENT_ID")
    )
    reddit_client_secret: str | None = field(
        default_factory=lambda: os.environ.get("REDDIT_CLIENT_SECRET")
    )
    reddit_user_agent: str = field(
        default_factory=lambda: os.environ.get("REDDIT_USER_AGENT", "redditpulse/0.2")
    )

    # Showcase static site
    showcase_output_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("REDDITPULSE_SHOWCASE_DIR", "docs"))
    )

    def require_anthropic_key(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file."
            )
        return self.anthropic_api_key


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def override_settings(settings: Settings) -> None:
    """Replace the settings singleton (used by tests)."""
    global _settings
    _settings = settings
