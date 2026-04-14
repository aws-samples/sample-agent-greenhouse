"""Tests for the AIDLC Inception skill, tools, and deliverable generators.

Covers skill registration and metadata, tool functions (start, submit, approve,
reject, status), full inception flow through tools, and artifact generation.

Traces to: spec §3.1 (AIDLC Inception Skill), §3.2 (Artifact Generation)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from platform_agent.plato.aidlc.stages import StageID
from platform_agent.plato.aidlc.state import Complexity, StageStatus, WorkflowState
from platform_agent.plato.skills.aidlc_inception import AIDLCInceptionSkill, register_skill
from platform_agent.plato.skills.aidlc_inception.deliverables import (
    generate_agentcore_refs,
    generate_claude_md,
    generate_spec,
    generate_test_cases,
)
from platform_agent.plato.skills.aidlc_inception import tools as _tools_mod
from platform_agent.plato.skills.aidlc_inception.tools import (
    AIDLC_INCEPTION_TOOLS,
    _active_workflows,
    _set_current_context,
    aidlc_approve_stage,
    aidlc_generate_artifacts,
    aidlc_get_questions,
    aidlc_get_status,
    aidlc_reject_stage,
    aidlc_start_inception,
    aidlc_submit_answers,
)
from platform_agent.plato.skills.base import SkillPack, load_skill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_workflow_registry(tmp_path: Path):
    """Reset the module-level workflow registry and patch projects base dir."""
    _active_workflows.clear()
    projects_dir = str(tmp_path / "projects")
    # Patch the lazy-cached base dir so all tests write to tmp_path
    old_val = _tools_mod._projects_base_dir
    _tools_mod._projects_base_dir = projects_dir
    yield
    _tools_mod._projects_base_dir = old_val
    _active_workflows.clear()


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Provide a temporary workspace directory (projects base)."""
    return tmp_path


@pytest.fixture
def started_workspace(tmp_workspace: Path) -> Path:
    """Start an inception workflow and return the auto-computed workspace path."""
    result_json = aidlc_start_inception(
        project_name="test-project",
        tenant_id="tenant-001",
        repo="org/test-project",
    )
    result = json.loads(result_json)
    assert result["status"] == "started"
    return Path(result["workspace_path"])


@pytest.fixture
def _completed_workflow_state() -> WorkflowState:
    """Create a WorkflowState that looks like a completed workflow."""
    state = WorkflowState(
        project_name="test-project",
        tenant_id="tenant-001",
        repo="org/test-project",
        complexity=Complexity.STANDARD,
    )
    state.audit_entries.append({
        "timestamp": "2026-04-03T00:00:00+00:00",
        "stage_id": "requirements",
        "user_input": {
            "target_users": "internal teams",
            "channels": ["Slack", "API"],
            "capabilities": ["knowledge base search", "ticket management"],
            "data_sources": ["CRM", "wiki"],
            "compliance": "audit trail",
            "deployment_target": "AgentCore",
        },
    })
    state.decisions.append({
        "timestamp": "2026-04-03T00:00:00+00:00",
        "decision": "Use DynamoDB",
        "rationale": "Already in the stack",
    })
    return state


@pytest.fixture
def completed_aidlc_docs(tmp_workspace: Path) -> Path:
    """Create aidlc-docs directory with sample artifact files."""
    docs_dir = tmp_workspace / "aidlc-docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    (docs_dir / "workspace-analysis.md").write_text(
        "# Workspace Analysis\n\n"
        "**Existing repository:** No (greenfield)\n\n"
        "**Project type:** Greenfield\n"
    )
    (docs_dir / "requirements.md").write_text(
        "# Requirements\n\n"
        "## Target Users\n\nInternal teams\n\n"
        "## Channels\n\n- Slack\n- API\n\n"
        "## Core Capabilities\n\n- Knowledge base search\n\n"
        "## Data Sources\n\n- CRM\n\n"
        "## Compliance Requirements\n\naudit trail\n\n"
        "## Deployment Target\n\nAgentCore\n"
    )
    (docs_dir / "workflow-plan.md").write_text(
        "# Workflow Plan\n\n"
        "## Construction Stages\n\n1. foundation\n2. tools\n\n"
        "## Execution Strategy\n\nSequential\n"
    )
    return docs_dir


