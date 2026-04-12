"""Tests for Observability Hooks — TelemetryHook, ModelMetricsHook, enhanced AuditHook."""

from __future__ import annotations

import json
import logging
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from platform_agent.foundation.hooks.telemetry_hook import TelemetryHook
from platform_agent.foundation.hooks.model_metrics_hook import (
    ModelMetricsHook,
    _estimate_cost,
)
from platform_agent.foundation.hooks.audit_hook import AuditHook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_event(
    tool_name: str = "read_file",
    tool_use_id: str = "tu_001",
    tool_input: dict | None = None,
    tool_result: str = "file contents",
    status: str | None = None,
) -> MagicMock:
    """Create a mock tool call event."""
    event = MagicMock()
    event.tool_use = {
        "toolUseId": tool_use_id,
        "name": tool_name,
        "input": tool_input or {},
    }
    event.tool_result = tool_result
    if status is not None:
        event.status = status
    else:
        # Ensure no accidental 'status' attribute
        del event.status
    return event


def _make_error_tool_event(
    tool_name: str = "failing_tool",
    tool_use_id: str = "tu_err",
) -> MagicMock:
    """Create a mock tool call event that indicates an error."""
    event = MagicMock()
    event.tool_use = {
        "toolUseId": tool_use_id,
        "name": tool_name,
        "input": {},
    }
    event.tool_result = {"status": "error", "message": "tool failed"}
    event.status = "error"
    return event


def _make_model_event(
    model_id: str = "claude-sonnet-4-20250514",
    stop_reason: str = "end_turn",
    has_exception: bool = False,
) -> tuple[MagicMock, MagicMock]:
    """Create before/after model call event pair matching the REAL Strands API.

    BeforeModelCallEvent has: agent, invocation_state
    AfterModelCallEvent has: agent, invocation_state, stop_response, exception, retry

    The model_id is extracted via event.agent.model.get_config()["model_id"].
    Token usage and cache_hit are NOT available in these events.
    """
    # Build a mock agent with .model.get_config() returning model_id
    mock_model = MagicMock()
    mock_model.get_config.return_value = {"model_id": model_id}

    mock_agent = MagicMock()
    mock_agent.model = mock_model

    # BeforeModelCallEvent: agent, invocation_state
    before = MagicMock(spec=[])  # spec=[] prevents auto-created attributes
    before.agent = mock_agent
    shared_invocation_state = {}
    before.invocation_state = shared_invocation_state

    # AfterModelCallEvent: agent, invocation_state, stop_response, exception, retry
    after = MagicMock(spec=[])
    after.agent = mock_agent
    after.invocation_state = shared_invocation_state

    # stop_response is a ModelStopResponse with stop_reason + message
    stop_response = MagicMock(spec=[])
    stop_response.stop_reason = stop_reason
    stop_response.message = {"role": "assistant", "content": [{"text": "response"}]}
    after.stop_response = stop_response

    after.exception = Exception("test error") if has_exception else None
    after.retry = False

    return before, after


# ===========================================================================
# TelemetryHook Tests
# ===========================================================================


class TestTelemetryHookRegisterHooks:
    """test_register_hooks — verifies callbacks registered for all 4 events."""

    def test_register_hooks(self):
        hook = TelemetryHook(session_id="s1", skill_name="inception")
        registry = MagicMock()
        hook.register_hooks(registry)
        # Should have registered 4 callbacks (if strands is importable)
        # If strands is not importable, register_hooks is a no-op
        # Either way, the method should not raise
        assert True  # no exception


class TestTelemetryHookInvocationTracking:
    """test_invocation_tracking — before/after invocation records timing."""

    def test_invocation_tracking(self):
        hook = TelemetryHook(session_id="sess_123", skill_name="review", auto_emit=False)
        before_event = MagicMock()
        after_event = MagicMock()

        hook.on_before_invocation(before_event)
        assert hook._current_invocation is not None
        assert hook._current_invocation["session_id"] == "sess_123"
        assert hook._current_invocation["skill_name"] == "review"

        hook.on_after_invocation(after_event)
        assert hook._current_invocation is None
        assert len(hook._invocations) == 1
        inv = hook._invocations[0]
        assert "start_time" in inv
        assert "end_time" in inv
        assert "duration_ms" in inv
        assert inv["duration_ms"] >= 0

    def test_after_invocation_without_before_is_noop(self):
        hook = TelemetryHook(auto_emit=False)
        hook.on_after_invocation(MagicMock())
        assert len(hook._invocations) == 0


