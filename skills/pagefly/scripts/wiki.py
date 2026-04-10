"""List wiki articles compiled by the agent."""

import json
import urllib.request

from config import get_url, get_headers


def main():
    url = f"{get_url()}/api/wiki"
    req = urllib.request.Request(url, headers=get_headers())

    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())

    articles = result.get("articles", [])
    print(f"Wiki Articles: {len(articles)}\n")
    for a in articles:
        atype = a.get("article_type", "")
        print(f"  [{atype}] {a['title']}")
        print(f"    ID: {a['id']}\n")


if __name__ == "__main__":
    main()
