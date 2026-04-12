"""Tests for AIDLCTelemetryHook and workflow engine event emission.

Covers: hook event handling, metric calculations, EMF output, and
workflow-engine-level event emission verification.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from platform_agent.foundation.hooks.aidlc_telemetry_hook import (
    AIDLCTelemetryHook,
)
from platform_agent.plato.aidlc.workflow import AIDLCWorkflow
from platform_agent.plato.aidlc.stages import StageID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def hook() -> AIDLCTelemetryHook:
    """Return a hook with auto_emit disabled for isolation."""
    return AIDLCTelemetryHook(auto_emit=False)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def workflow(tmp_project: Path) -> AIDLCWorkflow:
    return AIDLCWorkflow(
        project_name="test-project",
        tenant_id="tenant-001",
        repo="org/test-project",
        base_dir=tmp_project,
    )


# ===========================================================================
# AIDLCTelemetryHook Tests
# ===========================================================================


class TestWorkflowStartedEvent:
    """1. test_workflow_started_event — handle_event records workflow start."""

    def test_workflow_started_event(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "my-project",
            "complexity": "standard",
        })

        assert hook.workflow_start_time is not None
        assert hook._complexity == "standard"
        # First stage should be tracked as started
        assert "workspace_detection" in hook._stage_started_at


class TestStageSubmittedEvent:
    """2. test_stage_submitted_event — records stage submission time."""

    def test_stage_submitted_event(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })

        assert "workspace_detection" in hook._stage_submitted_at


class TestStageApprovedEvent:
    """3. test_stage_approved_event — records approval and calculates wait time."""

    def test_stage_approved_event(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })
        hook.handle_event("aidlc.stage_approved", {
            "stage_id": "workspace_detection",
        })

        assert "workspace_detection" in hook._completed_stages
        assert "workspace_detection" in hook.approval_wait_times
        assert hook.approval_wait_times["workspace_detection"] >= 0
        assert "workspace_detection" in hook.stage_durations
        assert hook.stage_durations["workspace_detection"] >= 0


class TestStageRejectedEvent:
    """4. test_stage_rejected_event — increments rework count."""

    def test_stage_rejected_event(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })
        hook.handle_event("aidlc.stage_rejected", {
            "stage_id": "workspace_detection",
        })

        assert hook.rework_count["workspace_detection"] == 1


class TestStageSkippedEvent:
    """5. test_stage_skipped_event — records skip."""

    def test_stage_skipped_event(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "simple",
        })
        hook.handle_event("aidlc.stage_skipped", {
            "stage_id": "user_stories",
            "reason": "SIMPLE project",
        })

        assert "user_stories" in hook._completed_stages


class TestWorkflowCompletedEvent:
    """6. test_workflow_completed_event — records completion."""

    def test_workflow_completed_event(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })
        hook.handle_event("aidlc.workflow_completed", {
            "completion_pct": 100,
        })

        assert hook.workflow_end_time is not None


class TestFullWorkflowFlow:
    """7. test_full_workflow_flow — simulate complete workflow, verify all metrics."""

    def test_full_workflow_flow(self, hook: AIDLCTelemetryHook) -> None:
        # Start
        hook.handle_event("aidlc.workflow_started", {
            "project": "full-test", "complexity": "standard",
        })

        stages = [
            "workspace_detection",
            "requirements",
            "user_stories",
            "workflow_planning",
            "app_design",
            "units",
        ]

        for stage_id in stages:
            hook.handle_event("aidlc.stage_submitted", {
                "stage_id": stage_id,
                "status": "awaiting_approval",
            })
            hook.handle_event("aidlc.stage_approved", {
                "stage_id": stage_id,
            })

        hook.handle_event("aidlc.workflow_completed", {"completion_pct": 100})

        # Verify all metrics populated
        metrics = hook.get_aidlc_metrics()
        assert metrics["workflow_start_time"] is not None
        assert metrics["workflow_end_time"] is not None
        assert metrics["complexity"] == "standard"
        assert len(metrics["completed_stages"]) == 6
        assert len(metrics["stage_durations"]) == 6
        assert len(metrics["approval_wait_times"]) == 6

        # Funnel should show all stages completed
        funnel = hook.get_funnel_data()
        assert all(entry["completed"] for entry in funnel)


class TestStageDurationCalculation:
    """8. test_stage_duration_calculation — duration = approved_time - started_time."""

    def test_stage_duration_calculation(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })

        # Manually set a known start time
        hook._stage_started_at["workspace_detection"] = time.time() - 5.0

        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })
        hook.handle_event("aidlc.stage_approved", {
            "stage_id": "workspace_detection",
        })

        duration = hook.stage_durations["workspace_detection"]
        assert duration >= 4.9  # At least ~5 seconds


class TestApprovalWaitCalculation:
    """9. test_approval_wait_calculation — wait = approved_time - submitted_time."""

    def test_approval_wait_calculation(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })

        # Manually backdate the submitted timestamp
        hook._stage_submitted_at["workspace_detection"] = time.time() - 3.0

        hook.handle_event("aidlc.stage_approved", {
            "stage_id": "workspace_detection",
        })

        wait = hook.approval_wait_times["workspace_detection"]
        assert wait >= 2.9  # At least ~3 seconds


class TestReworkTracking:
    """10. test_rework_tracking — reject twice, verify rework_count = 2."""

    def test_rework_tracking(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })

        # First rejection
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })
        hook.handle_event("aidlc.stage_rejected", {
            "stage_id": "workspace_detection",
        })

        # Second rejection
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })
        hook.handle_event("aidlc.stage_rejected", {
            "stage_id": "workspace_detection",
        })

        assert hook.rework_count["workspace_detection"] == 2


class TestGetFunnelData:
    """11. test_get_funnel_data — returns correct ordered stage completion data."""

    def test_get_funnel_data(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })
        hook.handle_event("aidlc.stage_approved", {
            "stage_id": "workspace_detection",
        })
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "requirements",
            "status": "awaiting_approval",
        })
        hook.handle_event("aidlc.stage_approved", {
            "stage_id": "requirements",
        })

        funnel = hook.get_funnel_data()

        # Correct order
        assert funnel[0]["stage_id"] == "workspace_detection"
        assert funnel[1]["stage_id"] == "requirements"
        assert funnel[2]["stage_id"] == "user_stories"

        # First two completed, rest not
        assert funnel[0]["completed"] is True
        assert funnel[1]["completed"] is True
        assert funnel[2]["completed"] is False
        assert funnel[3]["completed"] is False


class TestEmitCloudwatchEmf:
    """12. test_emit_cloudwatch_emf — valid EMF JSON with correct namespace/dimensions."""

    def test_emit_cloudwatch_emf(self, hook: AIDLCTelemetryHook, capsys) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })
        hook.handle_event("aidlc.stage_approved", {
            "stage_id": "workspace_detection",
        })
        hook.handle_event("aidlc.workflow_completed", {"completion_pct": 100})

        # Reset auto_emit effect — call manually
        hook.emit_cloudwatch_emf()

        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]
        assert len(lines) >= 1

        # Check first EMF line (per-stage metric for workspace_detection)
        emf = json.loads(lines[0])
        assert "_aws" in emf
        cw_metrics = emf["_aws"]["CloudWatchMetrics"][0]
        assert cw_metrics["Namespace"] == "Plato/AIDLC"
        assert ["StageName", "Complexity"] in cw_metrics["Dimensions"]
        assert emf["Complexity"] == "standard"

        # Check metric names across all lines
        all_metric_names: set[str] = set()
        for line in lines:
            parsed = json.loads(line)
            for m in parsed["_aws"]["CloudWatchMetrics"][0]["Metrics"]:
                all_metric_names.add(m["Name"])

        assert "AIDLCStageDuration" in all_metric_names
        assert "AIDLCApprovalWaitTime" in all_metric_names
        assert "AIDLCReworkCount" in all_metric_names
        assert "AIDLCWorkflowCompleted" in all_metric_names


class TestClearResetsState:
    """13. test_clear_resets_state — clear() resets everything."""

    def test_clear_resets_state(self, hook: AIDLCTelemetryHook) -> None:
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })
        hook.handle_event("aidlc.stage_submitted", {
            "stage_id": "workspace_detection",
            "status": "awaiting_approval",
        })
        hook.handle_event("aidlc.stage_approved", {
            "stage_id": "workspace_detection",
        })

        assert hook.workflow_start_time is not None
        assert len(hook._completed_stages) > 0

        hook.clear()

        assert hook.workflow_start_time is None
        assert hook.workflow_end_time is None
        assert hook._complexity is None
        assert len(hook.stage_transitions) == 0
        assert len(hook.stage_durations) == 0
        assert len(hook.approval_wait_times) == 0
        assert len(hook.drop_offs) == 0
        assert len(hook.rework_count) == 0
        assert len(hook._completed_stages) == 0

        metrics = hook.get_aidlc_metrics()
        assert metrics["workflow_start_time"] is None


class TestAutoEmit:
    """14. test_auto_emit — emits on workflow_completed when auto_emit=True."""

    def test_auto_emit_on_completed(self) -> None:
        hook = AIDLCTelemetryHook(auto_emit=True)
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })

        with patch.object(hook, "emit_cloudwatch_emf") as mock_emit:
            hook.handle_event("aidlc.workflow_completed", {"completion_pct": 100})
            mock_emit.assert_called_once()

    def test_auto_emit_disabled(self) -> None:
        hook = AIDLCTelemetryHook(auto_emit=False)
        hook.handle_event("aidlc.workflow_started", {
            "project": "p", "complexity": "standard",
        })

        with patch.object(hook, "emit_cloudwatch_emf") as mock_emit:
            hook.handle_event("aidlc.workflow_completed", {"completion_pct": 100})
            mock_emit.assert_not_called()


# ===========================================================================
# Workflow Engine Event Emission Tests
# ===========================================================================


class TestWorkflowEmitsEvents:
    """15. test_workflow_emits_events — verify AIDLCWorkflow emits correct events."""

    def test_start_emits_workflow_started(self, workflow: AIDLCWorkflow) -> None:
        events: list[tuple[str, dict]] = []
        workflow.on_event(lambda t, d: events.append((t, d)))

        workflow.start()

        assert len(events) == 1
        assert events[0][0] == "aidlc.workflow_started"
        assert events[0][1]["project"] == "test-project"
        assert events[0][1]["complexity"] == "standard"

    def test_submit_emits_stage_submitted(self, workflow: AIDLCWorkflow) -> None:
        events: list[tuple[str, dict]] = []
        workflow.start()
        workflow.on_event(lambda t, d: events.append((t, d)))

        workflow.submit_answers(StageID.WORKSPACE_DETECTION, {"existing_repo": False})

        submitted_events = [e for e in events if e[0] == "aidlc.stage_submitted"]
        assert len(submitted_events) == 1
        assert submitted_events[0][1]["stage_id"] == "workspace_detection"
        assert submitted_events[0][1]["status"] == "awaiting_approval"

    def test_approve_emits_stage_approved(self, workflow: AIDLCWorkflow) -> None:
        events: list[tuple[str, dict]] = []
        workflow.start()
        workflow.submit_answers(StageID.WORKSPACE_DETECTION, {"existing_repo": False})
        workflow.on_event(lambda t, d: events.append((t, d)))

        workflow.approve_stage(StageID.WORKSPACE_DETECTION)

        approved_events = [e for e in events if e[0] == "aidlc.stage_approved"]
        assert len(approved_events) == 1
        assert approved_events[0][1]["stage_id"] == "workspace_detection"

    def test_reject_emits_stage_rejected(self, workflow: AIDLCWorkflow) -> None:
        events: list[tuple[str, dict]] = []
        workflow.start()
        workflow.submit_answers(StageID.WORKSPACE_DETECTION, {"existing_repo": False})
        workflow.on_event(lambda t, d: events.append((t, d)))

        workflow.reject_stage(StageID.WORKSPACE_DETECTION, feedback="needs more")

        rejected_events = [e for e in events if e[0] == "aidlc.stage_rejected"]
        assert len(rejected_events) == 1
        assert rejected_events[0][1]["stage_id"] == "workspace_detection"

    def test_skip_emits_stage_skipped(self, workflow: AIDLCWorkflow) -> None:
        events: list[tuple[str, dict]] = []
        workflow.start()
        workflow.on_event(lambda t, d: events.append((t, d)))

        workflow.skip_stage(StageID.USER_STORIES, reason="Simple project")

        skipped_events = [e for e in events if e[0] == "aidlc.stage_skipped"]
        assert len(skipped_events) == 1
        assert skipped_events[0][1]["stage_id"] == "user_stories"
        assert skipped_events[0][1]["reason"] == "Simple project"

    def test_workflow_completed_emits_event(self, tmp_project: Path) -> None:
        """Complete a SIMPLE workflow and verify workflow_completed is emitted."""
        events: list[tuple[str, dict]] = []
        wf = AIDLCWorkflow(
            project_name="simple",
            tenant_id="t1",
            repo="org/simple",
            base_dir=tmp_project,
        )
        wf.on_event(lambda t, d: events.append((t, d)))
        wf.start()

        # Complete workspace detection
        wf.submit_answers(StageID.WORKSPACE_DETECTION, {"existing_repo": False})
        wf.approve_stage(StageID.WORKSPACE_DETECTION)

        # Complete requirements (triggers SIMPLE)
        wf.submit_answers(StageID.REQUIREMENTS, {
            "target_users": "internal teams",
            "channels": ["Slack"],
            "capabilities": ["kb"],
            "data_sources": ["wiki"],
            "compliance": "none",
            "deployment_target": "AgentCore",
        })
        wf.approve_stage(StageID.REQUIREMENTS)
        # USER_STORIES auto-skipped for SIMPLE

        # Complete workflow_planning
        wf.submit_answers(StageID.WORKFLOW_PLANNING, {"stages": ["build"]})
        wf.approve_stage(StageID.WORKFLOW_PLANNING)
        # APP_DESIGN and UNITS auto-skipped for SIMPLE

        completed_events = [e for e in events if e[0] == "aidlc.workflow_completed"]
        assert len(completed_events) == 1
        assert completed_events[0][1]["completion_pct"] == 100


class TestEventCallbackErrorHandled:
    """16. test_event_callback_error_handled — callback exception doesn't break workflow."""

    def test_event_callback_error_handled(self, workflow: AIDLCWorkflow) -> None:
        def bad_callback(event_type: str, data: dict) -> None:
            raise RuntimeError("Callback exploded!")

        good_events: list[tuple[str, dict]] = []

        workflow.on_event(bad_callback)
        workflow.on_event(lambda t, d: good_events.append((t, d)))

        # Should not raise despite bad_callback
        workflow.start()

        # Good callback should still have received the event
        assert len(good_events) == 1
        assert good_events[0][0] == "aidlc.workflow_started"