# ---------------------------------------------------------------------------
# Skill registration and metadata
# ---------------------------------------------------------------------------


class TestSkillRegistration:
    """Tests for AIDLC Inception skill registration and metadata."""

    def test_skill_is_skillpack_subclass(self) -> None:
        """AIDLCInceptionSkill is a SkillPack subclass."""
        assert issubclass(AIDLCInceptionSkill, SkillPack)

    def test_skill_name(self) -> None:
        """Skill name is 'aidlc_inception'."""
        skill = AIDLCInceptionSkill()
        assert skill.name == "aidlc_inception"

    def test_skill_description(self) -> None:
        """Skill has a non-empty description."""
        skill = AIDLCInceptionSkill()
        assert len(skill.description) > 0
        assert "AIDLC" in skill.description

    def test_skill_has_system_prompt(self) -> None:
        """Skill has system_prompt_extension cleared (SKILL.md is sole source)."""
        skill = AIDLCInceptionSkill()
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        assert skill.system_prompt_extension == ""

    def test_skill_tools_list(self) -> None:
        """Skill references all AIDLC tool names."""
        skill = AIDLCInceptionSkill()
        expected_tools = [
            "aidlc_start_inception",
            "aidlc_get_questions",
            "aidlc_submit_answers",
            "aidlc_approve_stage",
            "aidlc_reject_stage",
            "aidlc_get_status",
            "aidlc_generate_artifacts",
        ]
        for tool_name in expected_tools:
            assert tool_name in skill.tools

    def test_load_skill(self) -> None:
        """load_skill creates a configured instance."""
        skill = load_skill(AIDLCInceptionSkill)
        assert skill.name == "aidlc_inception"

    def test_skill_registered_in_registry(self) -> None:
        """Skill is available via the registry."""
        from platform_agent.plato.skills import get_skill
        cls = get_skill("aidlc_inception")
        assert cls is AIDLCInceptionSkill

    def test_tools_list_has_all_tools(self) -> None:
        """AIDLC_INCEPTION_TOOLS contains all 7 tool functions."""
        assert len(AIDLC_INCEPTION_TOOLS) == 7


# ---------------------------------------------------------------------------
# Tool: aidlc_start_inception
# ---------------------------------------------------------------------------


class TestStartInception:
    """Tests for the aidlc_start_inception tool."""

    def test_start_creates_workflow(self, tmp_workspace: Path) -> None:
        """Starting inception creates a workflow and returns questions."""
        result_json = aidlc_start_inception(
            project_name="my-agent",
            tenant_id="t1",
            repo="org/my-agent",
        )
        result = json.loads(result_json)
        assert result["status"] == "started"
        assert result["project_name"] == "my-agent"
        assert result["current_stage_id"] == "workspace_detection"
        assert "questions" in result
        assert "workspace_path" in result

    def test_start_persists_state(self, tmp_workspace: Path) -> None:
        """Starting inception saves state to disk."""
        result_json = aidlc_start_inception(
            project_name="my-agent",
            tenant_id="t1",
            repo="org/my-agent",
        )
        result = json.loads(result_json)
        workspace_path = Path(result["workspace_path"])
        state_file = workspace_path / "aidlc-docs" / "aidlc-state.json"
        assert state_file.exists()

    def test_duplicate_start_returns_error(self, tmp_workspace: Path) -> None:
        """Starting inception twice for the same repo returns an error."""
        aidlc_start_inception(
            project_name="my-agent",
            tenant_id="t1",
            repo="org/my-agent",
        )
        result_json = aidlc_start_inception(
            project_name="my-agent",
            tenant_id="t1",
            repo="org/my-agent",
        )
        result = json.loads(result_json)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Tool: aidlc_get_questions
# ---------------------------------------------------------------------------


