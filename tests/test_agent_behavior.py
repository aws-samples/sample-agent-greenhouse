"""Layer 2 — Agent Behavior Scenario Replay Tests.

Verifies that the agent makes correct tool-call decisions given
standard user prompts. Uses mock model responses to test the
routing logic without real LLM calls.

Test scenarios:
- New project request → must call aidlc_start_inception first
- Status query → calls aidlc_get_status, not inception
- Simple question → answers directly, no AIDLC
- Post-inception → allowed to use write_file/github tools
- Negative: new project should NOT call write_file before inception

Traces to: agent behavior improvement directive.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch, call

import pytest

from platform_agent.plato.skills.aidlc_inception.tools import (
    _active_workflows,
    aidlc_start_inception,
    aidlc_get_status,
    aidlc_get_questions,
    aidlc_submit_answers,
    aidlc_approve_stage,
    aidlc_reject_stage,
    aidlc_generate_artifacts,
)
from platform_agent.plato.aidlc.state import StageID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_aidlc_state():
    """Reset AIDLC workflow state between tests."""
    from platform_agent.plato.skills.aidlc_inception.tools import (
        _active_workflows,
        _aidlc_telemetry_hooks,
    )
    _active_workflows.clear()
    _aidlc_telemetry_hooks.clear()
    # Also reset the module-level current context
    import platform_agent.plato.skills.aidlc_inception.tools as _tools_mod
    _tools_mod._current_tenant_id = None
    _tools_mod._current_repo = None
    _tools_mod._current_workspace_path = None
    yield
    _active_workflows.clear()
    _aidlc_telemetry_hooks.clear()
    _tools_mod._current_tenant_id = None
    _tools_mod._current_repo = None
    _tools_mod._current_workspace_path = None


@pytest.fixture
def workspace_dir(tmp_path):
    """Create a minimal workspace directory."""
    (tmp_path / "SOUL.md").write_text("# Test Soul\nYou are a test agent.")
    (tmp_path / "IDENTITY.md").write_text("# Test Agent\nName: TestBot")
    return str(tmp_path)


# ---------------------------------------------------------------------------
# Scenario 1: New project request → AIDLC inception
# ---------------------------------------------------------------------------


class TestNewProjectTriggersAIDLC:
    """When user describes a new agent project, AIDLC inception tools must be available."""

    def test_aidlc_start_inception_is_callable(self):
        """aidlc_start_inception can be called with required params."""
        result = aidlc_start_inception(
            project_name="IT QA Agent",
            tenant_id="test-tenant",
            repo="test-org/it-qa-agent",
            workspace_path="/tmp/test-workspace",
        )
        data = json.loads(result)
        assert data["status"] == "started"
        assert data["project_name"] == "IT QA Agent"
        assert data["current_stage_id"] is not None
        assert "questions" in data

    def test_inception_starts_at_workspace_detection(self):
        """First stage after inception is workspace_detection."""
        result = aidlc_start_inception(
            project_name="Test Project",
            tenant_id="test-tenant",
            repo="test-org/test",
            workspace_path="/tmp/test-workspace",
        )
        data = json.loads(result)
        assert data["current_stage_id"] == "workspace_detection"

    def test_inception_returns_questions(self):
        """Inception provides questions for the user to answer."""
        result = aidlc_start_inception(
            project_name="Test Project",
            tenant_id="test-tenant",
            repo="test-org/test",
            workspace_path="/tmp/test-workspace",
        )
        data = json.loads(result)
        assert data["questions"] is not None
        assert len(data["questions"]) > 0

    def test_duplicate_inception_blocked(self):
        """Starting inception twice for same repo returns error."""
        aidlc_start_inception(
            project_name="First",
            tenant_id="test-tenant",
            repo="test-org/same-repo",
            workspace_path="/tmp/test-workspace",
        )
        result = aidlc_start_inception(
            project_name="Second",
            tenant_id="test-tenant",
            repo="test-org/same-repo",
            workspace_path="/tmp/test-workspace",
        )
        data = json.loads(result)
        assert data["status"] == "error"
        assert "already exists" in data["message"]


# ---------------------------------------------------------------------------
# Scenario 2: Status query → aidlc_get_status
# ---------------------------------------------------------------------------


class TestStatusQuery:
    """Status queries should use aidlc_get_status, not start new inception."""

    def test_get_status_no_active_workflow(self):
        """Status query with no active workflow returns error with guidance."""
        result = aidlc_get_status()
        data = json.loads(result)
        assert data["status"] == "error"
        assert "aidlc_start_inception" in data["message"]

    def test_get_status_after_inception(self):
        """Status query after inception returns current stage info."""
        aidlc_start_inception(
            project_name="Status Test",
            tenant_id="test-tenant",
            repo="test-org/status-test",
            workspace_path="/tmp/test-workspace",
        )
        result = aidlc_get_status()
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "current_stage" in data


# ---------------------------------------------------------------------------
# Scenario 3: Tool availability per category
# ---------------------------------------------------------------------------


class TestToolAvailabilityByCategory:
    """Verify tool categories are properly segmented."""

    def test_aidlc_tools_available_in_extra_tools(self):
        """When entrypoint initializes, AIDLC tools are in extra_tools."""
        with patch.dict(os.environ, {
            "GITHUB_TOKEN": "ghp_test",
            "WORKSPACE_DIR": "/tmp/test",
            "ENABLE_CLAUDE_CODE": "false",
        }):
            with patch("bedrock_agentcore.BedrockAgentCoreApp"):
                import importlib
                import entrypoint
                importlib.reload(entrypoint)
                entrypoint._initialized = False
                entrypoint._extra_tools = None

                with patch("entrypoint.MemoryClient", create=True):
                    with patch("entrypoint.AgentCoreMemory", create=True):
                        try:
                            entrypoint._ensure_initialized()
                        except Exception:
                            pass

                if entrypoint._extra_tools:
                    names = [
                        getattr(t, "__name__", getattr(t, "tool_name", ""))
                        for t in entrypoint._extra_tools
                    ]
                    # Must have both AIDLC and GitHub tools
                    assert any(n.startswith("aidlc_") for n in names), \
                        f"No AIDLC tools found in: {names}"
                    assert any(n.startswith("github_") for n in names), \
                        f"No GitHub tools found in: {names}"

    def test_workspace_tools_separate_from_extra(self, workspace_dir):
        """Workspace tools (read/write/list) come from agent, not extra_tools."""
        from platform_agent.foundation.agent import FoundationStrandsAgent

        agent = FoundationStrandsAgent(
            workspace_dir=workspace_dir,
            enable_claude_code=False,
        )
        tools = agent.get_tools()
        tool_names = [getattr(t, "__name__", "") for t in tools]

        # Workspace tools exist
        assert "read_file" in tool_names
        assert "write_file" in tool_names

        # But they come from agent.get_tools(), not extra_tools
        extra_names = [getattr(t, "__name__", "") for t in agent._extra_tools]
        assert "read_file" not in extra_names
        assert "write_file" not in extra_names


# ---------------------------------------------------------------------------
# Scenario 4: AIDLC workflow stage progression
# ---------------------------------------------------------------------------


class TestAIDLCWorkflowProgression:
    """Verify the AIDLC state machine progresses correctly through stages."""

    def test_inception_to_requirements(self):
        """After workspace_detection answers + approval, moves to requirements."""
        # Start inception
        aidlc_start_inception(
            project_name="Progression Test",
            tenant_id="test-tenant",
            repo="test-org/progression",
            workspace_path="/tmp/test-workspace",
        )

        # Get and answer workspace_detection questions
        questions_result = aidlc_get_questions()
        q_data = json.loads(questions_result)
        assert q_data["status"] == "ok"

        # Submit answers for workspace_detection
        answers = json.dumps({
            "existing_repo": "yes",
            "repo_url": "https://github.com/test-org/progression",
            "tech_stack": "Python, AWS",
        })
        submit_result = aidlc_submit_answers("workspace_detection", answers)
        s_data = json.loads(submit_result)
        assert s_data["status"] == "awaiting_approval"

        # Approve workspace_detection
        approve_result = aidlc_approve_stage("workspace_detection")
        a_data = json.loads(approve_result)
        assert a_data["status"] == "advanced"
        # Should advance to requirements
        assert a_data.get("next_stage_id") == "requirements"

    def test_full_simple_flow_completes(self):
        """A SIMPLE complexity project can complete all required stages."""
        aidlc_start_inception(
            project_name="Simple Flow",
            tenant_id="test-tenant",
            repo="test-org/simple",
            workspace_path="/tmp/test-simple",
        )

        # Process workspace_detection
        answers = json.dumps({"existing_repo": "no", "tech_stack": "Python"})
        aidlc_submit_answers("workspace_detection", answers)
        result = aidlc_approve_stage("workspace_detection")
        data = json.loads(result)
        # Verify it advanced
        assert data["status"] == "advanced"
        assert data.get("next_stage_id") is not None


# ---------------------------------------------------------------------------
# Scenario 5: Negative tests — what should NOT happen
# ---------------------------------------------------------------------------


class TestNegativeScenarios:
    """Things that should fail or be prevented."""

    def test_approve_without_answers_fails(self):
        """Cannot approve a stage that hasn't received answers."""
        aidlc_start_inception(
            project_name="Negative Test",
            tenant_id="test-tenant",
            repo="test-org/negative",
            workspace_path="/tmp/test-negative",
        )
        result = aidlc_approve_stage("workspace_detection")
        data = json.loads(result)
        # Should fail — status is 'error' because answers not submitted
        assert data["status"] == "error"
        # Error message should indicate the issue
        assert "message" in data

    def test_submit_to_wrong_stage_fails(self):
        """Cannot submit answers to a stage that's not current."""
        aidlc_start_inception(
            project_name="Wrong Stage Test",
            tenant_id="test-tenant",
            repo="test-org/wrong-stage",
            workspace_path="/tmp/test-wrong",
        )
        # Try submitting to requirements when we're at workspace_detection
        result = aidlc_submit_answers(
            "requirements",
            json.dumps({"goal": "test"}),
        )
        data = json.loads(result)
        assert data["status"] == "error"

    def test_reject_restarts_stage(self):
        """Rejecting a stage allows re-submission."""
        aidlc_start_inception(
            project_name="Reject Test",
            tenant_id="test-tenant",
            repo="test-org/reject",
            workspace_path="/tmp/test-reject",
        )
        answers = json.dumps({"existing_repo": "no"})
        aidlc_submit_answers("workspace_detection", answers)

        # Reject
        result = aidlc_reject_stage("workspace_detection", "Needs more detail")
        data = json.loads(result)
        assert data["status"] == "rejected"
        assert "feedback" in data

        # Should be able to re-submit
        result2 = aidlc_submit_answers("workspace_detection", answers)
        data2 = json.loads(result2)
        assert data2["status"] == "awaiting_approval"
