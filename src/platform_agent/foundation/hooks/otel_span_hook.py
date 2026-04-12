"""OTELSpanHook -- creates OpenTelemetry spans when OTEL SDK is available.

Gracefully degrades to no-op when opentelemetry is not installed.
Uses try/except ImportError for all OTEL imports.

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

# ------------------------------------------------------------------
# OTEL SDK: optional dependency
# ------------------------------------------------------------------
try:
    from opentelemetry import trace
    from opentelemetry.trace import StatusCode

    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False

# ------------------------------------------------------------------
# Strands hooks: optional dependency
# ------------------------------------------------------------------
try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import (
        BeforeInvocationEvent,
        AfterInvocationEvent,
        BeforeToolCallEvent,
        AfterToolCallEvent,
        BeforeModelCallEvent,
        AfterModelCallEvent,
    )

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



class OTELSpanHook(HookBase):
    """Hook that creates OpenTelemetry spans for Plato agent operations.

    When the OTEL SDK is available, creates spans for:
    - Root invocation span (plato.invoke)
    - Tool call child spans (plato.tool.{tool_name})
    - Model call child spans (plato.model.invoke)
    - Custom AIDLC spans (plato.aidlc.{stage_id})

    When OTEL is not installed, all methods are no-ops.

    Implements strands.hooks.HookProvider for native integration.
    """

    def __init__(self, service_name: str = "plato-agent") -> None:
        self._service_name = service_name
        self._tracer = None
        self._root_span = None
        self._active_spans: dict[str, Any] = {}

        # Context attributes — set by FoundationStrandsAgent after construction.
        self.session_id: str | None = None
        self.skill_name: str | None = None
        self.tenant_id: str | None = None

        if _HAS_OTEL:
            self._tracer = trace.get_tracer(service_name)

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)
            registry.add_callback(AfterInvocationEvent, self.on_after_invocation)
            registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call)
            registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)
            registry.add_callback(BeforeModelCallEvent, self.on_before_model_call)
            registry.add_callback(AfterModelCallEvent, self.on_after_model_call)

    def on_before_invocation(self, event) -> None:
        """Start a root span ``plato.invoke``."""
        if not _HAS_OTEL or self._tracer is None:
            return

        try:
            self._root_span = self._tracer.start_span("plato.invoke")
            ctx = {}

            # Set skill/session/tenant attributes if available.
            skill_name = getattr(self, "skill_name", None)
            session_id = getattr(self, "session_id", None)
            tenant_id = getattr(self, "tenant_id", None)

            if skill_name:
                self._root_span.set_attribute("plato.skill_name", skill_name)
            if session_id:
                self._root_span.set_attribute("plato.session_id", session_id)
            if tenant_id:
                self._root_span.set_attribute("plato.tenant_id", tenant_id)
        except Exception:
            logger.debug("OTELSpanHook: error in on_before_invocation", exc_info=True)

    def on_after_invocation(self, event) -> None:
        """End the root span, set status OK or ERROR.

        AfterInvocationEvent does not have an ``exception`` attribute.
        We detect errors by checking if ``event.result`` is None (no output
        produced) or if the result contains error indicators.
        """
        if not _HAS_OTEL or self._root_span is None:
            return

        try:
            result = getattr(event, "result", None)
            if result is None:
                self._root_span.set_status(
                    StatusCode.ERROR, "invocation returned no result"
                )
            else:
                self._root_span.set_status(StatusCode.OK)

            self._root_span.end()
            self._root_span = None
        except Exception:
            logger.debug("OTELSpanHook: error in on_after_invocation", exc_info=True)

    def on_before_tool_call(self, event) -> None:
        """Start a child span ``plato.tool.{tool_name}``."""
        if not _HAS_OTEL or self._tracer is None:
            return

        try:
            tool_use = getattr(event, "tool_use", {})
            tool_name = (
                tool_use.get("name", "unknown")
                if isinstance(tool_use, dict)
                else "unknown"
            )
            tool_use_id = (
                tool_use.get("toolUseId", "unknown")
                if isinstance(tool_use, dict)
                else "unknown"
            )

            span = self._tracer.start_span(f"plato.tool.{tool_name}")
            span.set_attribute("plato.tool.name", tool_name)
            self._active_spans[f"tool:{tool_use_id}"] = span
        except Exception:
            logger.debug("OTELSpanHook: error in on_before_tool_call", exc_info=True)

    def on_after_tool_call(self, event) -> None:
        """End the tool call child span with status."""
        if not _HAS_OTEL:
            return

        try:
            tool_use = getattr(event, "tool_use", {})
            tool_use_id = (
                tool_use.get("toolUseId", "unknown")
                if isinstance(tool_use, dict)
                else "unknown"
            )

            span = self._active_spans.pop(f"tool:{tool_use_id}", None)
            if span is None:
                return

            # Check for error status.
            is_error = False
            if getattr(event, "status", None) == "error":
                is_error = True
            tool_result = getattr(event, "tool_result", None)
            if isinstance(tool_result, dict) and tool_result.get("status") == "error":
                is_error = True

            if is_error:
                span.set_status(StatusCode.ERROR, "tool call failed")
            else:
                span.set_status(StatusCode.OK)

            span.end()
        except Exception:
            logger.debug("OTELSpanHook: error in on_after_tool_call", exc_info=True)

    def on_before_model_call(self, event) -> None:
        """Start a child span ``plato.model.invoke`` with model_id."""
        if not _HAS_OTEL or self._tracer is None:
            return

        try:
            model_id = _extract_model_id(event)

            span = self._tracer.start_span("plato.model.invoke")
            span.set_attribute("plato.model.id", model_id)

            # Use counter-based key to correlate before/after.
            # Store via invocation_state (mutable dict) — HookEvent attrs are read-only.
            call_id = id(event)
            inv_state = getattr(event, "invocation_state", None)
            if isinstance(inv_state, dict):
                inv_state["_otel_call_id"] = call_id
            self._active_spans[f"model:{call_id}"] = span
        except Exception:
            logger.debug("OTELSpanHook: error in on_before_model_call", exc_info=True)

    def on_after_model_call(self, event) -> None:
        """End model call span, set model_id and stop_reason attributes."""
        if not _HAS_OTEL:
            return

        try:
            # Retrieve call_id from invocation_state or fallback to event id
            inv_state = getattr(event, "invocation_state", None)
            call_id = None
            if isinstance(inv_state, dict):
                call_id = inv_state.pop("_otel_call_id", None)
            if call_id is None:
                call_id = id(event)
            span = self._active_spans.pop(f"model:{call_id}", None)
            if span is None:
                return

            model_id = _extract_model_id(event)
            span.set_attribute("plato.model.id", model_id)

            stop_response = getattr(event, "stop_response", None)
            if stop_response is not None:
                stop_reason = getattr(stop_response, "stop_reason", None)
                if stop_reason:
                    span.set_attribute("plato.model.stop_reason", str(stop_reason))

            span.set_status(StatusCode.OK)
            span.end()
        except Exception:
            logger.debug("OTELSpanHook: error in on_after_model_call", exc_info=True)

    def create_aidlc_span(self, stage_id: str, attributes: dict[str, Any] | None = None):
        """Create a custom span ``plato.aidlc.{stage_id}`` for AIDLC flow visibility.

        Args:
            stage_id: AIDLC stage identifier (e.g. "requirements", "design").
            attributes: Optional dict of span attributes.

        Returns:
            The created span, or None if OTEL is not available.
        """
        if not _HAS_OTEL or self._tracer is None:
            return None

        try:
            span = self._tracer.start_span(f"plato.aidlc.{stage_id}")
            span.set_attribute("plato.aidlc.stage_id", stage_id)

            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)

            return span
        except Exception:
            logger.debug("OTELSpanHook: error in create_aidlc_span", exc_info=True)
            return None

    def get_active_spans(self) -> list[str]:
        """Return list of active span keys for debugging.

        Returns:
            List of active span key strings.
        """
        return list(self._active_spans.keys())


def _extract_model_id(event) -> str:
    """Extract model_id from a Strands event safely."""
    try:
        config = event.agent.model.get_config()
        return config.get("model_id", "unknown")
    except Exception:
        return "unknown"
