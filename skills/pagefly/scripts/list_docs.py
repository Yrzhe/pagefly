"""List documents in your knowledge base."""

import json
import sys
import urllib.request

from config import get_url, get_headers


def main():
    category = sys.argv[1] if len(sys.argv) > 1 else ""
    params = "limit=50"
    if category:
        params += f"&category={category}"

    url = f"{get_url()}/api/documents?{params}"
    req = urllib.request.Request(url, headers=get_headers())

    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    docs = result.get("documents", [])
    total = result.get("total", len(docs))
    print(f"Documents: {total}\n")
    for d in docs:
        cat = f" [{d.get('category', '')}]" if d.get('category') else ""
        print(f"  {d['title']}{cat}")
        print(f"    ID: {d['id']}  Status: {d.get('status', '-')}\n")


if __name__ == "__main__":
    main()