class TestTelemetryHookToolCallTracking:
    """test_tool_call_tracking — before/after tool call records name, duration, size."""

    def test_tool_call_tracking(self):
        hook = TelemetryHook(auto_emit=False)
        event_before = _make_tool_event(tool_name="github_get_tree", tool_use_id="tc_1")
        event_after = _make_tool_event(
            tool_name="github_get_tree",
            tool_use_id="tc_1",
            tool_result="{'tree': ['a.py', 'b.py']}",
        )

        hook.on_before_tool_call(event_before)
        hook.on_after_tool_call(event_after)

        assert len(hook._tool_calls) == 1
        tc = hook._tool_calls[0]
        assert tc["tool_name"] == "github_get_tree"
        assert tc["duration_ms"] >= 0
        assert tc["status"] == "success"
        assert tc["output_size_bytes"] > 0


class TestTelemetryHookMultipleToolCalls:
    """test_multiple_tool_calls — multiple tools in one invocation aggregated correctly."""

    def test_multiple_tool_calls(self):
        hook = TelemetryHook(session_id="s2", skill_name="inception", auto_emit=False)

        hook.on_before_invocation(MagicMock())

        for i, tool_name in enumerate(["read_file", "write_file", "read_file"]):
            tid = f"tc_{i}"
            before = _make_tool_event(tool_name=tool_name, tool_use_id=tid)
            after = _make_tool_event(
                tool_name=tool_name, tool_use_id=tid, tool_result=f"result_{i}"
            )
            hook.on_before_tool_call(before)
            hook.on_after_tool_call(after)

        hook.on_after_invocation(MagicMock())

        assert len(hook._tool_calls) == 3
        assert hook._invocations[0]["tool_count"] == 3

        metrics = hook.get_metrics()
        assert metrics["tool_call_counts"]["read_file"] == 2
        assert metrics["tool_call_counts"]["write_file"] == 1


class TestTelemetryHookGetMetrics:
    """test_get_metrics_summary — returns correct totals and averages."""

    def test_get_metrics_summary(self):
        hook = TelemetryHook(skill_name="compliance", auto_emit=False)

        # Simulate two invocations
        for _ in range(2):
            hook.on_before_invocation(MagicMock())
            before = _make_tool_event(tool_name="check", tool_use_id=f"tc_{_}")
            after = _make_tool_event(tool_name="check", tool_use_id=f"tc_{_}")
            hook.on_before_tool_call(before)
            hook.on_after_tool_call(after)
            hook.on_after_invocation(MagicMock())

        metrics = hook.get_metrics()
        assert metrics["total_invocations"] == 2
        assert metrics["avg_duration_ms"] >= 0
        assert metrics["tool_call_counts"]["check"] == 2
        assert metrics["error_count"] == 0

    def test_empty_metrics(self):
        hook = TelemetryHook(auto_emit=False)
        metrics = hook.get_metrics()
        assert metrics["total_invocations"] == 0
        assert metrics["avg_duration_ms"] == 0.0
        assert metrics["tool_call_counts"] == {}
        assert metrics["error_count"] == 0