class TestGetQuestions:
    """Tests for the aidlc_get_questions tool."""

    def test_get_questions_returns_questions(self, started_workspace: Path) -> None:
        """aidlc_get_questions returns questions for the current stage."""
        result_json = aidlc_get_questions()
        result = json.loads(result_json)
        assert result["status"] == "ok"
        assert result["current_stage_id"] == "workspace_detection"
        assert "questions" in result

    def test_get_questions_no_workflow_returns_error(self) -> None:
        """aidlc_get_questions without a workflow returns an error."""
        # Reset context
        _set_current_context(None, None, None)  # type: ignore[arg-type]
        result_json = aidlc_get_questions()
        result = json.loads(result_json)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Tool: aidlc_submit_answers
# ---------------------------------------------------------------------------


class TestSubmitAnswers:
    """Tests for the aidlc_submit_answers tool."""

    def test_submit_workspace_answers(self, started_workspace: Path) -> None:
        """Submitting workspace answers transitions to awaiting_approval."""
        answers = json.dumps({"existing_repo": False})
        result_json = aidlc_submit_answers(
            stage_id="workspace_detection",
            answers_json=answers,
        )
        result = json.loads(result_json)
        assert result["status"] == "awaiting_approval"
        assert result["stage_id"] == "workspace_detection"
        assert result["artifact_path"] is not None

    def test_submit_invalid_stage_returns_error(self, started_workspace: Path) -> None:
        """Submitting for an invalid stage returns an error."""
        result_json = aidlc_submit_answers(
            stage_id="nonexistent",
            answers_json="{}",
        )
        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "Invalid stage_id" in result["message"]

    def test_submit_invalid_json_returns_error(self, started_workspace: Path) -> None:
        """Submitting invalid JSON returns an error."""
        result_json = aidlc_submit_answers(
            stage_id="workspace_detection",
            answers_json="not valid json{",
        )
        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "Invalid JSON" in result["message"]

    def test_submit_wrong_stage_returns_error(self, started_workspace: Path) -> None:
        """Submitting for the wrong stage returns an error."""
        result_json = aidlc_submit_answers(
            stage_id="requirements",
            answers_json="{}",
        )
        result = json.loads(result_json)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Tool: aidlc_approve_stage / aidlc_reject_stage
# ---------------------------------------------------------------------------


