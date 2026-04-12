"""TelemetryHook — traces invocations and tool call spans for observability.

Uses Strands HookProvider API for proper lifecycle integration.
Emits CloudWatch EMF metrics and structured logs.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import (
        BeforeInvocationEvent,
        AfterInvocationEvent,
        BeforeToolCallEvent,
        AfterToolCallEvent,
    )

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



class TelemetryHook(HookBase):
    """Hook that traces every Plato invocation end-to-end with tool call spans.

    Captures per-invocation timing, skill context, and per-tool-call
    metrics. Stores data in-memory for retrieval and emits structured
    logs in JSON format plus CloudWatch EMF.
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        skill_name: str | None = None,
        auto_emit: bool = True,
    ) -> None:
        self.session_id = session_id
        self.skill_name = skill_name
        self.auto_emit = auto_emit
        self._invocations: list[dict[str, Any]] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._current_invocation: dict[str, Any] | None = None
        self._pending_tool_calls: dict[str, dict[str, Any]] = {}

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)
            registry.add_callback(AfterInvocationEvent, self.on_after_invocation)
            registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call)
            registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    def on_before_invocation(self, event) -> None:
        """Start tracking an invocation."""
        self._current_invocation = {
            "start_time": time.time(),
            "session_id": self.session_id,
            "skill_name": self.skill_name,
            "tool_count": 0,
        }

    def on_after_invocation(self, event) -> None:
        """Complete invocation tracking and record metrics."""
        if self._current_invocation is None:
            return

        end_time = time.time()
        self._current_invocation["end_time"] = end_time
        self._current_invocation["duration_ms"] = (
            (end_time - self._current_invocation["start_time"]) * 1000
        )
        self._invocations.append(self._current_invocation)

        logger.info(
            json.dumps(
                {
                    "event": "invocation_complete",
                    "session_id": self._current_invocation["session_id"],
                    "skill_name": self._current_invocation["skill_name"],
                    "duration_ms": self._current_invocation["duration_ms"],
                    "tool_count": self._current_invocation["tool_count"],
                }
            )
        )

        self._current_invocation = None

        if self.auto_emit:
            self.emit_cloudwatch_emf()

    def on_before_tool_call(self, event) -> None:
        """Start tracking a tool call span."""
        tool_use = getattr(event, "tool_use", {})
        tool_name = (
            tool_use.get("name", "unknown") if isinstance(tool_use, dict) else "unknown"
        )
        tool_use_id = (
            tool_use.get("toolUseId", "unknown") if isinstance(tool_use, dict) else "unknown"
        )

        self._pending_tool_calls[tool_use_id] = {
            "tool_name": tool_name,
            "start_time": time.time(),
        }

    def on_after_tool_call(self, event) -> None:
        """Complete tool call tracking and record metrics."""
        tool_use = getattr(event, "tool_use", {})
        tool_name = (
            tool_use.get("name", "unknown") if isinstance(tool_use, dict) else "unknown"
        )
        tool_use_id = (
            tool_use.get("toolUseId", "unknown") if isinstance(tool_use, dict) else "unknown"
        )
        tool_result = str(getattr(event, "tool_result", ""))

        pending = self._pending_tool_calls.pop(tool_use_id, None)
        start_time = pending["start_time"] if pending else time.time()

        end_time = time.time()
        duration_ms = (end_time - start_time) * 1000
        output_size_bytes = len(tool_result.encode("utf-8"))

        # Determine status from tool result
        status = "error" if _is_tool_error(event) else "success"

        entry = {
            "tool_name": tool_name,
            "start_time": start_time,
            "duration_ms": duration_ms,
            "status": status,
            "output_size_bytes": output_size_bytes,
        }
        self._tool_calls.append(entry)

        if self._current_invocation is not None:
            self._current_invocation["tool_count"] += 1

        logger.info(
            json.dumps(
                {
                    "event": "tool_call_complete",
                    "tool_name": tool_name,
                    "duration_ms": duration_ms,
                    "status": status,
                    "output_size_bytes": output_size_bytes,
                }
            )
        )

    def get_metrics(self) -> dict[str, Any]:
        """Return summary metrics dict.

        Returns:
            Dictionary with total_invocations, avg_duration_ms,
            tool_call_counts (by name), and error_count.
        """
        total_invocations = len(self._invocations)

        durations = [inv["duration_ms"] for inv in self._invocations if "duration_ms" in inv]
        avg_duration_ms = sum(durations) / len(durations) if durations else 0.0

        tool_call_counts: dict[str, int] = {}
        error_count = 0
        for tc in self._tool_calls:
            name = tc["tool_name"]
            tool_call_counts[name] = tool_call_counts.get(name, 0) + 1
            if tc["status"] == "error":
                error_count += 1

        return {
            "total_invocations": total_invocations,
            "avg_duration_ms": avg_duration_ms,
            "tool_call_counts": tool_call_counts,
            "error_count": error_count,
        }

    def emit_cloudwatch_emf(self) -> None:
        """Emit CloudWatch Embedded Metric Format JSON to stdout.

        The CloudWatch agent picks up EMF-formatted log lines automatically.
        Namespace: Plato/Agent, Dimensions: SkillName.
        """
        metrics = self.get_metrics()
        skill = self.skill_name or "unknown"

        emf_log: dict[str, Any] = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "Plato/Agent",
                        "Dimensions": [["SkillName"]],
                        "Metrics": [
                            {"Name": "SkillInvocationDuration", "Unit": "Milliseconds"},
                            {"Name": "SkillInvocationCount", "Unit": "Count"},
                            {"Name": "ToolCallDuration", "Unit": "Milliseconds"},
                            {"Name": "ToolCallCount", "Unit": "Count"},
                            {"Name": "ToolErrorCount", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "SkillName": skill,
            "SkillInvocationDuration": metrics["avg_duration_ms"],
            "SkillInvocationCount": metrics["total_invocations"],
            "ToolCallDuration": _avg_tool_duration(self._tool_calls),
            "ToolCallCount": sum(metrics["tool_call_counts"].values()),
            "ToolErrorCount": metrics["error_count"],
        }
        print(json.dumps(emf_log))

    def clear(self) -> None:
        """Reset all tracked state."""
        self._invocations.clear()
        self._tool_calls.clear()
        self._current_invocation = None
        self._pending_tool_calls.clear()


def _is_tool_error(event) -> bool:
    """Check if a tool call event indicates an error."""
    tool_result = getattr(event, "tool_result", None)
    if tool_result is None:
        return False
    result_str = str(tool_result).lower()
    # Check for common error indicators
    if getattr(event, "status", None) == "error":
        return True
    if isinstance(tool_result, dict) and tool_result.get("status") == "error":
        return True
    return False


def _avg_tool_duration(tool_calls: list[dict[str, Any]]) -> float:
    """Calculate average tool call duration."""
    if not tool_calls:
        return 0.0
    return sum(tc["duration_ms"] for tc in tool_calls) / len(tool_calls)
