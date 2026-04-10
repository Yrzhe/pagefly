"""Show knowledge base statistics."""

import json
import urllib.request

from config import get_url, get_headers


def main():
    url = f"{get_url()}/api/stats"
    req = urllib.request.Request(url, headers=get_headers())

    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())

    print("PageFly Knowledge Base Stats")
    print("=" * 35)
    print(f"  Documents:       {result.get('documents', 0)}")
    print(f"  Wiki Articles:   {result.get('wiki_articles', 0)}")
    print(f"  Operations:      {result.get('operations', 0)}")
    print(f"  Schedules:       {result.get('scheduled_tasks', 0)}")

    cats = result.get("categories", {})
    if cats:
        print(f"\n  Categories:")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"    {cat}: {count}")


if __name__ == "__main__":
    main()
