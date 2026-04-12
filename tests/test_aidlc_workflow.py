"""Tests for the AIDLC Workflow Engine.

TDD test suite covering state persistence, stage transitions, conditional
skipping, approval gates, audit logging, artifact generation, and
complexity assessment.

Traces to spec §6.1 acceptance criteria: AC-1, AC-2, AC-3, AC-4, AC-21–AC-24.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform_agent.plato.aidlc.stages import StageID, Stage, STAGE_DEFINITIONS, get_stage
from platform_agent.plato.aidlc.state import (
    StageStatus,
    StageState,
    WorkflowState,
    Complexity,
    save_state,
    load_state,
    append_audit,
)
from platform_agent.plato.aidlc.questions import Question, QuestionType, get_questions_for_stage
from platform_agent.plato.aidlc.artifacts import (
    compile_requirements,
    compile_user_stories,
    compile_workflow_plan,
    compile_app_design,
    compile_units,
)
from platform_agent.plato.aidlc.workflow import AIDLCWorkflow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Provide a temporary directory simulating a project workspace."""
    return tmp_path


@pytest.fixture
def workflow(tmp_project: Path) -> AIDLCWorkflow:
    """Create a fresh AIDLCWorkflow instance."""
    return AIDLCWorkflow(
        project_name="test-project",
        tenant_id="tenant-001",
        repo="org/test-project",
        base_dir=tmp_project,
    )


@pytest.fixture
def started_workflow(workflow: AIDLCWorkflow) -> AIDLCWorkflow:
    """Return a workflow that has been started (first stage IN_PROGRESS)."""
    workflow.start()
    return workflow


@pytest.fixture
def requirements_answers() -> dict:
    """Sample answers for the Requirements stage."""
    return {
        "target_users": "internal teams",
        "channels": ["Slack"],
        "capabilities": ["knowledge base search"],
        "data_sources": ["internal wiki"],
        "compliance": "none",
        "deployment_target": "AgentCore",
    }


@pytest.fixture
def complex_requirements_answers() -> dict:
    """Answers that should trigger COMPLEX assessment."""
    return {
        "target_users": "external customers and internal teams",
        "channels": ["Slack", "API", "web"],
        "capabilities": ["knowledge base search", "CRM integration", "payment processing"],
        "data_sources": ["CRM", "databases", "APIs", "knowledge base"],
        "compliance": "PII handling, audit trail, SOC2",
        "deployment_target": "hybrid",
    }


@pytest.fixture
def simple_requirements_answers() -> dict:
    """Answers that should trigger SIMPLE assessment."""
    return {
        "target_users": "internal teams",
        "channels": ["Slack"],
        "capabilities": ["knowledge base search"],
        "data_sources": ["internal wiki"],
        "compliance": "none",
        "deployment_target": "AgentCore",
    }


# ---------------------------------------------------------------------------
# TC-001: State persists across save/load cycle (AC-21)
# ---------------------------------------------------------------------------


