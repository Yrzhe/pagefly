"""PageFly skill configuration."""

import json
import os
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "pagefly" / "config.json"

def load_config() -> dict:
    """Load config from file, falling back to env vars."""
    config = {"url": "", "token": ""}

    # Try config file first
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config.update(json.load(f))

    # Env vars override
    if os.environ.get("PAGEFLY_URL"):
        config["url"] = os.environ["PAGEFLY_URL"]
    if os.environ.get("PAGEFLY_TOKEN"):
        config["token"] = os.environ["PAGEFLY_TOKEN"]

    if not config["url"] or not config["token"]:
        raise ValueError(
            "PageFly not configured.\n\n"
            "Option 1: Set environment variables:\n"
            "  export PAGEFLY_URL='https://your-instance.com'\n"
            "  export PAGEFLY_TOKEN='pf_your_token'\n\n"
            "Option 2: Run setup:\n"
            "  python3 skills/pagefly/scripts/setup.py"
        )

    return config


def get_url() -> str:
    return load_config()["url"].rstrip("/")


def get_token() -> str:
    return load_config()["token"]


def get_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }
