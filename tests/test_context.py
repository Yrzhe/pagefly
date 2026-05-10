"""Tests for agent context injection — YRZ-269 (push context) and YRZ-270 (voice context)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestInjectIngestContextVoice:
    """YRZ-270: Voice transcription should inject full transcript."""

    def _call_inject(self, tmp_path, source_type, filename, content):
        """Helper: set up mocks and call _inject_ingest_context."""
        doc_dir = tmp_path / "doc"
        doc_dir.mkdir()
        (doc_dir / "document.md").write_text(content, encoding="utf-8")

        fake_doc = {
            "id": "test-id-001",
            "title": "Test Doc",
            "source_type": source_type,
            "current_path": str(doc_dir),
        }
        fake_session = MagicMock()
        fake_session.messages = []

        with patch("src.storage.db.get_document", return_value=fake_doc), \
             patch("src.channels.telegram._get_session", return_value=fake_session), \
             patch("src.channels.telegram._persist_session"):
            from src.channels.telegram import _inject_ingest_context
            _inject_ingest_context(12345, "test-id-001", filename)

        return fake_session.messages

    def test_voice_injects_full_transcript(self, tmp_path):
        """Voice file injects full transcript, not truncated preview."""
        transcript = "This is a long voice memo transcript. " * 50  # ~1900 chars
        msgs = self._call_inject(tmp_path, "voice", "memo.ogg", transcript)

        assert len(msgs) == 1
        msg = msgs[0]
        assert "Voice memo transcribed" in msg["content"]
        assert "Full transcript:" in msg["content"]
        assert transcript in msg["content"]

    def test_nonvoice_truncates_preview(self, tmp_path):
        """Non-voice file only injects 500 char preview."""
        long_content = "PDF content here. " * 200  # ~3600 chars
        msgs = self._call_inject(tmp_path, "pdf", "report.pdf", long_content)

        msg = msgs[0]
        assert "Content preview:" in msg["content"]
        assert "Voice memo" not in msg["content"]
        assert len(msg["content"]) < len(long_content)

    def test_voice_detected_by_filename(self, tmp_path):
        """Voice detected by .m4a extension even if source_type is empty."""
        msgs = self._call_inject(tmp_path, "", "memo.m4a", "Detected by ext")

        msg = msgs[0]
        assert "Voice memo transcribed" in msg["content"]

    def test_nonvoice_by_filename(self, tmp_path):
        """Non-voice extension uses preview mode."""
        msgs = self._call_inject(tmp_path, "", "paper.pdf", "Some content")

        msg = msgs[0]
        assert "Content preview:" in msg["content"]


class TestInjectPushContext:
    """YRZ-269: Scheduled task results should be injected into chat session."""

    def _try_import(self):
        try:
            from src.scheduler.engine import _inject_push_context
            return _inject_push_context
        except ImportError:
            pytest.skip("apscheduler not installed")

    def test_injects_context(self):
        """_inject_push_context adds system message to session."""
        fn = self._try_import()
        fake_session = MagicMock()
        fake_session.messages = []

        with patch("src.channels.telegram._get_session", return_value=fake_session), \
             patch("src.channels.telegram._persist_session"):
            fn("Daily Review", "3 new docs, 2 wiki articles updated")

        assert len(fake_session.messages) == 1
        msg = fake_session.messages[0]
        assert msg["role"] == "assistant"
        assert "Daily Review" in msg["content"]
        assert "3 new docs" in msg["content"]

    def test_skips_without_chat_id(self):
        """No crash when TELEGRAM_CHAT_ID is empty."""
        try:
            from src.scheduler.engine import _inject_push_context
        except ImportError:
            pytest.skip("apscheduler not installed")

        with patch("src.scheduler.engine.TELEGRAM_CHAT_ID", ""):
            _inject_push_context("Test", "preview")

    def test_truncates_long_preview(self):
        """Preview is truncated to 500 chars in the message."""
        fn = self._try_import()
        fake_session = MagicMock()
        fake_session.messages = []

        with patch("src.channels.telegram._get_session", return_value=fake_session), \
             patch("src.channels.telegram._persist_session"):
            fn("Compiler", "x" * 2000)

        msg = fake_session.messages[0]
        assert len(msg["content"]) < 1000
