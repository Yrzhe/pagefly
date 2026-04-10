"""Ask a question to your PageFly knowledge base agent."""

import json
import sys
import urllib.request

from config import get_url, get_headers


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 query.py <question>")
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    url = f"{get_url()}/api/query"
    data = json.dumps({"question": question}).encode()
    req = urllib.request.Request(url, data=data, headers=get_headers(), method="POST")

    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())

    print(result.get("answer", "No answer returned."))


if __name__ == "__main__":
    main()
