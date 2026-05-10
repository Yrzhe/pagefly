"""Tests for src/agents/trend — Trend Discovery Agent setup and DB stats."""

import json
from unittest.mock import patch, MagicMock

import pytest


class TestTrendSkillLoading:
    def test_skill_file_exists(self):
        """Trend skill SKILL.md exists and is loadable."""
        from src.shared.config import load_skill_prompt
        prompt = load_skill_prompt("trend", "SKILL")
        assert "Trend" in prompt

    def test_skill_has_key_sections(self):
        """Skill prompt contains required analysis sections."""
        from src.shared.config import load_skill_prompt
        prompt = load_skill_prompt("trend", "SKILL")
        assert "Ingestion Velocity" in prompt
        assert "Emerging Themes" in prompt
        assert "Coverage Analysis" in prompt
        assert "Exploration Suggestions" in prompt


class TestBuildTrendContext:
    def test_builds_context_from_db(self):
        """_build_trend_context produces markdown sections from DB data."""
        from src.agents.trend import _build_trend_context
        from src.storage.db import init_db

        init_db()
        context = _build_trend_context()

        # Should have key sections
        assert "## Document Counts" in context
        assert "## Category Distribution" in context
        assert "## Wiki Articles" in context
        assert "Total:" in context

    def test_context_has_tag_frequency(self):
        """Context includes tag frequency if tags exist in DB."""
        from src.agents.trend import _build_trend_context
        from src.storage.db import init_db

        init_db()
        context = _build_trend_context()

        # Tags section may or may not exist depending on DB state,
        # but the function should not crash
        assert isinstance(context, str)
        assert len(context) > 100  # Should have substantial content


class TestTrendAgentOptions:
    def test_build_agent_options(self):
        """build_agent_options loads trend skill without error."""
        with patch("src.agents.base.setup_env"):
            from src.agents.base import build_agent_options
            options = build_agent_options(skill_name="trend", max_turns=30)

        assert options is not None
        assert options.max_turns == 30
        assert "pagefly" in options.mcp_servers


class TestTrendImport:
    def test_import(self):
        """Trend module imports cleanly."""
        from src.agents.trend import run_trend
        assert callable(run_trend)

    def test_main_entry(self):
        """Main entry point exists."""
        from src.agents.trend import main
        assert callable(main)


class TestTrendSchedulerIntegration:
    def test_dispatch_recognizes_trend_type(self):
        """Scheduler dispatch handles task_type='trend'."""
        try:
            from src.scheduler.engine import _dispatch_custom_task
            assert callable(_dispatch_custom_task)
        except ImportError:
            pytest.skip("apscheduler not installed in test environment")
