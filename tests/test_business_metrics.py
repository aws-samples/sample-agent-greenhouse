"""Tests for BusinessMetricsHook — business-level metric tracking.

Tests:
1. Skill usage tracking
2. Unique developer tracking
3. Session depth
4. Artifact detection (submit_answers)
5. Review artifact detection
6. Issue artifact detection
7. Flow completion tracking
8. CloudWatch EMF emission
9. get_business_metrics structure
10. Auto-emit on after_invocation
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from platform_agent.foundation.hooks.business_metrics_hook import (
    BusinessMetricsHook,
)


@pytest.fixture
def hook() -> BusinessMetricsHook:
    """Create a fresh BusinessMetricsHook with auto_emit disabled."""
    return BusinessMetricsHook(auto_emit=False)


@pytest.fixture
def hook_auto_emit() -> BusinessMetricsHook:
    """Create a BusinessMetricsHook with auto_emit enabled."""
    return BusinessMetricsHook(auto_emit=True)


def _make_invocation_event(*, skill_name: str | None = None, session_id: str | None = None):
    """Create a mock BeforeInvocationEvent."""
    event = MagicMock()
    agent = MagicMock()
    agent.skill_name = skill_name
    agent.session_id = session_id
    event.agent = agent
    event.messages = [{"role": "user", "content": "hello"}]
    return event


def _make_tool_event(tool_name: str, tool_input: dict | None = None, tool_result: str = "ok"):
    """Create a mock AfterToolCallEvent."""
    event = MagicMock()
    event.tool_use = {
        "toolUseId": "tu_001",
        "name": tool_name,
        "input": tool_input or {},
    }
    event.tool_result = tool_result
    return event


class TestSkillUsageTracking:
    """Test skill_usage_count tracking."""

    def test_skill_usage_tracking(self, hook: BusinessMetricsHook):
        """Invoke twice with different skills, verify counts."""
        event1 = _make_invocation_event(skill_name="aidlc_inception")
        event2 = _make_invocation_event(skill_name="code_review")
        event3 = _make_invocation_event(skill_name="aidlc_inception")

        hook.on_before_invocation(event1)
        hook.on_before_invocation(event2)
        hook.on_before_invocation(event3)

        assert hook.skill_usage_count["aidlc_inception"] == 2
        assert hook.skill_usage_count["code_review"] == 1


class TestUniqueDeveloperTracking:
    """Test unique_developers tracking."""

    def test_unique_developer_tracking(self, hook: BusinessMetricsHook):
        """Multiple invocations with same session → same developer."""
        event1 = _make_invocation_event(session_id="sess_abc")
        event2 = _make_invocation_event(session_id="sess_abc")
        event3 = _make_invocation_event(session_id="sess_xyz")

        hook.on_before_invocation(event1)
        hook.on_before_invocation(event2)
        hook.on_before_invocation(event3)

        # sess_abc produces same hash twice, sess_xyz different
        assert len(hook.unique_developers) == 2


class TestSessionDepth:
    """Test session depth tracking."""

    def test_session_depth(self, hook: BusinessMetricsHook):
        """Multiple tool calls in one session should increase depth."""
        # Set up session context via invocation.
        inv_event = _make_invocation_event(session_id="sess_001")
        hook.on_before_invocation(inv_event)

        # Simulate 3 tool calls.
        for _ in range(3):
            tool_event = _make_tool_event("read_file")
            hook.on_after_tool_call(tool_event)

        assert hook.session_depths.get("sess_001", 0) == 3


class TestArtifactDetection:
    """Test artifact detection from tool calls."""

    def test_artifact_detection(self, hook: BusinessMetricsHook):
        """aidlc_submit_answers with stage requirements → spec artifact."""
        inv_event = _make_invocation_event()
        hook.on_before_invocation(inv_event)

        tool_event = _make_tool_event(
            "aidlc_submit_answers",
            tool_input={"stage_id": "requirements", "answers_json": "{}"},
        )
        hook.on_after_tool_call(tool_event)

        assert hook.artifact_counts.get("spec", 0) == 1

    def test_units_stage_counts_as_test_cases(self, hook: BusinessMetricsHook):
        """aidlc_submit_answers with stage units → test_cases artifact."""
        inv_event = _make_invocation_event()
        hook.on_before_invocation(inv_event)

        tool_event = _make_tool_event(
            "aidlc_submit_answers",
            tool_input={"stage_id": "units"},
        )
        hook.on_after_tool_call(tool_event)

        assert hook.artifact_counts.get("test_cases", 0) == 1

    def test_review_artifact_detection(self, hook: BusinessMetricsHook):
        """create_pull_request_review → review artifact."""
        inv_event = _make_invocation_event()
        hook.on_before_invocation(inv_event)

        tool_event = _make_tool_event("create_pull_request_review")
        hook.on_after_tool_call(tool_event)

        assert hook.artifact_counts.get("review", 0) == 1

    def test_issue_artifact_detection(self, hook: BusinessMetricsHook):
        """create_github_issue → issue artifact."""
        inv_event = _make_invocation_event()
        hook.on_before_invocation(inv_event)

        tool_event = _make_tool_event("create_github_issue")
        hook.on_after_tool_call(tool_event)

        assert hook.artifact_counts.get("issue", 0) == 1

    def test_non_artifact_tool_not_counted(self, hook: BusinessMetricsHook):
        """Random tool calls should not count as artifacts."""
        inv_event = _make_invocation_event()
        hook.on_before_invocation(inv_event)

        tool_event = _make_tool_event("read_file")
        hook.on_after_tool_call(tool_event)

        assert hook.artifact_counts == {}


class TestInvocationCompletion:
    """Test flow completion tracking."""

    def test_invocation_completion(self, hook: BusinessMetricsHook):
        """Start + complete invocation should count both."""
        inv_event = _make_invocation_event(skill_name="inception")
        hook.on_before_invocation(inv_event)

        after_event = MagicMock()
        hook.on_after_invocation(after_event)

        assert hook.invocation_completions["started"] == 1
        assert hook.invocation_completions["completed"] == 1

    def test_flow_partial(self, hook: BusinessMetricsHook):
        """Two starts, one completion → 50% rate."""
        for _ in range(2):
            hook.on_before_invocation(_make_invocation_event())
        hook.on_after_invocation(MagicMock())

        metrics = hook.get_business_metrics()
        assert metrics["invocation_completion_rate"] == pytest.approx(50.0)


class TestEmitCloudwatchEMF:
    """Test EMF emission."""

    def test_emit_cloudwatch_emf(self, hook: BusinessMetricsHook, capsys):
        """Valid EMF with correct namespace/dimensions."""
        hook.on_before_invocation(_make_invocation_event(skill_name="inception"))
        hook.on_after_tool_call(_make_tool_event(
            "aidlc_submit_answers", tool_input={"stage_id": "requirements"},
        ))
        hook.on_after_invocation(MagicMock())

        hook.emit_cloudwatch_emf()
        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        # First line: main EMF log
        emf = json.loads(lines[0])
        assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "Plato/Business"
        assert "SkillName" in emf["_aws"]["CloudWatchMetrics"][0]["Dimensions"][0]
        assert "SkillUsageCount" in emf
        assert "UniqueDevCount" in emf
        assert "SessionDepth" in emf
        assert "InvocationCompletionRate" in emf

    def test_artifact_emf_per_type(self, hook: BusinessMetricsHook, capsys):
        """Artifact EMF emitted per type."""
        hook.on_before_invocation(_make_invocation_event())
        hook.on_after_tool_call(_make_tool_event(
            "aidlc_submit_answers", tool_input={"stage_id": "requirements"},
        ))
        hook.on_after_tool_call(_make_tool_event("create_github_issue"))

        hook.emit_cloudwatch_emf()
        captured = capsys.readouterr()
        lines = [line for line in captured.out.strip().split("\n") if line]

        # Main EMF + 2 artifact EMFs (spec, issue)
        assert len(lines) >= 3
        artifact_emfs = [json.loads(l) for l in lines[1:]]
        artifact_types = {e["ArtifactType"] for e in artifact_emfs}
        assert "spec" in artifact_types
        assert "issue" in artifact_types


class TestGetBusinessMetrics:
    """Test get_business_metrics return structure."""

    def test_get_business_metrics(self, hook: BusinessMetricsHook):
        """Returns expected dict structure with all keys."""
        hook.on_before_invocation(_make_invocation_event(skill_name="test_skill"))
        hook.on_after_invocation(MagicMock())

        metrics = hook.get_business_metrics()
        assert "skill_usage_count" in metrics
        assert "unique_developer_count" in metrics
        assert "avg_session_depth" in metrics
        assert "artifact_counts" in metrics
        assert "invocation_completion_rate" in metrics
        assert isinstance(metrics["skill_usage_count"], dict)
        assert isinstance(metrics["unique_developer_count"], int)
        assert isinstance(metrics["avg_session_depth"], float)
        assert isinstance(metrics["artifact_counts"], dict)
        assert isinstance(metrics["invocation_completion_rate"], float)


class TestAutoEmit:
    """Test auto-emit behavior."""

    def test_auto_emit(self, hook_auto_emit: BusinessMetricsHook, capsys):
        """Emits on after_invocation when enabled."""
        hook_auto_emit.on_before_invocation(_make_invocation_event())
        hook_auto_emit.on_after_invocation(MagicMock())

        captured = capsys.readouterr()
        assert captured.out.strip()  # Something was printed
        emf = json.loads(captured.out.strip().split("\n")[0])
        assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "Plato/Business"

    def test_no_auto_emit_when_disabled(self, hook: BusinessMetricsHook, capsys):
        """Does not emit when auto_emit=False."""
        hook.on_before_invocation(_make_invocation_event())
        hook.on_after_invocation(MagicMock())

        captured = capsys.readouterr()
        assert captured.out.strip() == ""


class TestClear:
    """Test clear resets all state."""

    def test_clear(self, hook: BusinessMetricsHook):
        hook.on_before_invocation(_make_invocation_event(skill_name="s1"))
        hook.on_after_tool_call(_make_tool_event("create_github_issue"))
        hook.on_after_invocation(MagicMock())

        hook.clear()

        assert hook.skill_usage_count == {}
        assert hook.unique_developers == set()
        assert hook.session_depths == {}
        assert hook.artifact_counts == {}
        assert hook.invocation_completions == {"started": 0, "completed": 0}
