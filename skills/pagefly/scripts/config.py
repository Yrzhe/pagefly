"""PageFly skill configuration."""

import json
import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_CONFIG = SKILL_DIR / "config.json"
USER_CONFIG = Path.home() / ".config" / "pagefly" / "config.json"

def load_config() -> dict:
    """Load config. Priority: env vars > skill dir config.json > ~/.config/pagefly/config.json"""
    config = {"url": "", "token": ""}

    # Try ~/.config/pagefly/config.json
    if USER_CONFIG.exists():
        with open(USER_CONFIG) as f:
            config.update(json.load(f))

    # Skill directory config.json overrides
    if SKILL_CONFIG.exists():
        with open(SKILL_CONFIG) as f:
            loaded = json.load(f)
            if loaded.get("url"):
                config["url"] = loaded["url"]
            if loaded.get("token"):
                config["token"] = loaded["token"]

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
        "User-Agent": "PageFly-Skill/1.0",
    }