class TestApproveReject:
    """Tests for stage approval and rejection tools."""

    def test_approve_stage_advances(self, started_workspace: Path) -> None:
        """Approving a stage advances to the next one."""
        aidlc_submit_answers(
            stage_id="workspace_detection",
            answers_json=json.dumps({"existing_repo": False}),
        )
        result_json = aidlc_approve_stage(stage_id="workspace_detection")
        result = json.loads(result_json)
        assert result["status"] == "advanced"
        assert result["next_stage_id"] == "requirements"

    def test_approve_unapproved_returns_error(self, started_workspace: Path) -> None:
        """Approving a stage that isn't awaiting approval returns an error."""
        result_json = aidlc_approve_stage(stage_id="workspace_detection")
        result = json.loads(result_json)
        assert result["status"] == "error"

    def test_reject_stage_returns_to_progress(self, started_workspace: Path) -> None:
        """Rejecting a stage returns it to in_progress."""
        aidlc_submit_answers(
            stage_id="workspace_detection",
            answers_json=json.dumps({"existing_repo": False}),
        )
        result_json = aidlc_reject_stage(
            stage_id="workspace_detection",
            feedback="Need more detail",
        )
        result = json.loads(result_json)
        assert result["status"] == "rejected"
        assert "questions" in result

    def test_reject_non_awaiting_returns_error(self, started_workspace: Path) -> None:
        """Rejecting a stage that isn't awaiting approval returns an error."""
        result_json = aidlc_reject_stage(stage_id="workspace_detection")
        result = json.loads(result_json)
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Tool: aidlc_get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Tests for the aidlc_get_status tool."""

    def test_status_after_start(self, started_workspace: Path) -> None:
        """Status shows workspace_detection as current stage."""
        result_json = aidlc_get_status()
        result = json.loads(result_json)
        assert result["status"] == "ok"
        assert result["current_stage_id"] == "workspace_detection"
        assert result["completion_pct"] == 0

    def test_status_shows_progress(self, started_workspace: Path) -> None:
        """Status updates after approving a stage."""
        aidlc_submit_answers(
            stage_id="workspace_detection",
            answers_json=json.dumps({"existing_repo": False}),
        )
        aidlc_approve_stage(stage_id="workspace_detection")

        result_json = aidlc_get_status()
        result = json.loads(result_json)
        assert result["completion_pct"] > 0
        assert result["current_stage_id"] == "requirements"


# ---------------------------------------------------------------------------
# Full inception flow through tools
# ---------------------------------------------------------------------------


class TestFullInceptionFlow:
    """End-to-end test of the complete inception flow via tools."""

    def test_full_simple_flow(self, tmp_workspace: Path) -> None:
        """Complete a SIMPLE complexity inception flow through all tools."""
        # Start
        start_result = json.loads(aidlc_start_inception(
            project_name="simple-agent",
            tenant_id="t1",
            repo="org/simple-agent",
        ))
        assert start_result["status"] == "started"

        # Stage 1: Workspace Detection
        aidlc_submit_answers(
            stage_id="workspace_detection",
            answers_json=json.dumps({"existing_repo": False}),
        )
        approve_result = json.loads(
            aidlc_approve_stage(stage_id="workspace_detection")
        )
        assert approve_result["status"] == "advanced"
        assert approve_result["next_stage_id"] == "requirements"

        # Stage 2: Requirements (triggers SIMPLE)
        simple_answers = {
            "target_users": "internal teams",
            "channels": ["Slack"],
            "capabilities": ["knowledge base search"],
            "data_sources": ["internal wiki"],
            "compliance": "none",
            "deployment_target": "AgentCore",
        }
        aidlc_submit_answers(
            stage_id="requirements",
            answers_json=json.dumps(simple_answers),
        )
        approve_result = json.loads(
            aidlc_approve_stage(stage_id="requirements")
        )
        # SIMPLE skips USER_STORIES → should go to WORKFLOW_PLANNING
        assert approve_result["status"] == "advanced"
        assert approve_result["next_stage_id"] == "workflow_planning"

        # Stage 3: Workflow Planning
        aidlc_submit_answers(
            stage_id="workflow_planning",
            answers_json=json.dumps({
                "stages": ["build", "test"],
                "parallel": False,
            }),
        )
        approve_result = json.loads(
            aidlc_approve_stage(stage_id="workflow_planning")
        )
        # SIMPLE skips APP_DESIGN and UNITS → should complete
        assert approve_result["status"] == "all_stages_complete"

        # Verify status
        status = json.loads(aidlc_get_status())
        assert status["completion_pct"] == 100

    def test_full_flow_with_reject_resubmit(self, tmp_workspace: Path) -> None:
        """Inception flow with a reject-resubmit cycle."""
        aidlc_start_inception(
            project_name="test-agent",
            tenant_id="t1",
            repo="org/test-agent",
        )

        # Submit first attempt
        aidlc_submit_answers(
            stage_id="workspace_detection",
            answers_json=json.dumps({"existing_repo": False}),
        )

        # Reject
        reject_result = json.loads(
            aidlc_reject_stage(
                stage_id="workspace_detection",
                feedback="Please add repo URL",
            )
        )
        assert reject_result["status"] == "rejected"

        # Re-submit
        aidlc_submit_answers(
            stage_id="workspace_detection",
            answers_json=json.dumps({
                "existing_repo": True,
                "repo_url": "github.com/org/test-agent",
            }),
        )

        # Now approve
        approve_result = json.loads(
            aidlc_approve_stage(stage_id="workspace_detection")
        )
        assert approve_result["status"] == "advanced"


# ---------------------------------------------------------------------------
# Tool: aidlc_generate_artifacts
# ---------------------------------------------------------------------------


class TestGenerateArtifactsTool:
    """Tests for the aidlc_generate_artifacts tool."""

    def test_generate_fails_if_not_complete(self, started_workspace: Path) -> None:
        """Cannot generate artifacts if workflow is not complete."""
        result_json = aidlc_generate_artifacts()
        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "not yet complete" in result["message"]

    def test_generate_produces_files(self, tmp_workspace: Path) -> None:
        """Generates all deliverable files after workflow completion."""
        # Run a full simple flow to completion
        aidlc_start_inception(
            project_name="gen-test",
            tenant_id="t1",
            repo="org/gen-test",
        )
        aidlc_submit_answers(
            stage_id="workspace_detection",
            answers_json=json.dumps({"existing_repo": False}),
        )
        aidlc_approve_stage(stage_id="workspace_detection")

        aidlc_submit_answers(
            stage_id="requirements",
            answers_json=json.dumps({
                "target_users": "internal teams",
                "channels": ["Slack"],
                "capabilities": ["kb search"],
                "data_sources": ["wiki"],
                "compliance": "none",
                "deployment_target": "AgentCore",
            }),
        )
        aidlc_approve_stage(stage_id="requirements")

        aidlc_submit_answers(
            stage_id="workflow_planning",
            answers_json=json.dumps({
                "stages": ["build"],
                "parallel": False,
            }),
        )
        aidlc_approve_stage(stage_id="workflow_planning")

        # Verify workflow is complete
        status = json.loads(aidlc_get_status())
        assert status["completion_pct"] == 100

        # Generate artifacts (no workspace_path needed — uses wf.base_dir)
        result_json = aidlc_generate_artifacts()
        result = json.loads(result_json)
        assert result["status"] == "generated"
        assert result["file_count"] >= 4  # spec.md, CLAUDE.md, test-cases.md, rules

        # Verify files exist (use workspace_path from result)
        ws = Path(result["workspace_path"])
        assert (ws / "spec.md").exists()
        assert (ws / "CLAUDE.md").exists()
        assert (ws / "test-cases.md").exists()
        assert (ws / ".claude" / "rules" / "tdd-rule.md").exists()
        assert (ws / ".claude" / "rules" / "spec-compliance.md").exists()

        # AgentCore deployment → should also have agentcore patterns
        assert (ws / "docs" / "agentcore" / "agentcore-patterns.md").exists()
        assert (ws / ".claude" / "rules" / "agentcore-patterns.md").exists()


# ---------------------------------------------------------------------------
# Deliverables: generate_spec
# ---------------------------------------------------------------------------


class TestGenerateSpec:
    """Tests for the generate_spec deliverable function."""

    def test_spec_contains_project_name(
        self, _completed_workflow_state: WorkflowState, completed_aidlc_docs: Path
    ) -> None:
        """Spec includes the project name in the title."""
        spec = generate_spec(_completed_workflow_state, completed_aidlc_docs)
        assert "test-project" in spec

    def test_spec_contains_requirements_sections(
        self, _completed_workflow_state: WorkflowState, completed_aidlc_docs: Path
    ) -> None:
        """Spec includes extracted requirements sections."""
        spec = generate_spec(_completed_workflow_state, completed_aidlc_docs)
        assert "Requirements" in spec
        assert "Target Users" in spec

    def test_spec_contains_acceptance_criteria(
        self, _completed_workflow_state: WorkflowState, completed_aidlc_docs: Path
    ) -> None:
        """Spec includes acceptance criteria section."""
        spec = generate_spec(_completed_workflow_state, completed_aidlc_docs)
        assert "Acceptance Criteria" in spec
        assert "AC-001" in spec

    def test_spec_contains_risks(
        self, _completed_workflow_state: WorkflowState, completed_aidlc_docs: Path
    ) -> None:
        """Spec includes a risks section."""
        spec = generate_spec(_completed_workflow_state, completed_aidlc_docs)
        assert "Risks" in spec


# ---------------------------------------------------------------------------
# Deliverables: generate_claude_md
# ---------------------------------------------------------------------------


class TestGenerateClaudeMd:
    """Tests for the generate_claude_md deliverable function."""

    def test_claude_md_contains_project_info(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """CLAUDE.md includes project name and repository."""
        md = generate_claude_md(_completed_workflow_state)
        assert "test-project" in md
        assert "org/test-project" in md

    def test_claude_md_contains_tech_stack(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """CLAUDE.md includes tech stack information."""
        md = generate_claude_md(_completed_workflow_state)
        assert "Tech Stack" in md
        assert "Python" in md

    def test_claude_md_includes_testing_standards(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """CLAUDE.md includes testing standards."""
        md = generate_claude_md(_completed_workflow_state)
        assert "TDD" in md
        assert "80%" in md

    def test_claude_md_references_rules(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """CLAUDE.md references .claude/rules/ files."""
        md = generate_claude_md(_completed_workflow_state)
        assert ".claude/rules/" in md
        assert "tdd-rule.md" in md
        assert "spec-compliance.md" in md

    def test_claude_md_includes_agentcore_when_applicable(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """CLAUDE.md includes AgentCore info when deployment target is AgentCore."""
        md = generate_claude_md(_completed_workflow_state)
        assert "AgentCore" in md

    def test_claude_md_includes_decisions(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """CLAUDE.md includes key decisions from the inception."""
        md = generate_claude_md(_completed_workflow_state)
        assert "Use DynamoDB" in md


# ---------------------------------------------------------------------------
# Deliverables: generate_test_cases
# ---------------------------------------------------------------------------


class TestGenerateTestCases:
    """Tests for the generate_test_cases deliverable function."""

    def test_test_cases_has_tc_for_each_capability(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """Each capability AC gets a corresponding test case."""
        md = generate_test_cases(_completed_workflow_state)
        assert "TC-001" in md
        assert "knowledge base search" in md

    def test_test_cases_has_tc_for_channels(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """Each channel gets a corresponding test case."""
        md = generate_test_cases(_completed_workflow_state)
        assert "Slack" in md

    def test_test_cases_has_standard_checks(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """Test cases include standard checks (coverage, secrets)."""
        md = generate_test_cases(_completed_workflow_state)
        assert "80%" in md
        assert "hardcoded secrets" in md

    def test_test_cases_follow_format(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """Test cases follow the TC format with Description, Setup, Steps, Expected, Type."""
        md = generate_test_cases(_completed_workflow_state)
        assert "**Description:**" in md
        assert "**Setup:**" in md
        assert "**Steps:**" in md
        assert "**Expected:**" in md
        assert "**Type:**" in md


# ---------------------------------------------------------------------------
# Deliverables: generate_agentcore_refs
# ---------------------------------------------------------------------------


class TestGenerateAgentcoreRefs:
    """Tests for the generate_agentcore_refs deliverable function."""

    def test_returns_content_for_agentcore_deploy(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """Returns content when deployment target is AgentCore."""
        result = generate_agentcore_refs(_completed_workflow_state)
        assert result is not None
        assert "AgentCore" in result

    def test_returns_none_for_non_agentcore(self) -> None:
        """Returns None when deployment target is not AgentCore."""
        state = WorkflowState(
            project_name="test",
            tenant_id="t1",
            repo="org/test",
        )
        state.audit_entries.append({
            "timestamp": "2026-04-03T00:00:00+00:00",
            "stage_id": "requirements",
            "user_input": {
                "deployment_target": "Self-hosted",
            },
        })
        result = generate_agentcore_refs(state)
        assert result is None

    def test_agentcore_refs_include_deployment_config(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """AgentCore refs include deployment configuration."""
        result = generate_agentcore_refs(_completed_workflow_state)
        assert result is not None
        assert "bedrock_agentcore" in result

    def test_agentcore_refs_include_memory_pattern(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """AgentCore refs include memory integration pattern."""
        result = generate_agentcore_refs(_completed_workflow_state)
        assert result is not None
        assert "Memory" in result

    def test_agentcore_refs_include_cedar(
        self, _completed_workflow_state: WorkflowState
    ) -> None:
        """AgentCore refs include Cedar policy template."""
        result = generate_agentcore_refs(_completed_workflow_state)
        assert result is not None
        assert "cedar" in result.lower() or "Cedar" in result
