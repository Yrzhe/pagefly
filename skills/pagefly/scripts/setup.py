"""Interactive setup for PageFly skill."""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "pagefly"
CONFIG_FILE = CONFIG_DIR / "config.json"


def main():
    print("PageFly Skill Setup")
    print("=" * 40)

    url = input("PageFly URL (e.g. https://api.pagefly.ink): ").strip().rstrip("/")
    token = input("API Token (from Dashboard > API & Tokens): ").strip()

    if not url or not token:
        print("Error: URL and token are required.")
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = {"url": url, "token": token}
    CONFIG_FILE.write_text(json.dumps(config, indent=2))

    print(f"\nConfig saved to {CONFIG_FILE}")
    print("You can now use /pagefly commands in Claude Code.")


if __name__ == "__main__":
    main()
