"""URL fetcher — provides fetch functions for agent tools.

NOT a converter (not in pipeline). Agent calls these directly and decides
what to do with the result (save to workspace, ingest, or discard).

Phase A: httpx + readability (fast, static pages)
Phase B: Browser Use Cloud API (JS-rendered, agent-controlled)
"""

import re
import time
from urllib.parse import urlparse

import httpx
from markdownify import markdownify as md
from readability import Document as ReadabilityDocument

from src.shared.logger import get_logger

logger = get_logger("ingest.converters.url")

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def fetch_simple(url: str) -> dict:
    """Phase A: fetch with httpx + readability. Returns {title, markdown, url}."""
    try:
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
    except httpx.ConnectError:
        # Fallback: skip SSL verification (some envs have cert issues)
        with httpx.Client(follow_redirects=True, timeout=30, verify=False) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()

    html = resp.text
    doc = ReadabilityDocument(html)
    title = doc.title() or _title_from_url(url)
    content_html = doc.summary()

    markdown = md(content_html, heading_style="ATX", strip=["script", "style"])
    markdown = _clean_markdown(markdown)

    return {
        "title": title,
        "markdown": f"# {title}\n\n> Source: {url}\n\n{markdown}",
        "url": url,
        "char_count": len(markdown),
    }


def fetch_via_buc(url: str, task_instruction: str = "") -> dict:
    """Phase B: fetch via Browser Use Cloud API. Returns {title, markdown, url}."""
    from src.shared.config import _cfg

    buc_config = _cfg.get("api_keys", {}).get("browser_use_cloud", {})
    api_key = buc_config.get("api_key", "")

    if not api_key or api_key in ("xxx", ""):
        raise RuntimeError("Browser Use Cloud not configured (api_keys.browser_use_cloud.api_key)")

    base_url = buc_config.get("base_url", "https://api.browser-use.com/api/v1")

    if not task_instruction:
        task_instruction = f"Go to {url} and extract the main content of the page. Return the full text content in markdown format."

    with httpx.Client(timeout=120) as client:
        resp = client.post(
            f"{base_url}/run-task",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"task": task_instruction},
        )
        resp.raise_for_status()
        task_data = resp.json()
        task_id = task_data.get("id", "")

        if not task_id:
            raise RuntimeError("BUC returned no task ID")

        # Poll for result
        for _ in range(60):  # Max 120 seconds
            time.sleep(2)
            status_resp = client.get(
                f"{base_url}/task/{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()

            if status_data.get("status") == "completed":
                output = status_data.get("output", "")
                title = _title_from_url(url)
                return {
                    "title": title,
                    "markdown": f"# {title}\n\n> Source: {url}\n> Fetched via Browser Use Cloud\n\n{output}",
                    "url": url,
                    "char_count": len(output),
                }
            elif status_data.get("status") == "failed":
                raise RuntimeError(f"BUC task failed: {status_data.get('error', 'unknown')}")

    raise RuntimeError("BUC task timed out")


def _title_from_url(url: str) -> str:
    """Extract a readable title from URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path:
        segment = path.split("/")[-1]
        segment = re.sub(r'\.\w+$', '', segment)
        segment = segment.replace("-", " ").replace("_", " ")
        return segment.title() if segment else parsed.netloc
    return parsed.netloc


def _clean_markdown(text: str) -> str:
    """Clean up converted markdown."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()
