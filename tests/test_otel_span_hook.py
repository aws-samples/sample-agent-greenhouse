"""Tests for OTELSpanHook — OpenTelemetry span creation with graceful degradation.

Tests:
1. No-op when OTEL is not available
2. Register hooks subscribes to all 6 event types
3. Invocation span created and ended
4. Tool span created as child span
5. Model span created with model_id attribute
6. AIDLC custom span creation
7. Span error status on tool failure
8. Graceful behavior without OTEL installed
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

import platform_agent.foundation.hooks.otel_span_hook as otel_mod
from platform_agent.foundation.hooks.otel_span_hook import (
    OTELSpanHook,
    _HAS_OTEL,
)


# Create a mock StatusCode to inject when testing the OTEL-available path.
class _MockStatusCode:
    OK = "OK"
    ERROR = "ERROR"


@pytest.fixture
def hook() -> OTELSpanHook:
    """Create a fresh OTELSpanHook."""
    return OTELSpanHook()


def _make_invocation_event():
    """Create a mock BeforeInvocationEvent."""
    event = MagicMock()
    event.messages = [{"role": "user", "content": "hello"}]
    return event


def _make_after_invocation_event(*, result="success"):
    """Create a mock AfterInvocationEvent.

    AfterInvocationEvent has result (not exception).
    result=None simulates an error invocation.
    """
    event = MagicMock(spec=[])
    event.result = result
    return event


def _make_tool_event(tool_name: str = "read_file", tool_use_id: str = "tu_001"):
    """Create a mock BeforeToolCallEvent / AfterToolCallEvent."""
    event = MagicMock()
    event.tool_use = {
        "toolUseId": tool_use_id,
        "name": tool_name,
        "input": {},
    }
    event.tool_result = "result text"
    event.status = None
    return event


def _make_tool_error_event(tool_name: str = "bad_tool", tool_use_id: str = "tu_err"):
    """Create a mock AfterToolCallEvent with error status."""
    event = MagicMock()
    event.tool_use = {
        "toolUseId": tool_use_id,
        "name": tool_name,
        "input": {},
    }
    event.tool_result = {"status": "error", "message": "something failed"}
    event.status = "error"
    return event


def _make_model_event(model_id: str = "claude-sonnet-4"):
    """Create a mock Before/AfterModelCallEvent."""
    event = MagicMock()
    event.agent.model.get_config.return_value = {"model_id": model_id}
    event.stop_response = MagicMock()
    event.stop_response.stop_reason = "end_turn"
    return event


class _OTELPatch:
    """Context manager that makes OTEL appear available by injecting StatusCode."""

    def __enter__(self):
        self._orig_has_otel = otel_mod._HAS_OTEL
        self._had_status_code = hasattr(otel_mod, "StatusCode")
        if self._had_status_code:
            self._orig_status_code = otel_mod.StatusCode
        otel_mod._HAS_OTEL = True
        otel_mod.StatusCode = _MockStatusCode
        return self

    def __exit__(self, *args):
        otel_mod._HAS_OTEL = self._orig_has_otel
        if self._had_status_code:
            otel_mod.StatusCode = self._orig_status_code
        else:
            delattr(otel_mod, "StatusCode")


def _patch_otel_available():
    """Context manager that makes OTEL appear available by injecting StatusCode."""
    return _OTELPatch()


class TestNoOTELAvailable:
    """Test that when _HAS_OTEL is False, all methods are no-ops."""

    def test_no_otel_available(self):
        """When OTEL is not installed, hook should work without errors."""
        hook = OTELSpanHook()

        # Without OTEL, _tracer should be None
        if not _HAS_OTEL:
            assert hook._tracer is None

        # All methods should be callable without error
        hook.on_before_invocation(_make_invocation_event())
        hook.on_after_invocation(_make_after_invocation_event())
        hook.on_before_tool_call(_make_tool_event())
        hook.on_after_tool_call(_make_tool_event())
        hook.on_before_model_call(_make_model_event())
        hook.on_after_model_call(_make_model_event())

        # AIDLC span returns None when no OTEL
        if not _HAS_OTEL:
            result = hook.create_aidlc_span("requirements", {"key": "value"})
            assert result is None


class TestRegisterHooks:
    """Test that register_hooks subscribes to all 6 event types."""

    def test_register_hooks(self, hook: OTELSpanHook):
        """Should register callbacks for all 6 event types."""
        registry = MagicMock()
        hook.register_hooks(registry)

        # When Strands hooks are available, 6 callbacks should be registered
        try:
            from strands.hooks.events import (
                BeforeInvocationEvent,
                AfterInvocationEvent,
                BeforeToolCallEvent,
                AfterToolCallEvent,
                BeforeModelCallEvent,
                AfterModelCallEvent,
            )
            assert registry.add_callback.call_count == 6
            event_types = [call.args[0] for call in registry.add_callback.call_args_list]
            assert BeforeInvocationEvent in event_types
            assert AfterInvocationEvent in event_types
            assert BeforeToolCallEvent in event_types
            assert AfterToolCallEvent in event_types
            assert BeforeModelCallEvent in event_types
            assert AfterModelCallEvent in event_types
        except ImportError:
            # Without Strands, no callbacks registered
            assert registry.add_callback.call_count == 0


class TestInvocationSpan:
    """Test invocation span lifecycle with mocked OTEL."""

    def test_invocation_span_created(self):
        """Mock tracer, verify span plato.invoke started/ended."""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        hook = OTELSpanHook()
        hook._tracer = mock_tracer

        with _patch_otel_available():
            hook.on_before_invocation(_make_invocation_event())
            mock_tracer.start_span.assert_called_with("plato.invoke")
            assert hook._root_span is mock_span

            hook.on_after_invocation(_make_after_invocation_event())
            mock_span.set_status.assert_called_once_with("OK")
            mock_span.end.assert_called_once()
            assert hook._root_span is None

    def test_invocation_span_error_status(self):
        """On error (result=None), span should be marked ERROR."""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        hook = OTELSpanHook()
        hook._tracer = mock_tracer

        with _patch_otel_available():
            hook.on_before_invocation(_make_invocation_event())
            hook.on_after_invocation(_make_after_invocation_event(result=None))

            mock_span.set_status.assert_called_with(
                "ERROR", "invocation returned no result"
            )


class TestToolSpan:
    """Test tool call span creation."""

    def test_tool_span_created(self):
        """Verify child span plato.tool.{name} is created."""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        hook = OTELSpanHook()
        hook._tracer = mock_tracer

        with _patch_otel_available():
            event = _make_tool_event("read_file", "tu_100")
            hook.on_before_tool_call(event)
            mock_tracer.start_span.assert_called_with("plato.tool.read_file")
            assert "tool:tu_100" in hook._active_spans

            hook.on_after_tool_call(event)
            mock_span.set_status.assert_called_with("OK")
            mock_span.end.assert_called_once()
            assert "tool:tu_100" not in hook._active_spans


class TestModelSpan:
    """Test model call span creation."""

    def test_model_span_created(self):
        """Verify child span plato.model.invoke with model_id attribute."""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        hook = OTELSpanHook()
        hook._tracer = mock_tracer

        with _patch_otel_available():
            event = _make_model_event("claude-sonnet-4")
            hook.on_before_model_call(event)
            mock_tracer.start_span.assert_called_with("plato.model.invoke")
            mock_span.set_attribute.assert_any_call("plato.model.id", "claude-sonnet-4")

            hook.on_after_model_call(event)
            mock_span.end.assert_called_once()


class TestAIDLCSpan:
    """Test AIDLC custom span creation."""

    def test_create_aidlc_span(self):
        """Verify custom span plato.aidlc.{stage_id}."""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        hook = OTELSpanHook()
        hook._tracer = mock_tracer

        with _patch_otel_available():
            result = hook.create_aidlc_span(
                "requirements",
                {"plato.aidlc.complexity": "moderate"},
            )
            mock_tracer.start_span.assert_called_with("plato.aidlc.requirements")
            mock_span.set_attribute.assert_any_call("plato.aidlc.stage_id", "requirements")
            mock_span.set_attribute.assert_any_call("plato.aidlc.complexity", "moderate")
            assert result is mock_span

    def test_create_aidlc_span_no_attributes(self):
        """AIDLC span works without extra attributes."""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        hook = OTELSpanHook()
        hook._tracer = mock_tracer

        with _patch_otel_available():
            result = hook.create_aidlc_span("design")
            mock_tracer.start_span.assert_called_with("plato.aidlc.design")
            assert result is mock_span


class TestSpanErrorStatus:
    """Test that tool call errors set span ERROR status."""

    def test_span_error_status(self):
        """When tool call has error, span status = ERROR."""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        hook = OTELSpanHook()
        hook._tracer = mock_tracer

        with _patch_otel_available():
            before_event = _make_tool_event("bad_tool", "tu_err")
            hook.on_before_tool_call(before_event)

            after_event = _make_tool_error_event("bad_tool", "tu_err")
            hook.on_after_tool_call(after_event)

            mock_span.set_status.assert_called_with("ERROR", "tool call failed")


class TestGracefulWithoutOTEL:
    """Test graceful handling when OTEL is not installed."""

    def test_graceful_without_otel(self):
        """All methods should work without error when OTEL not installed."""
        hook = OTELSpanHook()

        # Force _HAS_OTEL to False and _tracer to None
        with patch.object(otel_mod, "_HAS_OTEL", False):
            hook._tracer = None

            # All lifecycle methods should be no-ops
            hook.on_before_invocation(_make_invocation_event())
            hook.on_after_invocation(_make_after_invocation_event())
            hook.on_before_tool_call(_make_tool_event())
            hook.on_after_tool_call(_make_tool_event())
            hook.on_before_model_call(_make_model_event())
            hook.on_after_model_call(_make_model_event())

            # AIDLC span returns None
            assert hook.create_aidlc_span("test") is None

            # Active spans should be empty
            assert hook.get_active_spans() == []


class TestGetActiveSpans:
    """Test get_active_spans debugging method."""

    def test_get_active_spans(self):
        """Returns list of active span keys."""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        hook = OTELSpanHook()
        hook._tracer = mock_tracer

        with _patch_otel_available():
            hook.on_before_tool_call(_make_tool_event("tool_a", "tu_1"))
            hook.on_before_tool_call(_make_tool_event("tool_b", "tu_2"))

            active = hook.get_active_spans()
            assert "tool:tu_1" in active
            assert "tool:tu_2" in active
            assert len(active) == 2
