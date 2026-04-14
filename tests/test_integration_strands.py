"""Integration tests — full agent assembly with workspace, hooks, and skills.

Tests the complete FoundationStrandsAgent setup without AWS credentials.
All Strands/Bedrock calls are mocked.
"""

from __future__ import annotations

import os
import tempfile
import textwrap

import pytest

from platform_agent.foundation.agent import FoundationStrandsAgent


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace with soul files and skills."""
    # Soul files
    (tmp_path / "IDENTITY.md").write_text("# Agent\nName: TestBot\nEmoji: 🤖")
    (tmp_path / "SOUL.md").write_text("Be helpful and concise.")
    (tmp_path / "AGENTS.md").write_text("Follow user instructions carefully.")
    (tmp_path / "USER.md").write_text("Name: Test User\nTimezone: UTC")
    (tmp_path / "MEMORY.md").write_text("User prefers dark mode.")

    # Memory directory
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "2026-03-26.md").write_text("Had a meeting about architecture.")

    # Skills directory
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    skill1_dir = skills_dir / "code-review"
    skill1_dir.mkdir()
    (skill1_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: code-review
        description: Review code for quality and best practices
        ---

        # Code Review Skill

        When asked to review code, check for:
        - Code style
        - Error handling
        - Test coverage
    """))

    skill2_dir = skills_dir / "deployment"
    skill2_dir.mkdir()
    (skill2_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: deployment
        description: Help with deployment configuration
        ---

        # Deployment Skill

        Generate Dockerfiles, CDK stacks, and IAM policies.
    """))

    return str(tmp_path)


class TestFullAgentAssembly:
    """Test complete agent setup with all components."""

    def test_agent_creates_with_workspace(self, workspace):
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        assert agent.workspace_dir == workspace
        assert agent.soul_system is not None
        assert agent.workspace_memory is not None

    def test_system_prompt_contains_soul_content(self, workspace):
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        prompt = agent.build_system_prompt()
        assert "TestBot" in prompt
        assert "Be helpful and concise" in prompt
        assert "Follow user instructions carefully" in prompt
        assert "Test User" in prompt
        assert "User prefers dark mode" in prompt

    def test_system_prompt_contains_skills(self, workspace):
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        if agent._skills_plugin is not None:
            # AgentSkills plugin is active — SkillRegistry prompt injection is
            # skipped; the plugin injects its own <available_skills> XML.
            # Verify plugin was created with correct skill sources.
            skills_arg = agent._skills_plugin.skills
            ws_skills = str(__import__("pathlib").Path(workspace) / "skills")
            if isinstance(skills_arg, list):
                assert ws_skills in skills_arg
            else:
                assert skills_arg == ws_skills
        else:
            prompt = agent.build_system_prompt()
            assert "code-review" in prompt
            assert "Review code for quality" in prompt
            assert "deployment" in prompt
            assert "Help with deployment" in prompt

    def test_system_prompt_skills_with_plugin(self, workspace):
        """When AgentSkills plugin active, SkillRegistry markdown not in prompt."""
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        if agent._skills_plugin is not None:
            prompt = agent.build_system_prompt()
            assert "## Available Skills" not in prompt

    def test_system_prompt_skills_without_plugin(self, workspace, monkeypatch):
        """When AgentSkills unavailable, SkillRegistry injects skill summary."""
        import platform_agent.foundation.agent as agent_mod
        monkeypatch.setattr(agent_mod, "_AgentSkills", None)
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        assert agent._skills_plugin is None
        # Explicitly discover since auto-discover is no longer done
        agent.skill_registry.discover()
        prompt = agent.build_system_prompt()
        assert "code-review" in prompt
        assert "deployment" in prompt

    def test_system_prompt_contains_timestamp(self, workspace):
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        prompt = agent.build_system_prompt()
        assert "Current Time" in prompt

    def test_skill_lazy_loading(self, workspace):
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        # Explicitly discover since auto-discover is no longer done
        agent.skill_registry.discover()
        # Summary in prompt should NOT contain full skill content
        prompt = agent.build_system_prompt()
        assert "check for:" not in prompt  # Full skill content not in prompt

        # But we can load the full content on demand
        skill = agent.skill_registry.get_skill("code-review")
        assert skill is not None
        assert "Code style" in skill.full_content

    def test_cc_cli_tool_registered(self, workspace):
        agent = FoundationStrandsAgent(
            workspace_dir=workspace,
            enable_claude_code=True,
        )
        tools = agent.get_tools()
        tool_names = [t.__name__ for t in tools]
        assert "claude_code" in tool_names

    def test_cc_cli_tool_not_registered_when_disabled(self, workspace):
        agent = FoundationStrandsAgent(
            workspace_dir=workspace,
            enable_claude_code=False,
        )
        tools = agent.get_tools()
        tool_names = [t.__name__ for t in tools]
        assert "claude_code" not in tool_names

    def test_workspace_tools_registered(self, workspace):
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        tools = agent.get_tools()
        tool_names = [t.__name__ for t in tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "list_files" in tool_names

    def test_tool_policy_enforcement(self, workspace):
        agent = FoundationStrandsAgent(
            workspace_dir=workspace,
            tool_denylist=["dangerous_tool"],
        )
        assert agent.tool_policy_hook.denylist == {"dangerous_tool"}

        policy = agent.tool_policy_hook.get_policy_summary()
        assert "dangerous_tool" in policy["denylist"]

    def test_tool_allowlist_enforcement(self, workspace):
        agent = FoundationStrandsAgent(
            workspace_dir=workspace,
            tool_allowlist=["read_file", "write_file"],
        )
        assert agent.tool_policy_hook.allowlist == {"read_file", "write_file"}

    def test_all_hooks_registered(self, workspace):
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        # v1: 10 core hooks (CompactionHook + StmIngestionHook removed from active registry)
        assert len(agent.hook_registry) == 10
        # Verify types
        from platform_agent.foundation.hooks import (
            SoulSystemHook, MemoryHook, AuditHook,
            GuardrailsHook, ToolPolicyHook,
            TelemetryHook, ModelMetricsHook,
            BusinessMetricsHook, HallucinationDetectorHook,
            SessionRecordingHook,
        )
        types = [type(h) for h in agent.hook_registry]
        assert SoulSystemHook in types
        assert MemoryHook in types
        assert AuditHook in types
        assert GuardrailsHook in types
        assert ToolPolicyHook in types
        assert TelemetryHook in types
        assert ModelMetricsHook in types
        assert BusinessMetricsHook in types
        assert HallucinationDetectorHook in types
        assert SessionRecordingHook in types
        assert SessionRecordingHook in types
        # CompactionHook removed (dead code cleanup)
        from platform_agent.foundation.hooks import CompactionHook
        assert CompactionHook not in types
        assert not hasattr(agent, 'compaction_hook')

    def test_agent_without_workspace(self):
        agent = FoundationStrandsAgent()
        prompt = agent.build_system_prompt()
        # Should use base prompt
        assert "helpful AI assistant" in prompt
        # No skills, no soul
        assert "code-review" not in prompt

    def test_extra_tools_registered(self, workspace):
        def my_custom_tool(x: str) -> str:
            """A custom tool."""
            return x.upper()

        agent = FoundationStrandsAgent(
            workspace_dir=workspace,
            extra_tools=[my_custom_tool],
        )
        tools = agent.get_tools()
        tool_names = [t.__name__ for t in tools]
        assert "my_custom_tool" in tool_names

    def test_memory_files_accessible(self, workspace):
        agent = FoundationStrandsAgent(workspace_dir=workspace)
        mem_files = agent.soul_system.load_memory_files()
        assert "2026-03-26.md" in mem_files
        assert "meeting about architecture" in mem_files["2026-03-26.md"]


class TestHookProviderCompliance:
    """Test that all hooks implement register_hooks method."""

    def test_soul_hook_has_register_hooks(self):
        from platform_agent.foundation.hooks import SoulSystemHook
        hook = SoulSystemHook(workspace_dir="/tmp")
        assert hasattr(hook, "register_hooks")
        assert callable(hook.register_hooks)

    def test_memory_hook_has_register_hooks(self):
        from platform_agent.foundation.hooks import MemoryHook
        hook = MemoryHook()
        assert hasattr(hook, "register_hooks")
        assert callable(hook.register_hooks)

    def test_audit_hook_has_register_hooks(self):
        from platform_agent.foundation.hooks import AuditHook
        hook = AuditHook()
        assert hasattr(hook, "register_hooks")
        assert callable(hook.register_hooks)

    def test_guardrails_hook_has_register_hooks(self):
        from platform_agent.foundation.hooks import GuardrailsHook
        hook = GuardrailsHook()
        assert hasattr(hook, "register_hooks")
        assert callable(hook.register_hooks)

    def test_tool_policy_hook_has_register_hooks(self):
        from platform_agent.foundation.hooks import ToolPolicyHook
        hook = ToolPolicyHook()
        assert hasattr(hook, "register_hooks")
        assert callable(hook.register_hooks)

    def test_compaction_hook_has_register_hooks(self):
        from platform_agent.foundation.hooks import CompactionHook
        hook = CompactionHook()
        assert hasattr(hook, "register_hooks")
        assert callable(hook.register_hooks)
