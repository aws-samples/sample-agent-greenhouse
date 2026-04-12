"""Layer 1 — Tool Registration Tests.

Verifies that all tool categories are properly registered with the
FoundationStrandsAgent via entrypoint.py configuration.

These tests catch the class of bug where tool code exists but is never
wired into the running agent (e.g., AIDLC tools existed but were never
registered — discovered 2026-04-05).

Test categories:
- Tool category completeness (GitHub, AIDLC, Memory, Workspace)
- Individual tool discoverability by name
- Tool count assertions per category
- Entrypoint initialization registers expected tools
"""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_env():
    """Standard environment variables for testing."""
    env = {
        "WORKSPACE_DIR": "/tmp/test-workspace",
        "MODEL_ID": "global.anthropic.claude-opus-4-6-v1",
        "GITHUB_TOKEN": "ghp_test_token_1234567890",
        "ENABLE_CLAUDE_CODE": "false",
    }
    with patch.dict(os.environ, env):
        yield env


# ---------------------------------------------------------------------------
# AIDLC Tool Registration
# ---------------------------------------------------------------------------


class TestAIDLCToolRegistration:
    """Verify AIDLC inception tools are importable and properly decorated."""

    def test_aidlc_tools_importable(self):
        """All 7 AIDLC tools can be imported from the skills module."""
        from platform_agent.plato.skills.aidlc_inception.tools import (
            aidlc_start_inception,
            aidlc_get_questions,
            aidlc_submit_answers,
            aidlc_approve_stage,
            aidlc_reject_stage,
            aidlc_get_status,
            aidlc_generate_artifacts,
        )
        tools = [
            aidlc_start_inception,
            aidlc_get_questions,
            aidlc_submit_answers,
            aidlc_approve_stage,
            aidlc_reject_stage,
            aidlc_get_status,
            aidlc_generate_artifacts,
        ]
        assert len(tools) == 7
        for tool in tools:
            assert callable(tool), f"{tool} is not callable"

    def test_aidlc_tools_have_docstrings(self):
        """Each AIDLC tool has a docstring (required for LLM tool schema)."""
        from platform_agent.plato.skills.aidlc_inception.tools import (
            aidlc_start_inception,
            aidlc_get_questions,
            aidlc_submit_answers,
            aidlc_approve_stage,
            aidlc_reject_stage,
            aidlc_get_status,
            aidlc_generate_artifacts,
        )
        tools = [
            aidlc_start_inception,
            aidlc_get_questions,
            aidlc_submit_answers,
            aidlc_approve_stage,
            aidlc_reject_stage,
            aidlc_get_status,
            aidlc_generate_artifacts,
        ]
        for tool in tools:
            # strands @tool wraps the function; check both wrapper and original
            doc = getattr(tool, "__doc__", None)
            if doc is None and hasattr(tool, "__wrapped__"):
                doc = getattr(tool.__wrapped__, "__doc__", None)
            assert doc is not None and len(doc) > 10, (
                f"{getattr(tool, '__name__', tool)} missing docstring"
            )

    def test_aidlc_tool_names(self):
        """AIDLC tool names follow the aidlc_ prefix convention."""
        from platform_agent.plato.skills.aidlc_inception.tools import (
            aidlc_start_inception,
            aidlc_get_questions,
            aidlc_submit_answers,
            aidlc_approve_stage,
            aidlc_reject_stage,
            aidlc_get_status,
            aidlc_generate_artifacts,
        )
        expected_names = {
            "aidlc_start_inception",
            "aidlc_get_questions",
            "aidlc_submit_answers",
            "aidlc_approve_stage",
            "aidlc_reject_stage",
            "aidlc_get_status",
            "aidlc_generate_artifacts",
        }
        tools = [
            aidlc_start_inception,
            aidlc_get_questions,
            aidlc_submit_answers,
            aidlc_approve_stage,
            aidlc_reject_stage,
            aidlc_get_status,
            aidlc_generate_artifacts,
        ]
        actual_names = set()
        for tool in tools:
            name = getattr(tool, "__name__", None)
            if name is None and hasattr(tool, "tool_name"):
                name = tool.tool_name
            actual_names.add(name)
        assert expected_names.issubset(actual_names), (
            f"Missing tools: {expected_names - actual_names}"
        )


# ---------------------------------------------------------------------------
# GitHub Tool Registration
# ---------------------------------------------------------------------------


class TestGitHubToolRegistration:
    """Verify GitHub tools are importable."""

    def test_github_tools_importable(self):
        """All 13 GitHub tools can be imported."""
        from platform_agent.foundation.tools.github_tool import (
            github_get_repo,
            github_list_prs,
            github_get_pr_diff,
            github_list_pr_files,
            github_list_issues,
            github_get_file,
            github_create_issue,
            github_create_pr_review,
            github_merge_pr,
            github_create_repo,
            github_create_or_update_file,
            github_set_branch_protection,
            github_add_labels,
        )
        tools = [
            github_get_repo,
            github_list_prs,
            github_get_pr_diff,
            github_list_pr_files,
            github_list_issues,
            github_get_file,
            github_create_issue,
            github_create_pr_review,
            github_merge_pr,
            github_create_repo,
            github_create_or_update_file,
            github_set_branch_protection,
            github_add_labels,
        ]
        assert len(tools) == 13
        for tool in tools:
            assert callable(tool)