class TestStatePersistence:
    """Tests for state persistence across save/load cycles."""

    def test_save_load_roundtrip(self, tmp_project: Path) -> None:
        """TC-001: State persists across save/load cycle.

        Traces to: AC-21 (State persists across sessions)
        """
        state = WorkflowState(
            project_name="test-project",
            tenant_id="tenant-001",
            repo="org/test-project",
            current_stage_id=StageID.REQUIREMENTS,
            complexity=Complexity.STANDARD,
        )
        state.stages[StageID.WORKSPACE_DETECTION] = StageState(
            stage_id=StageID.WORKSPACE_DETECTION,
            status=StageStatus.APPROVED,
        )

        save_state(state, tmp_project)
        loaded = load_state(tmp_project)

        assert loaded.project_name == "test-project"
        assert loaded.tenant_id == "tenant-001"
        assert loaded.repo == "org/test-project"
        assert loaded.current_stage_id == StageID.REQUIREMENTS
        assert loaded.complexity == Complexity.STANDARD
        assert loaded.stages[StageID.WORKSPACE_DETECTION].status == StageStatus.APPROVED

    def test_state_file_is_json(self, tmp_project: Path) -> None:
        """State file is JSON, not markdown (per sprint spec)."""
        state = WorkflowState(
            project_name="test-project",
            tenant_id="tenant-001",
            repo="org/test-project",
        )
        save_state(state, tmp_project)

        state_path = tmp_project / "aidlc-docs" / "aidlc-state.json"
        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert data["project_name"] == "test-project"

    def test_load_nonexistent_raises(self, tmp_project: Path) -> None:
        """Loading from a directory with no state file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_state(tmp_project)


# ---------------------------------------------------------------------------
# TC-002: Workflow resumes from last approved stage (AC-22)
# ---------------------------------------------------------------------------


class TestWorkflowResume:
    """Tests for workflow resume across sessions."""

    def test_resume_from_persisted_state(self, tmp_project: Path) -> None:
        """TC-002: Workflow resumes from last approved stage.

        Traces to: AC-22 (Workflow resumes from last approved stage on reconnect)
        """
        wf = AIDLCWorkflow(
            project_name="test-project",
            tenant_id="tenant-001",
            repo="org/test-project",
            base_dir=tmp_project,
        )
        wf.start()
        # Complete workspace detection
        wf.submit_answers(StageID.WORKSPACE_DETECTION, {"existing_repo": False})
        wf.approve_stage(StageID.WORKSPACE_DETECTION)
        wf.save()

        # Simulate new session — load from disk
        restored = AIDLCWorkflow.load(tmp_project)
        current = restored.get_current_stage()
        assert current is not None
        assert current.id == StageID.REQUIREMENTS
        assert restored.state.stages[StageID.WORKSPACE_DETECTION].status == StageStatus.APPROVED


# ---------------------------------------------------------------------------
# TC-003: Conditional stages skipped for SIMPLE complexity (AC-23)
# ---------------------------------------------------------------------------


class TestConditionalStageSkipping:
    """Tests for complexity-based conditional stage skipping."""

    def test_simple_skips_conditional_stages(
        self, tmp_project: Path, simple_requirements_answers: dict
    ) -> None:
        """TC-003: Conditional stages skipped for SIMPLE complexity.

        Traces to: AC-23 (Conditional stages correctly skipped based on complexity)
        """
        wf = AIDLCWorkflow(
            project_name="simple-project",
            tenant_id="tenant-001",
            repo="org/simple-project",
            base_dir=tmp_project,
        )
        wf.start()

        # Complete workspace detection
        wf.submit_answers(StageID.WORKSPACE_DETECTION, {"existing_repo": False})
        wf.approve_stage(StageID.WORKSPACE_DETECTION)

        # Complete requirements — triggers SIMPLE complexity
        wf.submit_answers(StageID.REQUIREMENTS, simple_requirements_answers)
        wf.approve_stage(StageID.REQUIREMENTS)

        # USER_STORIES is conditional — should be skipped for SIMPLE
        assert wf.should_skip_stage(StageID.USER_STORIES)

        # Current stage should jump past USER_STORIES to WORKFLOW_PLANNING
        current = wf.get_current_stage()
        assert current is not None
        assert current.id == StageID.WORKFLOW_PLANNING

    def test_complex_includes_all_stages(
        self, tmp_project: Path, complex_requirements_answers: dict
    ) -> None:
        """COMPLEX projects include all conditional stages."""
        wf = AIDLCWorkflow(
            project_name="complex-project",
            tenant_id="tenant-001",
            repo="org/complex-project",
            base_dir=tmp_project,
        )
        wf.start()

        wf.submit_answers(StageID.WORKSPACE_DETECTION, {"existing_repo": True})
        wf.approve_stage(StageID.WORKSPACE_DETECTION)

        wf.submit_answers(StageID.REQUIREMENTS, complex_requirements_answers)
        wf.approve_stage(StageID.REQUIREMENTS)

        # USER_STORIES should NOT be skipped for COMPLEX
        assert not wf.should_skip_stage(StageID.USER_STORIES)
        current = wf.get_current_stage()
        assert current is not None
        assert current.id == StageID.USER_STORIES


# ---------------------------------------------------------------------------
# TC-004 / TC-006: Cannot advance without approval (AC-2, AC-24)
# ---------------------------------------------------------------------------


class TestApprovalGates:
    """Tests for approval gate enforcement."""

    def test_cannot_advance_without_approval(self, started_workflow: AIDLCWorkflow) -> None:
        """TC-004/TC-006: Cannot advance without approval.

        Traces to: AC-2 (No stage proceeds without explicit human approval)
                   AC-24 (State machine prevents skipping unapproved stages)
        """
        # Submit answers but don't approve
        started_workflow.submit_answers(
            StageID.WORKSPACE_DETECTION, {"existing_repo": False}
        )
        # Attempting to submit answers for next stage should fail
        with pytest.raises(ValueError, match="not the current.*in-progress"):
            started_workflow.submit_answers(
                StageID.REQUIREMENTS, {"target_users": "internal"}
            )

    def test_cannot_approve_unapproved_stage(self, started_workflow: AIDLCWorkflow) -> None:
        """Cannot approve a stage that hasn't had answers submitted."""
        with pytest.raises(ValueError, match="awaiting approval"):
            started_workflow.approve_stage(StageID.WORKSPACE_DETECTION)

    def test_cannot_skip_non_conditional_stage(self, started_workflow: AIDLCWorkflow) -> None:
        """Cannot skip a non-conditional stage."""
        with pytest.raises(ValueError, match="not conditional"):
            started_workflow.skip_stage(StageID.WORKSPACE_DETECTION)

    def test_cannot_submit_for_wrong_stage(self, started_workflow: AIDLCWorkflow) -> None:
        """Cannot submit answers for a stage that isn't the current one."""
        with pytest.raises(ValueError, match="not the current.*in-progress"):
            started_workflow.submit_answers(StageID.REQUIREMENTS, {"foo": "bar"})


