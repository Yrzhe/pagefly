"""Phase 0 gate: HTML <-> Markdown conversion must survive the Tiptap editor's
full feature set (headings, marks, lists, quote, code, table, image, link).

If any of these lose content, anchoring (Phase 1) cannot be built on top, so
this test is the gate for the whole AI-suggestion feature.
"""

import pytest

from src.shared import md
from src.storage import db


# Representative Tiptap getHTML() output covering every toolbar feature.
EDITOR_HTML = (
    "<h1>Title</h1>"
    "<h2>Section</h2>"
    "<h3>Sub</h3>"
    "<p>Plain with <strong>bold</strong>, <em>italic</em>, "
    "<s>strike</s> and <code>inline</code>.</p>"
    "<ul><li>bullet one</li><li>bullet two</li></ul>"
    "<ol><li>first</li><li>second</li></ol>"
    "<blockquote><p>a quote</p></blockquote>"
    "<pre><code>code block line</code></pre>"
    "<hr>"
    '<p><a href="https://example.com">a link</a></p>'
    '<img src="https://example.com/i.png" alt="pic">'
    "<table><tbody>"
    "<tr><th>H1</th><th>H2</th></tr>"
    "<tr><td>r1c1</td><td>r1c2</td></tr>"
    "</tbody></table>"
)


class TestHtmlToMarkdown:
    def test_headings(self):
        out = md.html_to_markdown(EDITOR_HTML)
        assert "# Title" in out
        assert "## Section" in out
        assert "### Sub" in out

    def test_inline_marks(self):
        out = md.html_to_markdown(EDITOR_HTML)
        assert "**bold**" in out
        assert "*italic*" in out
        assert "`inline`" in out

    def test_lists_keep_ordered_vs_bullet(self):
        out = md.html_to_markdown(EDITOR_HTML)
        assert "- bullet one" in out
        assert "- bullet two" in out
        assert "1. first" in out
        assert "2. second" in out

    def test_blockquote_and_codeblock(self):
        out = md.html_to_markdown(EDITOR_HTML)
        assert "> a quote" in out
        assert "code block line" in out

    def test_link_survives(self):
        out = md.html_to_markdown(EDITOR_HTML)
        assert "[a link](https://example.com)" in out

    def test_image_survives(self):
        out = md.html_to_markdown(EDITOR_HTML)
        assert "https://example.com/i.png" in out

    def test_table_survives(self):
        """The regex converter dropped tables entirely — this is the key gate."""
        out = md.html_to_markdown(EDITOR_HTML)
        assert "H1" in out and "H2" in out
        assert "r1c1" in out and "r1c2" in out
        assert "|" in out  # GFM table pipe syntax


class TestMarkdownToHtml:
    def test_roundtrip_preserves_text_content(self):
        markdown = md.html_to_markdown(EDITOR_HTML)
        html = md.markdown_to_html(markdown)
        for token in ("Title", "bold", "italic", "bullet one",
                      "first", "a quote", "code block line",
                      "a link", "r1c1", "r1c2"):
            assert token in html, f"round-trip lost: {token!r}"


@pytest.fixture(autouse=True)
def _init_db(tmp_path, monkeypatch):
    """Use a temporary database for each storage test."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


class TestMarkdownCanonicalStorage:
    """content_md is the canonical anchor truth, derived from the HTML on write."""

    def test_insert_populates_content_md(self):
        db.insert_workspace_document("ws-1", title="T", content="<h1>Hello</h1><p>body</p>")
        doc = db.get_workspace_document("ws-1")
        assert doc["content"] == "<h1>Hello</h1><p>body</p>"  # HTML preserved
        assert "# Hello" in doc["content_md"]
        assert "body" in doc["content_md"]

    def test_update_content_rederives_md(self):
        db.insert_workspace_document("ws-1", title="T", content="<p>old</p>")
        db.update_workspace_document("ws-1", content="<h2>new</h2>")
        doc = db.get_workspace_document("ws-1")
        assert "## new" in doc["content_md"]
        assert "old" not in doc["content_md"]

    def test_update_without_content_keeps_md(self):
        db.insert_workspace_document("ws-1", title="T", content="<p>keep</p>")
        db.update_workspace_document("ws-1", title="New Title")
        doc = db.get_workspace_document("ws-1")
        assert doc["title"] == "New Title"
        assert "keep" in doc["content_md"]

    def test_empty_content_safe(self):
        db.insert_workspace_document("ws-1", title="Empty")
        doc = db.get_workspace_document("ws-1")
        assert doc["content_md"] == ""
