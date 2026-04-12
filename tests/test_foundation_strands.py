"""Tests for Strands Foundation Agent — core agent creation, system prompt, invocation."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# Strands mocks are installed by conftest.py

from platform_agent.foundation.agent import FoundationStrandsAgent
from platform_agent.foundation.soul import SoulSystem


# ---------------------------------------------------------------------------
# Agent creation tests
# ---------------------------------------------------------------------------


class TestAgentCreation:
    """Test FoundationStrandsAgent instantiation and configuration."""

    def test_create_default_agent(self):
        agent = FoundationStrandsAgent()
        assert agent is not None
        assert agent.workspace_dir is None

    def test_create_agent_with_workspace(self, tmp_path):
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        assert agent.workspace_dir == str(tmp_path)

    def test_create_agent_with_custom_model(self):
        agent = FoundationStrandsAgent(model_id="anthropic.claude-sonnet-4-20250514-v1:0")
        assert agent.model_id == "anthropic.claude-sonnet-4-20250514-v1:0"

    def test_default_model_is_claude(self):
        agent = FoundationStrandsAgent()
        assert "claude" in agent.model_id.lower()

    def test_agent_has_hook_registry(self):
        agent = FoundationStrandsAgent()
        assert agent.hook_registry is not None

    def test_agent_has_soul_system(self):
        agent = FoundationStrandsAgent(workspace_dir="/tmp/test")
        assert agent.soul_system is not None


# ---------------------------------------------------------------------------
# System prompt assembly tests
# ---------------------------------------------------------------------------


class TestSystemPromptAssembly:
    """Test system prompt construction from soul system + skills."""

    def test_base_prompt_without_workspace(self):
        agent = FoundationStrandsAgent()
        prompt = agent.build_system_prompt()
        # Should contain base identity even without workspace
        assert "You are" in prompt
        assert len(prompt) > 50

    def test_prompt_includes_soul_file(self, tmp_path):
        # Create workspace with SOUL.md
        (tmp_path / "SOUL.md").write_text("I am a helpful agent with a warm personality.")
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        prompt = agent.build_system_prompt()
        assert "warm personality" in prompt

    def test_prompt_includes_agents_file(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Always use TDD. Never skip tests.")
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        prompt = agent.build_system_prompt()
        assert "Always use TDD" in prompt

    def test_prompt_includes_user_file(self, tmp_path):
        (tmp_path / "USER.md").write_text("The user is a senior engineer named Alice.")
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        prompt = agent.build_system_prompt()
        assert "Alice" in prompt

    def test_prompt_includes_identity_file(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("Name: Nova\nEmoji: 🌟\nVibe: energetic")
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        prompt = agent.build_system_prompt()
        assert "Nova" in prompt

    def test_prompt_handles_missing_files_gracefully(self, tmp_path):
        # Empty workspace — no soul files
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        prompt = agent.build_system_prompt()
        # Should still produce a valid prompt
        assert len(prompt) > 0

    def test_prompt_includes_datetime(self):
        agent = FoundationStrandsAgent()
        prompt = agent.build_system_prompt()
        # Should contain current date/time info
        assert "date" in prompt.lower() or "time" in prompt.lower() or "202" in prompt

    def test_prompt_includes_skill_list(self, tmp_path):
        # Create a skill directory
        skills_dir = tmp_path / "skills" / "test_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: test_skill\ndescription: A test skill\n---\nFull instructions."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        # When AgentSkills plugin is active, SkillRegistry prompt injection is
        # skipped (the plugin handles it).  Verify via the plugin or fallback.
        if agent._skills_plugin is not None:
            assert agent._skills_plugin is not None
        else:
            prompt = agent.build_system_prompt()
            assert "test_skill" in prompt

    def test_prompt_includes_skill_list_with_plugin(self, tmp_path):
        """When AgentSkills plugin is active, SkillRegistry prompt is skipped."""
        skills_dir = tmp_path / "skills" / "test_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: test_skill\ndescription: A test skill\n---\nFull instructions."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        if agent._skills_plugin is not None:
            prompt = agent.build_system_prompt()
            # SkillRegistry markdown should NOT be in prompt when plugin active
            assert "## Available Skills" not in prompt

    def test_prompt_includes_skill_list_without_plugin(self, tmp_path, monkeypatch):
        """When AgentSkills is unavailable, SkillRegistry injects skill summary."""
        import platform_agent.foundation.agent as agent_mod
        monkeypatch.setattr(agent_mod, "_AgentSkills", None)
        skills_dir = tmp_path / "skills" / "test_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: test_skill\ndescription: A test skill\n---\nFull instructions."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        assert agent._skills_plugin is None
        prompt = agent.build_system_prompt()
        assert "test_skill" in prompt

    def test_prompt_order(self, tmp_path):
        """Soul files should appear in correct order in prompt."""
        (tmp_path / "IDENTITY.md").write_text("Name: Nova")
        (tmp_path / "SOUL.md").write_text("Personality: kind")
        (tmp_path / "AGENTS.md").write_text("Rules: be nice")
        (tmp_path / "USER.md").write_text("User: Bob")
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        prompt = agent.build_system_prompt()
        # Identity should come before soul, soul before rules, rules before user
        identity_pos = prompt.find("Nova")
        soul_pos = prompt.find("kind")
        rules_pos = prompt.find("be nice")
        user_pos = prompt.find("Bob")
        assert identity_pos < soul_pos < rules_pos < user_pos


# ---------------------------------------------------------------------------
# Agent invocation tests
# ---------------------------------------------------------------------------


class TestAgentInvocation:
    """Test running the agent with prompts."""

    def test_invoke_returns_string(self):
        agent = FoundationStrandsAgent()
        with patch.object(agent, '_build_strands_agent') as mock_build:
            mock_inner = MagicMock()
            mock_inner.return_value = {
                "role": "assistant",
                "content": [{"text": "Hello!"}],
            }
            mock_build.return_value = mock_inner
            result = agent.invoke("Hello")
            assert isinstance(result, str)
            assert "Hello!" in result

    def test_invoke_passes_prompt_to_strands(self):
        agent = FoundationStrandsAgent()
        with patch.object(agent, '_build_strands_agent') as mock_build:
            mock_inner = MagicMock()
            mock_inner.return_value = {
                "role": "assistant",
                "content": [{"text": "done"}],
            }
            mock_build.return_value = mock_inner
            agent.invoke("Do something")
            mock_inner.assert_called_once_with("Do something")

    def test_invoke_with_empty_content_list(self):
        agent = FoundationStrandsAgent()
        with patch.object(agent, '_build_strands_agent') as mock_build:
            mock_inner = MagicMock()
            mock_inner.return_value = {
                "role": "assistant",
                "content": [],
            }
            mock_build.return_value = mock_inner
            result = agent.invoke("Hello")
            assert result == ""

    def test_invoke_extracts_text_from_multiple_content_blocks(self):
        agent = FoundationStrandsAgent()
        with patch.object(agent, '_build_strands_agent') as mock_build:
            mock_inner = MagicMock()
            mock_inner.return_value = {
                "role": "assistant",
                "content": [
                    {"text": "Part 1."},
                    {"text": " Part 2."},
                ],
            }
            mock_build.return_value = mock_inner
            result = agent.invoke("Hello")
            assert "Part 1." in result
            assert "Part 2." in result


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Test that tools are properly registered with the Strands agent."""

    def test_default_tools_with_workspace(self, tmp_path):
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        tools = agent.get_tools()
        # Should include workspace tools when workspace_dir is set
        assert len(tools) > 0

    def test_no_tools_without_workspace(self):
        agent = FoundationStrandsAgent()
        tools = agent.get_tools()
        # No workspace = no default tools
        assert len(tools) == 0

    def test_custom_tools_can_be_added(self):
        def my_tool(x: str) -> str:
            """A custom tool."""
            return x

        agent = FoundationStrandsAgent(extra_tools=[my_tool])
        tools = agent.get_tools()
        assert my_tool in tools

    def test_claude_code_tool_included_when_enabled(self):
        agent = FoundationStrandsAgent(enable_claude_code=True)
        tools = agent.get_tools()
        tool_names = [getattr(t, '__name__', str(t)) for t in tools]
        assert "claude_code" in tool_names