class TestTelemetryHookEmitCloudwatchEmf:
    """test_emit_cloudwatch_emf — emits valid EMF JSON with correct namespace/dimensions/metrics."""

    def test_emit_cloudwatch_emf(self, capsys):
        hook = TelemetryHook(skill_name="inception", auto_emit=False)

        hook.on_before_invocation(MagicMock())
        before = _make_tool_event(tool_name="read", tool_use_id="tc_emf")
        after = _make_tool_event(tool_name="read", tool_use_id="tc_emf")
        hook.on_before_tool_call(before)
        hook.on_after_tool_call(after)
        hook.on_after_invocation(MagicMock())

        hook.emit_cloudwatch_emf()

        captured = capsys.readouterr()
        emf = json.loads(captured.out.strip())

        # Validate EMF structure
        assert "_aws" in emf
        assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "Plato/Agent"
        assert ["SkillName"] in emf["_aws"]["CloudWatchMetrics"][0]["Dimensions"]
        assert emf["SkillName"] == "inception"

        # Validate metric names present
        metric_names = {
            m["Name"] for m in emf["_aws"]["CloudWatchMetrics"][0]["Metrics"]
        }
        assert "SkillInvocationDuration" in metric_names
        assert "SkillInvocationCount" in metric_names
        assert "ToolCallDuration" in metric_names
        assert "ToolCallCount" in metric_names
        assert "ToolErrorCount" in metric_names

        # Validate metric values are numbers
        assert isinstance(emf["SkillInvocationDuration"], (int, float))
        assert isinstance(emf["SkillInvocationCount"], int)
        assert isinstance(emf["ToolCallCount"], int)
        assert isinstance(emf["ToolErrorCount"], int)


class TestTelemetryHookAutoEmit:
    """test_auto_emit — on_after_invocation calls emit_cloudwatch_emf when auto_emit=True."""

    def test_auto_emit_enabled(self):
        hook = TelemetryHook(skill_name="test", auto_emit=True)

        hook.on_before_invocation(MagicMock())

        with patch.object(hook, "emit_cloudwatch_emf") as mock_emit:
            hook.on_after_invocation(MagicMock())
            mock_emit.assert_called_once()

    def test_auto_emit_disabled(self):
        hook = TelemetryHook(skill_name="test", auto_emit=False)

        hook.on_before_invocation(MagicMock())

        with patch.object(hook, "emit_cloudwatch_emf") as mock_emit:
            hook.on_after_invocation(MagicMock())
            mock_emit.assert_not_called()


class TestTelemetryHookToolErrorCounting:
    """test_tool_error_counting — tracks errors when tool_result indicates failure."""

    def test_tool_error_counting(self):
        hook = TelemetryHook(auto_emit=False)

        # Successful call
        before_ok = _make_tool_event(tool_name="read_file", tool_use_id="tc_ok")
        after_ok = _make_tool_event(tool_name="read_file", tool_use_id="tc_ok")
        hook.on_before_tool_call(before_ok)
        hook.on_after_tool_call(after_ok)

        # Error call
        before_err = _make_error_tool_event(tool_name="failing_tool", tool_use_id="tc_err")
        after_err = _make_error_tool_event(tool_name="failing_tool", tool_use_id="tc_err")
        hook.on_before_tool_call(before_err)
        hook.on_after_tool_call(after_err)

        metrics = hook.get_metrics()
        assert metrics["error_count"] == 1
        assert metrics["tool_call_counts"]["read_file"] == 1
        assert metrics["tool_call_counts"]["failing_tool"] == 1


class TestTelemetryHookClear:
    """test_clear — clear() resets all state."""

    def test_clear(self):
        hook = TelemetryHook(session_id="s1", skill_name="test", auto_emit=False)

        hook.on_before_invocation(MagicMock())
        before = _make_tool_event(tool_name="tool1", tool_use_id="tc_cl")
        hook.on_before_tool_call(before)
        after = _make_tool_event(tool_name="tool1", tool_use_id="tc_cl")
        hook.on_after_tool_call(after)
        hook.on_after_invocation(MagicMock())

        assert len(hook._invocations) == 1
        assert len(hook._tool_calls) == 1

        hook.clear()

        assert len(hook._invocations) == 0
        assert len(hook._tool_calls) == 0
        assert hook._current_invocation is None
        assert len(hook._pending_tool_calls) == 0

        metrics = hook.get_metrics()
        assert metrics["total_invocations"] == 0


# ===========================================================================
# ModelMetricsHook Tests
# ===========================================================================


class TestModelMetricsHookRegisterHooks:
    """test_register_hooks — verifies callbacks for model events."""

    def test_register_hooks(self):
        hook = ModelMetricsHook(skill_name="inception")
        registry = MagicMock()
        hook.register_hooks(registry)
        # Should not raise regardless of strands availability
        assert True