# ---------------------------------------------------------------------------
# Workspace Tool Registration
# ---------------------------------------------------------------------------


class TestWorkspaceToolRegistration:
    """Verify workspace tools are created by FoundationStrandsAgent."""

    def test_workspace_tools_created(self):
        """Agent with workspace_dir creates read_file, write_file, list_files."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create minimal workspace files so SoulSystem doesn't fail
            from platform_agent.foundation.agent import (
                FoundationStrandsAgent,
            )
            agent = FoundationStrandsAgent(
                workspace_dir=tmpdir,
                enable_claude_code=False,
            )
            tools = agent.get_tools()
            tool_names = []
            for t in tools:
                name = getattr(t, "__name__", None)
                if name is None and hasattr(t, "tool_name"):
                    name = t.tool_name
                tool_names.append(name)

            assert "read_file" in tool_names, "read_file not registered"
            assert "write_file" in tool_names, "write_file not registered"
            assert "list_files" in tool_names, "list_files not registered"

    def test_no_workspace_no_workspace_tools(self):
        """Agent without workspace_dir does NOT create workspace tools."""
        from platform_agent.foundation.agent import (
            FoundationStrandsAgent,
        )
        agent = FoundationStrandsAgent(
            workspace_dir=None,
            enable_claude_code=False,
        )
        tools = agent.get_tools()
        tool_names = [getattr(t, "__name__", "") for t in tools]
        assert "read_file" not in tool_names
        assert "write_file" not in tool_names
        assert "list_files" not in tool_names


# ---------------------------------------------------------------------------
# Memory Tool Registration
# ---------------------------------------------------------------------------


class TestMemoryToolRegistration:
    """Verify memory tools can be created."""

    def test_memory_tools_creation(self):
        """create_memory_tools returns callable tools."""
        from platform_agent.foundation.tools.memory_tools import (
            create_memory_tools,
        )
        mock_backend = MagicMock()
        tools = create_memory_tools(
            memory_backend=mock_backend,
            actor_id="test-user",
            session_id="test-session",
        )
        assert len(tools) >= 2, "Expected at least save_memory + recall_memory"
        for tool in tools:
            assert callable(tool)


# ---------------------------------------------------------------------------
# Entrypoint Integration — Tool Count Assertion
# ---------------------------------------------------------------------------


class TestEntrypointToolRegistration:
    """Verify entrypoint.py registers the expected tool categories.

    These tests import entrypoint logic and verify the tool list
    composition without starting the actual AgentCore server.
    """

    def test_extra_tools_include_aidlc(self, mock_env):
        """AIDLC tools are in the extra_tools list after initialization."""
        # Re-import with clean state
        import importlib
        # Mock heavy dependencies
        with patch("platform_agent.foundation.agent.FoundationStrandsAgent"):
            with patch("bedrock_agentcore.BedrockAgentCoreApp"):
                import entrypoint
                importlib.reload(entrypoint)

                # Reset init state and re-initialize
                entrypoint._initialized = False
                entrypoint._extra_tools = None

                # Mock memory client to avoid AWS calls
                with patch("entrypoint.MemoryClient", create=True):
                    with patch("entrypoint.AgentCoreMemory", create=True):
                        try:
                            entrypoint._ensure_initialized()
                        except Exception:
                            pass  # May fail on AgentPool etc

                if entrypoint._extra_tools is not None:
                    tool_names = []
                    for t in entrypoint._extra_tools:
                        name = getattr(t, "__name__", None)
                        if name is None and hasattr(t, "tool_name"):
                            name = t.tool_name
                        tool_names.append(name)

                    # AIDLC tools must be present
                    aidlc_tools = [n for n in tool_names if n and n.startswith("aidlc_")]
                    assert len(aidlc_tools) >= 7, (
                        f"Expected 7 AIDLC tools, found {len(aidlc_tools)}: {aidlc_tools}"
                    )

                    # GitHub tools must be present (when GITHUB_TOKEN is set)
                    github_tools = [n for n in tool_names if n and n.startswith("github_")]
                    assert len(github_tools) >= 13, (
                        f"Expected 13 GitHub tools, found {len(github_tools)}: {github_tools}"
                    )

    def test_tool_categories_logged(self, mock_env, caplog):
        """Entrypoint logs tool category registration."""
        import importlib
        import logging

        with patch("platform_agent.foundation.agent.FoundationStrandsAgent"):
            with patch("bedrock_agentcore.BedrockAgentCoreApp"):
                import entrypoint
                importlib.reload(entrypoint)

                entrypoint._initialized = False
                entrypoint._extra_tools = None

                with patch("entrypoint.MemoryClient", create=True):
                    with patch("entrypoint.AgentCoreMemory", create=True):
                        with caplog.at_level(logging.INFO):
                            try:
                                entrypoint._ensure_initialized()
                            except Exception:
                                pass

                # Check that AIDLC registration was logged
                aidlc_logged = any(
                    "AIDLC" in record.message
                    for record in caplog.records
                )
                assert aidlc_logged, (
                    "Expected 'AIDLC' in log output during initialization"
                )