# ---------------------------------------------------------------------------
# TC-005: Each stage produces artifact path (AC-1)
# ---------------------------------------------------------------------------


class TestArtifactGeneration:
    """Tests for artifact generation at each stage."""

    def test_requirements_produces_artifact(
        self, tmp_project: Path, requirements_answers: dict
    ) -> None:
        """TC-005: Each stage produces artifact path.

        Traces to: AC-1 (Each stage produces a markdown artifact in aidlc-docs/)
        """
        wf = AIDLCWorkflow(
            project_name="test-project",
            tenant_id="tenant-001",
            repo="org/test-project",
            base_dir=tmp_project,
        )
        wf.start()
        wf.submit_answers(StageID.WORKSPACE_DETECTION, {"existing_repo": False})
        wf.approve_stage(StageID.WORKSPACE_DETECTION)

        wf.submit_answers(StageID.REQUIREMENTS, requirements_answers)
        stage_state = wf.state.stages[StageID.REQUIREMENTS]
        assert stage_state.output_path is not None
        assert (tmp_project / stage_state.output_path).exists()

    def test_workspace_detection_artifact(self, started_workflow: AIDLCWorkflow) -> None:
        """Workspace detection stage produces an artifact."""
        started_workflow.submit_answers(
            StageID.WORKSPACE_DETECTION, {"existing_repo": False, "repo_url": ""}
        )
        stage_state = started_workflow.state.stages[StageID.WORKSPACE_DETECTION]
        assert stage_state.output_path is not None

    def test_artifact_compilers_produce_markdown(
        self, requirements_answers: dict
    ) -> None:
        """Artifact compilers produce non-empty markdown strings."""
        state = WorkflowState(
            project_name="test-project",
            tenant_id="tenant-001",
            repo="org/test-project",
        )
        md = compile_requirements(state, requirements_answers)
        assert isinstance(md, str)
        assert len(md) > 0
        assert "# Requirements" in md

    def test_all_artifact_compilers(self) -> None:
        """All artifact compilers produce valid markdown."""
        state = WorkflowState(
            project_name="test-project",
            tenant_id="tenant-001",
            repo="org/test-project",
        )
        answers = {"placeholder": "value"}

        for compiler, heading in [
            (compile_requirements, "# Requirements"),
            (compile_user_stories, "# User Stories"),
            (compile_workflow_plan, "# Workflow Plan"),
            (compile_app_design, "# Application Design"),
            (compile_units, "# Units"),
        ]:
            result = compiler(state, answers)
            assert isinstance(result, str)
            assert heading in result


