"""Configuration — loads from config.json and config files."""

import json
from pathlib import Path


# Project root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"

# Data directories
RAW_DIR = DATA_DIR / "raw"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
WIKI_DIR = DATA_DIR / "wiki"


def _load_config() -> dict:
    """Load config.json. Raise if not found."""
    path = ROOT_DIR / "config.json"
    if not path.exists():
        raise FileNotFoundError(
            f"config.json not found at {path}. "
            "Copy config.json.example to config.json and fill in your keys."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_cfg = _load_config()

# API Keys & Base URLs
ANTHROPIC_API_KEY: str = _cfg["api_keys"]["anthropic"]["api_key"]
ANTHROPIC_BASE_URL: str = _cfg["api_keys"]["anthropic"].get("base_url", "https://api.anthropic.com")
OPENAI_API_KEY: str = _cfg["api_keys"]["openai"]["api_key"]
OPENAI_BASE_URL: str = _cfg["api_keys"]["openai"].get("base_url", "https://api.openai.com/v1")
MISTRAL_API_KEY: str = _cfg["api_keys"]["mistral"]["api_key"]
MISTRAL_BASE_URL: str = _cfg["api_keys"]["mistral"].get("base_url", "https://api.mistral.ai")

# Telegram
TELEGRAM_BOT_TOKEN: str = _cfg["telegram"]["bot_token"]
TELEGRAM_CHAT_ID: str = _cfg["telegram"]["chat_id"]

# Database
DATABASE_URL: str = _cfg["database"]["url"]

# Models
CLASSIFIER_MODEL: str = _cfg["models"]["classifier"]
AGENT_MODEL: str = _cfg["models"]["agent"]

# App
LOG_LEVEL: str = _cfg["app"]["log_level"]
SCAN_INTERVAL_MINUTES: int = _cfg["app"]["scan_interval_minutes"]


def load_categories() -> dict:
    """Load category definitions."""
    path = CONFIG_DIR / "categories.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_schedules() -> dict:
    """Load scheduled task configuration."""
    path = CONFIG_DIR / "schedules.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_prompt(name: str) -> str:
    """Load a prompt template file."""
    path = CONFIG_DIR / "prompts" / f"{name}.md"
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_skill(name: str) -> str:
    """Load a skill's SKILL.md content."""
    path = CONFIG_DIR / "skills" / name / "SKILL.md"
    with open(path, encoding="utf-8") as f:
        return f.read()
