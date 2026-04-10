"""Send a message to the PageFly chat agent (shared with Telegram)."""

import json
import sys
import urllib.request

from config import get_url, get_headers


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 chat.py <message>")
        sys.exit(1)

    message = " ".join(sys.argv[1:])
    url = f"{get_url()}/api/chat"
    data = json.dumps({"message": message}).encode()
    req = urllib.request.Request(url, data=data, headers=get_headers(), method="POST")

    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())

    print(result.get("response", "No response."))


if __name__ == "__main__":
    main()
