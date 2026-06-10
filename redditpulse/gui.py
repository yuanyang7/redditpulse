"""Launcher for the Streamlit GUI (the app itself lives in ``ui/``)."""

import subprocess
import sys
from pathlib import Path


def main():
    """Entry point for the `redditpulse-gui` command."""
    app_path = Path(__file__).parent / "ui" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path),
                    "--server.headless=true"])


if __name__ == "__main__":
    main()
