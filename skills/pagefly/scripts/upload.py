"""Upload a file to your PageFly knowledge base."""

import json
import sys
import os
import urllib.request
from pathlib import Path

from config import get_url, get_token


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 upload.py <file_path>")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    url = f"{get_url()}/api/ingest"
    boundary = "----PageFlyUploadBoundary"

    file_data = file_path.read_bytes()
    filename = file_path.name

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {get_token()}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    print(f"Uploading {filename} ({len(file_data)} bytes)...")

    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())

    doc_id = result.get("doc_id", "")
    title = result.get("title", filename)
    print(f"Uploaded: {title}")
    print(f"Document ID: {doc_id}")
    print("The file will be automatically classified and added to your knowledge base.")


if __name__ == "__main__":
    main()