# ---------------------------------------------------------------------------
# TC-007: Audit log captures input verbatim (AC-3)
# ---------------------------------------------------------------------------


class TestAuditLog:
    """Tests for audit logging."""

    def test_audit_captures_input_verbatim(self) -> None:
        """TC-007: Audit log captures input verbatim.

        Traces to: AC-3 (Audit log captures every human input verbatim)
        """
        state = WorkflowState(
            project_name="test-project",
            tenant_id="tenant-001",
            repo="org/test-project",
        )
        user_input = {"answer": "I want to build a Slack bot for customer support"}
        append_audit(state, user_input, StageID.REQUIREMENTS)

        assert len(state.audit_entries) == 1
        entry = state.audit_entries[0]
        assert entry["user_input"] == user_input
        assert entry["stage_id"] == StageID.REQUIREMENTS.value
        assert "timestamp" in entry

    def test_audit_preserves_multiple_entries(self) -> None:
        """Multiple audit entries are preserved in order."""
        state = WorkflowState(
            project_name="test-project",
            tenant_id="tenant-001",
            repo="org/test-project",
        )
        append_audit(state, {"q": "first"}, StageID.WORKSPACE_DETECTION)
        append_audit(state, {"q": "second"}, StageID.REQUIREMENTS)
        append_audit(state, {"q": "third"}, StageID.USER_STORIES)

        assert len(state.audit_entries) == 3
        assert state.audit_entries[0]["user_input"]["q"] == "first"
        assert state.audit_entries[2]["user_input"]["q"] == "third"


# ---------------------------------------------------------------------------
# Complexity assessment tests (AC-4)
# ---------------------------------------------------------------------------


class TestComplexityAssessment:
    """Tests for complexity assessment logic."""

    def test_simple_assessment(self, simple_requirements_answers: dict) -> None:
        """Simple project with single channel, few capabilities → SIMPLE.

        Traces to: AC-4 (Stage depth adapts based on complexity assessment)
        """
        wf = AIDLCWorkflow(
            project_name="simple",
            tenant_id="t1",
            repo="org/simple",
            base_dir=Path("/tmp/test"),
        )
        complexity = wf.assess_complexity(simple_requirements_answers)
        assert complexity == Complexity.SIMPLE

    def test_complex_assessment(self, complex_requirements_answers: dict) -> None:
        """Multi-channel, compliance, many data sources → COMPLEX."""
        wf = AIDLCWorkflow(
            project_name="complex",
            tenant_id="t1",
            repo="org/complex",
            base_dir=Path("/tmp/test"),
        )
        complexity = wf.assess_complexity(complex_requirements_answers)
        assert complexity == Complexity.COMPLEX

    def test_standard_assessment(self) -> None:
        """Middle-ground answers → STANDARD."""
        answers = {
            "target_users": "internal teams",
            "channels": ["Slack", "API"],
            "capabilities": ["knowledge base search", "task management"],
            "data_sources": ["internal wiki", "databases"],
            "compliance": "audit trail",
            "deployment_target": "AgentCore",
        }
        wf = AIDLCWorkflow(
            project_name="standard",
            tenant_id="t1",
            repo="org/standard",
            base_dir=Path("/tmp/test"),
        )
        complexity = wf.assess_complexity(answers)
        assert complexity == Complexity.STANDARD