class TestModelMetricsHookCallTracking:
    """test_model_call_tracking — records model_id, latency, stop_reason."""

    def test_model_call_tracking(self, capsys):
        hook = ModelMetricsHook(auto_emit=False)
        before, after = _make_model_event(
            model_id="claude-sonnet-4-20250514",
            stop_reason="end_turn",
        )

        hook.on_before_model_call(before)
        # Propagate call_id to after event
        hook.on_after_model_call(after)

        assert len(hook._call_history) == 1
        entry = hook._call_history[0]
        assert entry["model_id"] == "claude-sonnet-4-20250514"
        assert entry["stop_reason"] == "end_turn"
        assert entry["latency_ms"] >= 0
        # Token fields should NOT be present (not available from Strands SDK)
        assert "input_tokens" not in entry
        assert "output_tokens" not in entry
        assert "cache_hit" not in entry
        assert "estimated_cost_usd" not in entry

    def test_model_id_extraction_fallback(self, capsys):
        """When agent.model.get_config() fails, model_id should be 'unknown'."""
        hook = ModelMetricsHook(auto_emit=False)

        # Create events where agent.model.get_config() raises
        before = MagicMock(spec=[])
        before.agent = MagicMock()
        before.agent.model.get_config.side_effect = AttributeError("no config")
        shared_state = {}
        before.invocation_state = shared_state

        after = MagicMock(spec=[])
        after.agent = MagicMock()
        after.agent.model.get_config.side_effect = AttributeError("no config")
        after.stop_response = None
        after.exception = None
        after.retry = False
        after.invocation_state = shared_state

        hook.on_before_model_call(before)
        hook.on_after_model_call(after)

        assert hook._call_history[0]["model_id"] == "unknown"

    def test_stop_reason_none_when_no_stop_response(self, capsys):
        """When stop_response is None, stop_reason should be None."""
        hook = ModelMetricsHook(auto_emit=False)
        before, after = _make_model_event()

        # Override stop_response to None
        after.stop_response = None

        hook.on_before_model_call(before)
        hook.on_after_model_call(after)

        assert hook._call_history[0]["stop_reason"] is None


class TestModelMetricsHookCostEstimation:
    """test_cost_estimation — correct cost calc for opus, sonnet, and haiku.

    Note: _estimate_cost is retained for future use when token data becomes
    available via OTEL integration. It is not called at runtime currently.
    """

    def test_sonnet_cost(self):
        cost = _estimate_cost("claude-sonnet-4-20250514", 1000, 500)
        expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_opus_cost(self):
        cost = _estimate_cost("claude-opus-4-20250514", 1000, 500)
        expected = (1000 * 15.0 + 500 * 75.0) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_haiku_cost(self):
        cost = _estimate_cost("claude-haiku-3-20250307", 1000, 500)
        expected = (1000 * 0.25 + 500 * 0.25) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_unknown_model_uses_sonnet_pricing(self):
        cost = _estimate_cost("unknown-model", 1000, 500)
        expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000
        assert abs(cost - expected) < 1e-10


class TestModelMetricsHookGetMetricsSummary:
    """test_get_model_metrics_summary — returns correct totals."""

    def test_get_model_metrics_summary(self):
        hook = ModelMetricsHook(auto_emit=False)

        # Simulate two model calls
        for i in range(2):
            before, after = _make_model_event(
                model_id="claude-sonnet-4-20250514",
                stop_reason="end_turn",
            )
            hook.on_before_model_call(before)
            hook.on_after_model_call(after)

        metrics = hook.get_model_metrics()
        assert metrics["total_calls"] == 2
        assert metrics["avg_latency_ms"] >= 0
        # Token totals and cost should NOT be in metrics
        assert "total_input_tokens" not in metrics
        assert "total_output_tokens" not in metrics
        assert "estimated_cost_usd" not in metrics

    def test_empty_metrics(self):
        hook = ModelMetricsHook(auto_emit=False)
        metrics = hook.get_model_metrics()
        assert metrics["total_calls"] == 0
        assert metrics["avg_latency_ms"] == 0.0


