"""Search across all documents and wiki articles."""

import json
import sys
import urllib.request

from config import get_url, get_headers


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 search.py <keyword>")
        sys.exit(1)

    keyword = " ".join(sys.argv[1:])
    url = f"{get_url()}/api/search"
    data = json.dumps({"keyword": keyword}).encode()
    req = urllib.request.Request(url, data=data, headers=get_headers(), method="POST")

    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    total = result.get("total", 0)
    print(f"Found {total} results for '{keyword}':\n")
    for r in result.get("results", []):
        print(f"  [{r['type']}] {r['title']}")
        print(f"    {r['snippet'][:120]}...")
        print(f"    ID: {r['id']}\n")


if __name__ == "__main__":
    main()
