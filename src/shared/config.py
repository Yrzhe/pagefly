"""Configuration — loads from config.json, with env var overrides."""

import json
import os
from pathlib import Path


# Project root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"


def _env(key: str, default: str = "") -> str:
    """Get env var, return empty string if not set or placeholder."""
    val = os.environ.get(key, "")
    if val and val not in ("xxx", "sk-xxx", "sk-ant-xxx", "change-this-to-a-secure-token"):
        return val
    return default

# Data directories
RAW_DIR = DATA_DIR / "raw"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
WIKI_DIR = DATA_DIR / "wiki"
INBOX_DIR = DATA_DIR / "inbox"
WORKSPACE_DIR = DATA_DIR / "workspace"


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

# API Keys & Base URLs (env vars override config.json)
ANTHROPIC_API_KEY: str = _env("ANTHROPIC_API_KEY", _cfg["api_keys"]["anthropic"]["api_key"])
ANTHROPIC_BASE_URL: str = _env("ANTHROPIC_BASE_URL", _cfg["api_keys"]["anthropic"].get("base_url", "https://api.anthropic.com"))
OPENAI_API_KEY: str = _env("OPENAI_API_KEY", _cfg["api_keys"]["openai"]["api_key"])
OPENAI_BASE_URL: str = _env("OPENAI_BASE_URL", _cfg["api_keys"]["openai"].get("base_url", "https://api.openai.com/v1"))
MISTRAL_API_KEY: str = _env("MISTRAL_API_KEY", _cfg["api_keys"]["mistral"]["api_key"])
MISTRAL_BASE_URL: str = _env("MISTRAL_BASE_URL", _cfg["api_keys"]["mistral"].get("base_url", "https://api.mistral.ai"))

# Telegram
TELEGRAM_BOT_TOKEN: str = _env("TELEGRAM_BOT_TOKEN", _cfg["telegram"]["bot_token"])
TELEGRAM_CHAT_ID: str = _env("TELEGRAM_CHAT_ID", _cfg["telegram"]["chat_id"])

# Database
DATABASE_URL: str = _env("DATABASE_URL", _cfg["database"]["url"])

# Models
CLASSIFIER_MODEL: str = _cfg["models"]["classifier"]
AGENT_MODEL: str = _cfg["models"]["agent"]
TRANSCRIPTION_MODEL: str = _cfg["models"].get("transcription", "gpt-4o-transcribe")

# Watcher
_watcher = _cfg.get("watcher", {})
WATCHER_INBOX_DIR: Path = ROOT_DIR / _watcher.get("inbox_dir", "data/inbox")
WATCHER_PARALLEL_LIMIT: int = _watcher.get("parallel_limit", 3)

# Scheduler (cron expressions)
_scheduler = _cfg.get("scheduler", {})
SCHEDULE_DAILY_REVIEW: str = _scheduler.get("daily_review", "0 22 * * *")
SCHEDULE_WEEKLY_REVIEW: str = _scheduler.get("weekly_review", "0 22 * * 0")
SCHEDULE_MONTHLY_REVIEW: str = _scheduler.get("monthly_review", "0 22 1 * *")
SCHEDULE_COMPILER: str = _scheduler.get("compiler", "0 2 * * *")
SCHEDULE_CHAT_ARCHIVE: str = _scheduler.get("chat_archive", "55 23 * * *")

# Notifications
_notifications = _cfg.get("notifications", {})
NOTIFY_TELEGRAM: bool = _notifications.get("telegram", False)

# API
_api = _cfg.get("api", {})
API_PORT: int = int(_env("API_PORT", str(_api.get("port", 8000))))
API_MASTER_TOKEN: str = _env("API_MASTER_TOKEN", _api.get("master_token", ""))
API_MAX_UPLOAD_MB: int = _api.get("max_upload_mb", 50)

# App
LOG_LEVEL: str = _env("LOG_LEVEL", _cfg["app"]["log_level"])


def load_categories() -> dict:
    """Load category definitions."""
    path = CONFIG_DIR / "categories.json"
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


def load_skill_prompt(name: str, prompt_name: str) -> str:
    """Load a specific prompt file from a skill folder."""
    path = CONFIG_DIR / "skills" / name / f"{prompt_name}.md"
    with open(path, encoding="utf-8") as f:
        return f.read()