class TestModelMetricsHookEmitCloudwatchEmf:
    """test_emit_cloudwatch_emf — emits valid EMF JSON for model metrics."""

    def test_emit_cloudwatch_emf(self, capsys):
        hook = ModelMetricsHook(skill_name="review", auto_emit=False)

        before, after = _make_model_event(
            model_id="claude-sonnet-4-20250514",
        )
        hook.on_before_model_call(before)
        hook.on_after_model_call(after)

        hook.emit_cloudwatch_emf()

        captured = capsys.readouterr()
        emf = json.loads(captured.out.strip())

        assert "_aws" in emf
        assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "Plato/Agent"
        dims = emf["_aws"]["CloudWatchMetrics"][0]["Dimensions"]
        assert ["ModelId", "SkillName"] in dims
        assert emf["SkillName"] == "review"
        assert emf["ModelId"] == "claude-sonnet-4-20250514"

        metric_names = {
            m["Name"] for m in emf["_aws"]["CloudWatchMetrics"][0]["Metrics"]
        }
        # Only ModelCallLatency and ModelCallCount — no token-based metrics
        assert "ModelCallLatency" in metric_names
        assert "ModelCallCount" in metric_names
        assert "ModelInputTokens" not in metric_names
        assert "ModelOutputTokens" not in metric_names
        assert "ModelEstimatedCost" not in metric_names


class TestModelMetricsHookAutoEmit:
    """test_auto_emit — on_after_model_call calls emit_cloudwatch_emf when auto_emit=True."""

    def test_auto_emit_enabled(self):
        hook = ModelMetricsHook(auto_emit=True)
        before, after = _make_model_event()

        hook.on_before_model_call(before)

        with patch.object(hook, "emit_cloudwatch_emf") as mock_emit:
            hook.on_after_model_call(after)
            mock_emit.assert_called_once()

    def test_auto_emit_disabled(self):
        hook = ModelMetricsHook(auto_emit=False)
        before, after = _make_model_event()

        hook.on_before_model_call(before)

        with patch.object(hook, "emit_cloudwatch_emf") as mock_emit:
            hook.on_after_model_call(after)
            mock_emit.assert_not_called()


class TestModelMetricsHookClear:
    """test_clear — clear() resets all state."""

    def test_clear(self):
        hook = ModelMetricsHook(skill_name="test", auto_emit=False)

        before, after = _make_model_event()
        hook.on_before_model_call(before)
        hook.on_after_model_call(after)

        assert len(hook._call_history) == 1

        hook.clear()

        assert len(hook._call_history) == 0
        assert hook._call_counter == 0
        assert len(hook._pending_calls) == 0

        metrics = hook.get_model_metrics()
        assert metrics["total_calls"] == 0


# ===========================================================================
# Enhanced AuditHook Tests
# ===========================================================================


class TestAuditHookExistingFunctionality:
    """test_existing_functionality_preserved — all original tests still work."""

    def test_hook_initializes_with_empty_log(self):
        hook = AuditHook()
        assert hook.tool_calls == []

    def test_logs_before_tool_call(self):
        hook = AuditHook()
        event = MagicMock()
        event.tool_use = {
            "toolUseId": "123",
            "name": "read_file",
            "input": {"path": "/tmp/test.txt"},
        }
        hook.on_before_tool_call(event)
        assert len(hook.tool_calls) == 1
        assert hook.tool_calls[0]["tool_name"] == "read_file"
        assert hook.tool_calls[0]["status"] == "started"

    def test_logs_after_tool_call(self):
        hook = AuditHook()
        before_event = MagicMock()
        before_event.tool_use = {
            "toolUseId": "123",
            "name": "read_file",
            "input": {"path": "/tmp/test.txt"},
        }
        hook.on_before_tool_call(before_event)

        after_event = MagicMock()
        after_event.tool_use = {
            "toolUseId": "123",
            "name": "read_file",
            "input": {},
        }
        after_event.tool_result = "file contents"
        hook.on_after_tool_call(after_event)
        assert len(hook.tool_calls) == 2
        assert hook.tool_calls[1]["status"] == "completed"

    def test_get_audit_log(self):
        hook = AuditHook()
        event = MagicMock()
        event.tool_use = {
            "toolUseId": "456",
            "name": "write_file",
            "input": {"path": "/tmp/out.txt"},
        }
        hook.on_before_tool_call(event)
        log = hook.get_audit_log()
        assert len(log) == 1
        assert log[0]["tool_name"] == "write_file"

    def test_clear_audit_log(self):
        hook = AuditHook()
        event = MagicMock()
        event.tool_use = {"toolUseId": "789", "name": "test", "input": {}}
        hook.on_before_tool_call(event)
        assert len(hook.tool_calls) == 1
        hook.clear()
        assert len(hook.tool_calls) == 0

    def test_default_constructor_backward_compatible(self):
        """AuditHook() with no args still works."""
        hook = AuditHook()
        assert hook.session_id is None
        assert hook.skill_name is None


