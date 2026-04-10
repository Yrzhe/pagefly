"""Read full content of a document or wiki article."""

import json
import sys
import urllib.request

from config import get_url, get_headers


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 read_doc.py <document_id> [--wiki]")
        sys.exit(1)

    doc_id = sys.argv[1]
    is_wiki = "--wiki" in sys.argv

    endpoint = "wiki" if is_wiki else "documents"
    url = f"{get_url()}/api/{endpoint}/{doc_id}"
    req = urllib.request.Request(url, headers=get_headers())

    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    title = result.get("title", "Untitled")
    content = result.get("content", "")
    category = result.get("category", "")

    print(f"# {title}")
    if category:
        print(f"Category: {category}")
    print(f"ID: {doc_id}")
    print("---\n")
    print(content)


if __name__ == "__main__":
    main()