# ---------------------------------------------------------------------------
# Reject → re-submit flow
# ---------------------------------------------------------------------------


class TestRejectResubmit:
    """Tests for the reject and re-submit flow."""

    def test_reject_returns_to_in_progress(self, started_workflow: AIDLCWorkflow) -> None:
        """Rejecting a stage returns it to IN_PROGRESS for re-work."""
        started_workflow.submit_answers(
            StageID.WORKSPACE_DETECTION, {"existing_repo": False}
        )
        assert (
            started_workflow.state.stages[StageID.WORKSPACE_DETECTION].status
            == StageStatus.AWAITING_APPROVAL
        )

        started_workflow.reject_stage(StageID.WORKSPACE_DETECTION, feedback="Need more detail")
        assert (
            started_workflow.state.stages[StageID.WORKSPACE_DETECTION].status
            == StageStatus.IN_PROGRESS
        )

    def test_reject_then_resubmit(self, started_workflow: AIDLCWorkflow) -> None:
        """Can re-submit answers after rejection."""
        started_workflow.submit_answers(
            StageID.WORKSPACE_DETECTION, {"existing_repo": False}
        )
        started_workflow.reject_stage(StageID.WORKSPACE_DETECTION, feedback="Incomplete")

        # Re-submit with better answers
        started_workflow.submit_answers(
            StageID.WORKSPACE_DETECTION, {"existing_repo": True, "repo_url": "github.com/org/repo"}
        )
        assert (
            started_workflow.state.stages[StageID.WORKSPACE_DETECTION].status
            == StageStatus.AWAITING_APPROVAL
        )

    def test_cannot_reject_non_awaiting_stage(self, started_workflow: AIDLCWorkflow) -> None:
        """Cannot reject a stage that isn't awaiting approval."""
        with pytest.raises(ValueError, match="awaiting approval"):
            started_workflow.reject_stage(StageID.WORKSPACE_DETECTION, feedback="nope")


# ---------------------------------------------------------------------------
# Stage definitions tests
# ---------------------------------------------------------------------------


class TestStageDefinitions:
    """Tests for stage definitions."""

    def test_all_stages_defined(self) -> None:
        """All StageID values have a corresponding Stage definition."""
        for stage_id in StageID:
            stage = get_stage(stage_id)
            assert stage is not None
            assert stage.id == stage_id

    def test_conditional_stages(self) -> None:
        """USER_STORIES, APP_DESIGN, and UNITS are conditional."""
        assert get_stage(StageID.USER_STORIES).is_conditional
        assert get_stage(StageID.APP_DESIGN).is_conditional
        assert get_stage(StageID.UNITS).is_conditional

    def test_non_conditional_stages(self) -> None:
        """WORKSPACE_DETECTION, REQUIREMENTS, and WORKFLOW_PLANNING are not conditional."""
        assert not get_stage(StageID.WORKSPACE_DETECTION).is_conditional
        assert not get_stage(StageID.REQUIREMENTS).is_conditional
        assert not get_stage(StageID.WORKFLOW_PLANNING).is_conditional

    def test_stage_order_is_correct(self) -> None:
        """STAGE_DEFINITIONS list is in the correct execution order."""
        ids = [s.id for s in STAGE_DEFINITIONS]
        expected = [
            StageID.WORKSPACE_DETECTION,
            StageID.REQUIREMENTS,
            StageID.USER_STORIES,
            StageID.WORKFLOW_PLANNING,
            StageID.APP_DESIGN,
            StageID.UNITS,
        ]
        assert ids == expected

    def test_stages_have_output_artifacts(self) -> None:
        """Each stage has an output_artifact path."""
        for stage in STAGE_DEFINITIONS:
            assert stage.output_artifact is not None
            assert stage.output_artifact.endswith(".md")


# ---------------------------------------------------------------------------
# Question generator tests
# ---------------------------------------------------------------------------


