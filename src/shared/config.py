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


def _default_config() -> dict:
    """Return a minimal config scaffold when config.json is absent.

    This lets users run PageFly with env vars only — no config file required
    for a minimal deployment. Only ANTHROPIC_API_KEY, PAGEFLY_EMAIL, and
    PAGEFLY_PASSWORD are needed to boot a working system.
    """
    return {
        "api_keys": {
            "anthropic": {"api_key": "", "base_url": "https://api.anthropic.com"},
            "openai": {"api_key": "", "base_url": "https://api.openai.com/v1"},
            "mistral": {"api_key": "", "base_url": "https://api.mistral.ai"},
        },
        "telegram": {"bot_token": "", "chat_id": ""},
        "database": {"url": "sqlite:///data/pagefly.db"},
        "models": {
            "classifier": "claude-sonnet-4-6",
            "agent": "claude-sonnet-4-6",
            "transcription": "gpt-4o-transcribe",
        },
        "watcher": {"inbox_dir": "data/inbox", "parallel_limit": 3},
        "scheduler": {
            "daily_review": "0 22 * * *",
            "weekly_review": "0 22 * * 0",
            "monthly_review": "0 22 1 * *",
            "compiler": "0 2 * * *",
            "chat_archive": "55 23 * * *",
        },
        "notifications": {"telegram": True},
        "api": {"port": 8000, "master_token": "", "max_upload_mb": 50},
        "auth": {
            "account": "",
            "password_hash": "",
            "totp_secret": "",
            "resend_api_key": "",
            "jwt_secret": "",
            "jwt_expiry_hours": 24,
        },
        "app": {"log_level": "INFO"},
    }


def _apply_env_overlay(cfg: dict) -> dict:
    """Allow env vars to fully replace config fields for minimal-config boots.

    - PAGEFLY_EMAIL → auth.account
    - PAGEFLY_PASSWORD → hashed into auth.password_hash (if not already set)
    """
    email = os.environ.get("PAGEFLY_EMAIL", "").strip()
    if email:
        cfg.setdefault("auth", {})["account"] = email

    password = os.environ.get("PAGEFLY_PASSWORD", "").strip()
    if password and not cfg.get("auth", {}).get("password_hash"):
        try:
            import bcrypt
            cfg.setdefault("auth", {})["password_hash"] = bcrypt.hashpw(
                password.encode(), bcrypt.gensalt()
            ).decode()
        except ImportError:
            pass

    return cfg


def _load_config() -> dict:
    """Load config.json, or fall back to defaults + env vars."""
    path = ROOT_DIR / "config.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        # No config file — rely on env vars (useful for Railway/Render deploys)
        cfg = _default_config()
    return _apply_env_overlay(cfg)


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

# Frontend
FRONTEND_ORIGIN: str = _env("FRONTEND_ORIGIN", _cfg.get("frontend", {}).get("origin", ""))

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
# API_PORT with fallback to PORT (Railway/Render/Heroku convention)
API_PORT: int = int(_env("API_PORT", _env("PORT", str(_api.get("port", 8000)))))
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
