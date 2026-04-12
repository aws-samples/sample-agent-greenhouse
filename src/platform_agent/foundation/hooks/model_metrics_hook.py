"""ModelMetricsHook — tracks LLM call metrics for performance monitoring.

Uses Strands HookProvider API for proper lifecycle integration.
Subscribes to BeforeModelCallEvent / AfterModelCallEvent when available.

Note on token tracking: Strands SDK (1.33.0) does not expose token usage
(input_tokens, output_tokens) or cache_hit in AfterModelCallEvent. Token
tracking requires either a Strands SDK update or OTEL instrumentation
(Phase 4). This hook tracks what IS available: model_id, latency, stop_reason.
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
    from strands.hooks.events import BeforeModelCallEvent, AfterModelCallEvent

    _HAS_MODEL_HOOKS = True
except ImportError:
    _HAS_MODEL_HOOKS = False


# Cost lookup table (USD per million tokens).
# Kept for future use when token data becomes available via OTEL integration
# (Phase 4). Cost estimation requires token counts not currently exposed by
# Strands AfterModelCallEvent.
_COST_TABLE: dict[str, dict[str, float]] = {
    "claude-opus": {"input": 15.0, "output": 75.0},
    "claude-sonnet": {"input": 3.0, "output": 15.0},
    "claude-haiku": {"input": 0.25, "output": 0.25},
}


def _estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a model call.

    Uses a simple lookup table. Falls back to sonnet pricing for unknown models.

    Note: Currently unused at runtime because Strands SDK does not expose token
    counts. Retained for future OTEL integration (Phase 4).
    """
    # Match model ID to cost table by checking substrings
    cost_key = "claude-sonnet"  # default
    for key in _COST_TABLE:
        if key in model_id.lower():
            cost_key = key
            break

    rates = _COST_TABLE[cost_key]
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000


def _extract_model_id(event) -> str:
    """Extract model_id from a Strands event safely.

    Strands BeforeModelCallEvent/AfterModelCallEvent expose the agent via
    ``event.agent``, whose ``.model.get_config()`` returns a dict that may
    contain ``model_id``.
    """
    try:
        config = event.agent.model.get_config()
        return config.get("model_id", "unknown")
    except Exception:
        return "unknown"


class ModelMetricsHook(HookBase):
    """Hook that tracks LLM model call metrics.

    Records model_id, latency, and stop_reason for each call.
    Token counts and cost estimation are NOT available from the Strands SDK
    (1.33.0) — those require OTEL instrumentation (Phase 4).
    """

    def __init__(
        self,
        *,
        skill_name: str | None = None,
        auto_emit: bool = True,
    ) -> None:
        self.skill_name = skill_name
        self.auto_emit = auto_emit
        self._call_history: list[dict[str, Any]] = []
        self._pending_calls: dict[int, dict[str, Any]] = {}
        self._call_counter: int = 0

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_MODEL_HOOKS:
            registry.add_callback(BeforeModelCallEvent, self.on_before_model_call)
            registry.add_callback(AfterModelCallEvent, self.on_after_model_call)

    def on_before_model_call(self, event) -> None:
        """Record model call start time and model ID."""
        model_id = _extract_model_id(event)

        self._call_counter += 1
        call_id = self._call_counter

        self._pending_calls[call_id] = {
            "model_id": model_id,
            "start_time": time.time(),
        }

        # Store call_id via invocation_state (mutable dict) for correlation.
        # HookEvent attributes are read-only; writing to event directly crashes.
        inv_state = getattr(event, "invocation_state", None)
        if isinstance(inv_state, dict):
            inv_state["_plato_call_id"] = call_id
        else:
            # Fallback: store mapping by event identity
            self._pending_calls[f"_eid:{id(event)}"] = call_id

    def on_after_model_call(self, event) -> None:
        """Record model call completion with latency and stop reason.

        Strands AfterModelCallEvent provides:
        - event.agent (Agent instance)
        - event.stop_response (ModelStopResponse with stop_reason + message)
        - event.exception, event.retry

        Token usage and cache_hit are NOT available in this event.
        """
        # Retrieve call_id from invocation_state or fallback mapping
        inv_state = getattr(event, "invocation_state", None)
        call_id = None
        if isinstance(inv_state, dict):
            call_id = inv_state.pop("_plato_call_id", None)
        if call_id is None:
            call_id = self._pending_calls.pop(f"_eid:{id(event)}", None)

        pending = self._pending_calls.pop(call_id, None) if call_id else None
        start_time = pending["start_time"] if pending else time.time()
        model_id = (pending["model_id"] if pending else None) or _extract_model_id(event)

        end_time = time.time()
        latency_ms = (end_time - start_time) * 1000

        # Extract stop_reason from event.stop_response (ModelStopResponse)
        stop_reason = None
        stop_response = getattr(event, "stop_response", None)
        if stop_response is not None:
            stop_reason = getattr(stop_response, "stop_reason", None)

        entry: dict[str, Any] = {
            "model_id": model_id,
            "latency_ms": latency_ms,
            "stop_reason": stop_reason,
            "timestamp": end_time,
        }

        self._call_history.append(entry)

        logger.info(
            json.dumps(
                {
                    "event": "model_call_complete",
                    "model_id": model_id,
                    "latency_ms": latency_ms,
                    "stop_reason": stop_reason,
                }
            )
        )

        if self.auto_emit:
            self.emit_cloudwatch_emf()

    def get_model_metrics(self) -> dict[str, Any]:
        """Return summary of model call metrics.

        Returns:
            Dictionary with total_calls, avg_latency_ms.
            Token totals and cost estimation are omitted because the Strands
            SDK does not expose token counts in AfterModelCallEvent.
        """
        total_calls = len(self._call_history)

        latencies = [c["latency_ms"] for c in self._call_history]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        return {
            "total_calls": total_calls,
            "avg_latency_ms": avg_latency,
        }

    def emit_cloudwatch_emf(self) -> None:
        """Emit CloudWatch Embedded Metric Format JSON to stdout.

        Namespace: Plato/Agent, Dimensions: ModelId, SkillName.
        Only emits ModelCallLatency and ModelCallCount because token data
        is not available from the Strands SDK.
        """
        metrics = self.get_model_metrics()
        skill = self.skill_name or "unknown"

        # Determine most common model_id
        model_id = "unknown"
        if self._call_history:
            model_counts: dict[str, int] = {}
            for c in self._call_history:
                mid = c["model_id"]
                model_counts[mid] = model_counts.get(mid, 0) + 1
            model_id = max(model_counts, key=model_counts.get)  # type: ignore[arg-type]

        emf_log: dict[str, Any] = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "Plato/Agent",
                        "Dimensions": [["ModelId", "SkillName"]],
                        "Metrics": [
                            {"Name": "ModelCallLatency", "Unit": "Milliseconds"},
                            {"Name": "ModelCallCount", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "ModelId": model_id,
            "SkillName": skill,
            "ModelCallLatency": metrics["avg_latency_ms"],
            "ModelCallCount": metrics["total_calls"],
        }
        print(json.dumps(emf_log))

    def clear(self) -> None:
        """Reset all tracked state."""
        self._call_history.clear()
        self._pending_calls.clear()
        self._call_counter = 0
