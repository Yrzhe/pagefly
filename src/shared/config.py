"""配置管理 — 从环境变量和配置文件加载。"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"

# 数据目录
RAW_DIR = DATA_DIR / "raw"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
WIKI_DIR = DATA_DIR / "wiki"

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'pagefly.db'}")

# App
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))

# 分类模型（简单调用用便宜的）
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "claude-haiku-4-5")

# Agent 模型（复杂任务用强的）
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-opus-4-6")


def load_categories() -> dict:
    """加载分类定义。"""
    path = CONFIG_DIR / "categories.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_schedules() -> dict:
    """加载定时任务配置。"""
    path = CONFIG_DIR / "schedules.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_prompt(name: str) -> str:
    """加载提示词文件。"""
    path = CONFIG_DIR / "prompts" / f"{name}.md"
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_skill(name: str) -> str:
    """加载 Skill 的 SKILL.md 内容。"""
    path = CONFIG_DIR / "skills" / name / "SKILL.md"
    with open(path, encoding="utf-8") as f:
        return f.read()