class TestQuestionGenerator:
    """Tests for the structured question generator."""

    def test_questions_returned_for_each_stage(self) -> None:
        """Each stage returns at least one question."""
        for stage_id in StageID:
            questions = get_questions_for_stage(stage_id, Complexity.STANDARD)
            assert len(questions) > 0, f"No questions for {stage_id}"

    def test_question_structure(self) -> None:
        """Questions have required fields."""
        questions = get_questions_for_stage(StageID.REQUIREMENTS, Complexity.STANDARD)
        for q in questions:
            assert isinstance(q, Question)
            assert q.id
            assert q.text
            assert isinstance(q.question_type, QuestionType)
            assert isinstance(q.required, bool)

    def test_complexity_affects_depth(self) -> None:
        """COMPLEX projects get more questions than SIMPLE ones."""
        simple_qs = get_questions_for_stage(StageID.REQUIREMENTS, Complexity.SIMPLE)
        complex_qs = get_questions_for_stage(StageID.REQUIREMENTS, Complexity.COMPLEX)
        assert len(complex_qs) >= len(simple_qs)

    def test_multiple_choice_has_options(self) -> None:
        """MULTIPLE_CHOICE questions have at least 2 options."""
        questions = get_questions_for_stage(StageID.REQUIREMENTS, Complexity.STANDARD)
        mc_questions = [q for q in questions if q.question_type == QuestionType.MULTIPLE_CHOICE]
        for q in mc_questions:
            assert q.options is not None
            assert len(q.options) >= 2


# ---------------------------------------------------------------------------
# Workflow status and decisions tests
# ---------------------------------------------------------------------------


class TestWorkflowStatus:
    """Tests for workflow status reporting and decision logging."""

    def test_get_status(self, started_workflow: AIDLCWorkflow) -> None:
        """get_status returns a summary dict with expected keys."""
        status = started_workflow.get_status()
        assert "current_stage" in status
        assert "progress" in status
        assert "completion_pct" in status
        assert status["current_stage"] == StageID.WORKSPACE_DETECTION.value

    def test_completion_percentage(self, started_workflow: AIDLCWorkflow) -> None:
        """Completion percentage reflects approved stages."""
        status = started_workflow.get_status()
        assert status["completion_pct"] == 0

    def test_record_decision(self, started_workflow: AIDLCWorkflow) -> None:
        """record_decision adds to the decisions log."""
        started_workflow.record_decision(
            "Use DynamoDB for persistence", "Already in the stack"
        )
        assert len(started_workflow.state.decisions) == 1
        assert started_workflow.state.decisions[0]["decision"] == "Use DynamoDB for persistence"
        assert started_workflow.state.decisions[0]["rationale"] == "Already in the stack"

    def test_workflow_complete(self, tmp_project: Path) -> None:
        """Workflow reports complete when all required stages are approved."""
        wf = AIDLCWorkflow(
            project_name="test",
            tenant_id="t1",
            repo="org/test",
            base_dir=tmp_project,
        )
        wf.start()

        # Complete all stages sequentially
        stage_answers = {
            StageID.WORKSPACE_DETECTION: {"existing_repo": False},
            StageID.REQUIREMENTS: {
                "target_users": "internal teams",
                "channels": ["Slack"],
                "capabilities": ["kb search"],
                "data_sources": ["wiki"],
                "compliance": "none",
                "deployment_target": "AgentCore",
            },
            StageID.WORKFLOW_PLANNING: {"stages": ["build", "test"], "parallel": False},
        }

        for stage_id, answers in stage_answers.items():
            current = wf.get_current_stage()
            if current is None:
                break
            # Skip conditional stages for SIMPLE
            if current.is_conditional and wf.should_skip_stage(current.id):
                wf.skip_stage(current.id, reason="Simple project")
                current = wf.get_current_stage()
                if current is None:
                    break
            if current.id in stage_answers:
                wf.submit_answers(current.id, stage_answers[current.id])
                wf.approve_stage(current.id)

        # All non-conditional stages done, conditional ones skipped → complete
        final_stage = wf.get_current_stage()
        # If there are remaining conditional stages, skip them
        while final_stage is not None and final_stage.is_conditional and wf.should_skip_stage(final_stage.id):
            wf.skip_stage(final_stage.id, reason="Simple project")
            final_stage = wf.get_current_stage()

        assert wf.get_current_stage() is None
        status = wf.get_status()
        assert status["completion_pct"] == 100


