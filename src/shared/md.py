"""HTML <-> Markdown conversion for Workspace documents.

Markdown is the canonical storage form (anchors/suggestions resolve against it,
per docs/workspace spec §7.1 GFM). The Tiptap editor works in HTML, so we
convert on save (HTML->MD) and on load (MD->HTML).

Uses `markdownify` + `markdown` (already project deps) instead of the lossy
inline regex previously in the /ingest endpoint — that one dropped tables,
images and links, which would break anchoring.
"""

from __future__ import annotations

import markdown as _markdown
from markdownify import markdownify as _markdownify

_MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "nl2br"]


def html_to_markdown(html: str) -> str:
    """Convert Tiptap editor HTML to canonical GFM markdown."""
    if not html:
        return ""
    out = _markdownify(
        html,
        heading_style="ATX",   # "# h1" not underline style
        bullets="-",            # stable bullet marker
        strip=["span"],         # Tiptap wraps marks in spans we don't need
    )
    # Collapse the runs of blank lines markdownify can emit around blocks.
    lines = [ln.rstrip() for ln in out.splitlines()]
    cleaned: list[str] = []
    blank = 0
    for ln in lines:
        if ln == "":
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        cleaned.append(ln)
    return "\n".join(cleaned).strip()


def markdown_to_html(md_text: str) -> str:
    """Render canonical markdown back to HTML for the editor."""
    if not md_text:
        return ""
    return _markdown.markdown(md_text, extensions=_MD_EXTENSIONS)
