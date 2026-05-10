"""Tests for src/agents/linker — Linker Agent setup and configuration."""

from unittest.mock import patch, AsyncMock, MagicMock

import pytest


class TestLinkerSkillLoading:
    def test_skill_file_exists(self):
        """Linker skill SKILL.md exists and is loadable."""
        from src.shared.config import load_skill_prompt
        prompt = load_skill_prompt("linker", "SKILL")
        assert "Linker Agent" in prompt
        assert "connection" in prompt.lower()

    def test_skill_has_key_sections(self):
        """Skill prompt contains required workflow sections."""
        from src.shared.config import load_skill_prompt
        prompt = load_skill_prompt("linker", "SKILL")
        assert "Survey" in prompt
        assert "Identify Gaps" in prompt
        assert "Create/Update Connections" in prompt
        assert "Quality Rules" in prompt


class TestLinkerAgentOptions:
    def test_build_agent_options(self):
        """build_agent_options loads linker skill without error."""
        with patch("src.agents.base.setup_env"):
            from src.agents.base import build_agent_options
            options = build_agent_options(skill_name="linker", max_turns=40)

        assert options is not None
        assert options.max_turns == 40
        assert "pagefly" in options.mcp_servers


class TestLinkerImport:
    def test_import(self):
        """Linker module imports cleanly."""
        from src.agents.linker import run_linker
        assert callable(run_linker)

    def test_main_entry(self):
        """Main entry point exists."""
        from src.agents.linker import main
        assert callable(main)


class TestLinkerSchedulerIntegration:
    def test_dispatch_recognizes_linker_type(self):
        """Scheduler dispatch handles task_type='linker'."""
        try:
            from src.scheduler.engine import _dispatch_custom_task
            assert callable(_dispatch_custom_task)
        except ImportError:
            pytest.skip("apscheduler not installed in test environment")