# ---------------------------------------------------------------------------
# Full happy-path workflow test
# ---------------------------------------------------------------------------


class TestFullWorkflowHappyPath:
    """End-to-end test of the complete AIDLC workflow."""

    def test_full_standard_workflow(self, tmp_project: Path) -> None:
        """Complete workflow for a STANDARD complexity project."""
        wf = AIDLCWorkflow(
            project_name="my-agent",
            tenant_id="tenant-001",
            repo="org/my-agent",
            base_dir=tmp_project,
        )
        wf.start()

        # Stage 1: Workspace Detection
        wf.submit_answers(StageID.WORKSPACE_DETECTION, {"existing_repo": True, "repo_url": "github.com/org/my-agent"})
        wf.approve_stage(StageID.WORKSPACE_DETECTION)

        # Stage 2: Requirements (triggers STANDARD complexity)
        req_answers = {
            "target_users": "internal teams",
            "channels": ["Slack", "API"],
            "capabilities": ["knowledge base search", "ticket management"],
            "data_sources": ["CRM", "wiki"],
            "compliance": "audit trail",
            "deployment_target": "AgentCore",
        }
        wf.submit_answers(StageID.REQUIREMENTS, req_answers)
        wf.approve_stage(StageID.REQUIREMENTS)
        assert wf.state.complexity == Complexity.STANDARD

        # Stage 3: User Stories (STANDARD → included)
        current = wf.get_current_stage()
        assert current is not None
        assert current.id == StageID.USER_STORIES
        wf.submit_answers(StageID.USER_STORIES, {
            "actors": ["support agent", "manager"],
            "journeys": ["search kb", "escalate ticket"],
        })
        wf.approve_stage(StageID.USER_STORIES)

        # Stage 4: Workflow Planning
        wf.submit_answers(StageID.WORKFLOW_PLANNING, {
            "stages": ["foundation", "tools", "testing"],
            "parallel": False,
        })
        wf.approve_stage(StageID.WORKFLOW_PLANNING)

        # Stage 5: App Design (STANDARD → included)
        current = wf.get_current_stage()
        assert current is not None
        assert current.id == StageID.APP_DESIGN
        wf.submit_answers(StageID.APP_DESIGN, {
            "components": ["agent", "tools", "memory"],
            "apis": ["search", "ticket"],
        })
        wf.approve_stage(StageID.APP_DESIGN)

        # Stage 6: Units (STANDARD → may be skipped)
        current = wf.get_current_stage()
        assert current is not None
        assert current.id == StageID.UNITS
        wf.submit_answers(StageID.UNITS, {
            "units": ["unit-1: foundation", "unit-2: tools"],
            "dependencies": {"unit-2": ["unit-1"]},
        })
        wf.approve_stage(StageID.UNITS)

        # Workflow complete
        assert wf.get_current_stage() is None
        status = wf.get_status()
        assert status["completion_pct"] == 100

        # Verify artifacts were created
        aidlc_docs = tmp_project / "aidlc-docs"
        assert (aidlc_docs / "requirements.md").exists()
        assert (aidlc_docs / "user-stories.md").exists()
        assert (aidlc_docs / "workflow-plan.md").exists()
        assert (aidlc_docs / "application-design.md").exists()
        assert (aidlc_docs / "units.md").exists()

        # Verify state persistence
        wf.save()
        restored = AIDLCWorkflow.load(tmp_project)
        assert restored.get_current_stage() is None
        assert restored.state.complexity == Complexity.STANDARD
