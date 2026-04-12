"""PageFly CLI — interactive setup and utilities."""

import getpass
import json
import secrets
import sys
from pathlib import Path

import bcrypt

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.json"
CONFIG_EXAMPLE = ROOT_DIR / "config.json.example"
DATA_DIR = ROOT_DIR / "data"


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """Prompt user for input with optional default."""
    suffix = f" [{default}]" if default else ""
    prompt_text = f"  {label}{suffix}: "
    if secret:
        val = getpass.getpass(prompt_text)
    else:
        val = input(prompt_text)
    return val.strip() or default


def _hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def setup() -> None:
    """Interactive setup: generate config.json from user input."""
    print()
    print("  PageFly Setup")
    print("  " + "=" * 40)
    print()

    # Load template
    if not CONFIG_EXAMPLE.exists():
        print("  Error: config.json.example not found.")
        sys.exit(1)

    with open(CONFIG_EXAMPLE, encoding="utf-8") as f:
        cfg = json.load(f)

    # Auth
    print("  1/3  Account & Password")
    print("  " + "-" * 30)
    account = _prompt("Email", cfg["auth"]["account"])
    password = _prompt("Password (min 6 chars)", secret=True)
    while len(password) < 6:
        print("  Password must be at least 6 characters.")
        password = _prompt("Password (min 6 chars)", secret=True)

    cfg["auth"]["account"] = account
    cfg["auth"]["password_hash"] = _hash_password(password)
    cfg["auth"]["jwt_secret"] = secrets.token_hex(32)
    print()

    # API Keys
    print("  2/3  API Keys")
    print("  " + "-" * 30)
    anthropic_key = _prompt("Anthropic API Key (required)", "")
    if not anthropic_key:
        print("  Warning: Anthropic API key is required for AI features.")
        print("  You can set it later in config.json or via ANTHROPIC_API_KEY env var.")
    else:
        cfg["api_keys"]["anthropic"]["api_key"] = anthropic_key

    openai_key = _prompt("OpenAI API Key (optional, for voice transcription)", "")
    if openai_key:
        cfg["api_keys"]["openai"]["api_key"] = openai_key

    mistral_key = _prompt("Mistral API Key (optional, for image OCR)", "")
    if mistral_key:
        cfg["api_keys"]["mistral"]["api_key"] = mistral_key
    print()

    # Telegram
    print("  3/3  Telegram Bot (optional)")
    print("  " + "-" * 30)
    bot_token = _prompt("Telegram Bot Token (press Enter to skip)", "")
    if bot_token:
        cfg["telegram"]["bot_token"] = bot_token
        chat_id = _prompt("Telegram Chat ID", "")
        if chat_id:
            cfg["telegram"]["chat_id"] = chat_id
    print()

    # API token
    cfg["api"]["master_token"] = secrets.token_hex(24)

    # Write config
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Ensure data directories
    for d in ["raw", "knowledge", "wiki", "inbox", "workspace"]:
        (DATA_DIR / d).mkdir(parents=True, exist_ok=True)

    # Offer to load demo data
    print()
    load_demo_answer = _prompt("Load demo data? (shows a working knowledge base) [Y/n]", "Y")
    if load_demo_answer.lower() not in ("n", "no"):
        try:
            from src import demo
            demo.load()
        except Exception as e:
            print(f"  Could not load demo data: {e}")
            print("  You can try again later with: python -m src.demo load")

    print("  " + "=" * 40)
    print("  Setup complete!")
    print()
    print(f"  Config saved to: {CONFIG_PATH}")
    print(f"  Account: {account}")
    print(f"  Master Token: {cfg['api']['master_token']}")
    print()
    print("  Next steps:")
    print("    docker compose up -d")
    print("    Open http://localhost (or your configured port)")
    print()


def hash_pw() -> None:
    """Hash a password and print the result (utility command)."""
    password = _prompt("Password to hash", secret=True)
    if not password:
        print("  No password provided.")
        sys.exit(1)
    print(f"  Bcrypt hash: {_hash_password(password)}")
    print()


def main() -> None:
    """CLI entry point."""
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print()
        print("  PageFly CLI")
        print()
        print("  Usage:")
        print("    python -m src.cli setup         Interactive setup (generates config.json)")
        print("    python -m src.cli hash-pw       Hash a password for config.json")
        print("    python -m src.cli load-demo     Load demo documents & wiki")
        print("    python -m src.cli clear-demo    Remove demo data")
        print("    python -m src.cli help          Show this help message")
        print()
        sys.exit(0)

    cmd = args[0]
    if cmd == "setup":
        setup()
    elif cmd == "hash-pw":
        hash_pw()
    elif cmd == "load-demo":
        from src import demo
        demo.load()
    elif cmd == "clear-demo":
        from src import demo
        demo.clear()
    else:
        print(f"  Unknown command: {cmd}")
        print("  Run 'python -m src.cli help' for available commands.")
        sys.exit(1)


if __name__ == "__main__":
    main()