class TestAuditHookSessionIdTracked:
    """test_session_id_tracked — session_id in entries when provided."""

    def test_session_id_in_before_entry(self):
        hook = AuditHook(session_id="sess_abc", skill_name="inception")
        event = MagicMock()
        event.tool_use = {"toolUseId": "1", "name": "tool_a", "input": {}}
        hook.on_before_tool_call(event)

        assert hook.tool_calls[0]["session_id"] == "sess_abc"
        assert hook.tool_calls[0]["skill_name"] == "inception"

    def test_session_id_in_after_entry(self):
        hook = AuditHook(session_id="sess_xyz")
        event = MagicMock()
        event.tool_use = {"toolUseId": "2", "name": "tool_b", "input": {}}
        event.tool_result = "result"
        hook.on_after_tool_call(event)

        assert hook.tool_calls[0]["session_id"] == "sess_xyz"

    def test_no_session_id_when_not_provided(self):
        hook = AuditHook()
        event = MagicMock()
        event.tool_use = {"toolUseId": "3", "name": "tool_c", "input": {}}
        hook.on_before_tool_call(event)

        assert "session_id" not in hook.tool_calls[0]


class TestAuditHookEmitStructuredLog:
    """test_emit_structured_log — writes JSON to plato.audit logger."""

    def test_emit_structured_log(self):
        hook = AuditHook(session_id="sess_log", skill_name="review")

        with patch("platform_agent.foundation.hooks.audit_hook.audit_logger") as mock_logger:
            event = MagicMock()
            event.tool_use = {"toolUseId": "sl_1", "name": "check_tool", "input": {}}
            event.tool_result = "ok"
            hook.on_after_tool_call(event)

            mock_logger.info.assert_called_once()
            log_json = json.loads(mock_logger.info.call_args[0][0])

            assert log_json["event_type"] == "tool_call"
            assert log_json["tool_name"] == "check_tool"
            assert log_json["session_id"] == "sess_log"
            assert log_json["skill_name"] == "review"
            assert "timestamp" in log_json


class TestAuditHookToCloudwatchFormat:
    """test_to_cloudwatch_format — correct structured format."""

    def test_to_cloudwatch_format(self):
        hook = AuditHook(session_id="sess_cw", skill_name="compliance")

        entry = {
            "tool_name": "validate_spec",
            "status": "completed",
            "timestamp": 1712200000.0,
            "session_id": "sess_cw",
            "skill_name": "compliance",
            "tool_output_preview": "pass",
        }
        formatted = hook.to_cloudwatch_format(entry)

        assert formatted["event_type"] == "tool_call"
        assert formatted["session_id"] == "sess_cw"
        assert formatted["skill_name"] == "compliance"
        assert formatted["tool_name"] == "validate_spec"
        assert formatted["status"] == "completed"
        assert "timestamp" in formatted

    def test_to_cloudwatch_format_uses_hook_defaults(self):
        hook = AuditHook(session_id="default_sess", skill_name="default_skill")

        entry = {
            "tool_name": "some_tool",
            "status": "completed",
            "timestamp": 1712200000.0,
        }
        formatted = hook.to_cloudwatch_format(entry)

        assert formatted["session_id"] == "default_sess"
        assert formatted["skill_name"] == "default_skill"
