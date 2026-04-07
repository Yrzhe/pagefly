"""Start the Telegram bot."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.channels.telegram import run_bot

if __name__ == "__main__":
    run_bot()
