from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


class HarnessInvocationError(RuntimeError):
    """AgentCore Harness did not return a usable assistant response."""


@dataclass(frozen=True)
class HarnessLimits:
    max_iterations: int = 10
    max_tokens: int = 8_000
    timeout_seconds: int = 240


def collect_harness_text(
    events: Iterable[dict[str, Any]],
    *,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    parts: list[str] = []
    role: str | None = None
    stop_reason: str | None = None
    for event in events:
        runtime_error = event.get("runtimeClientError")
        if isinstance(runtime_error, dict):
            raise HarnessInvocationError(
                str(runtime_error.get("message") or "AgentCore runtime error")
            )
        message_start = event.get("messageStart")
        if isinstance(message_start, dict):
            role = message_start.get("role")
        delta_event = event.get("contentBlockDelta")
        if role == "assistant" and isinstance(delta_event, dict):
            delta = delta_event.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("text"), str):
                parts.append(delta["text"])
                if on_progress is not None:
                    on_progress("".join(parts).strip())
        message_stop = event.get("messageStop")
        if isinstance(message_stop, dict):
            value = message_stop.get("stopReason")
            if isinstance(value, str):
                stop_reason = value

    text = "".join(parts).strip()
    if not text:
        raise HarnessInvocationError("AgentCore returned no assistant text")
    warnings = {
        "max_tokens": "The model reached its per-turn token limit.",
        "max_iterations_exceeded": "The agent reached its iteration limit.",
        "timeout_exceeded": "The agent reached its execution time limit.",
        "max_output_tokens_exceeded": "The agent reached its output budget.",
    }
    if stop_reason in warnings:
        text = f"{text}\n\n_{warnings[stop_reason]}_"
    elif stop_reason == "tool_use":
        raise HarnessInvocationError("AgentCore requested an unsupported inline tool result")
    return text


class HarnessInvoker:
    def __init__(
        self,
        client: Any,
        *,
        harness_arn: str,
        qualifier: str,
        limits: HarnessLimits | None = None,
    ) -> None:
        self._client = client
        self._harness_arn = harness_arn
        self._qualifier = qualifier
        self._limits = limits or HarnessLimits()

    def invoke(
        self,
        *,
        prompt: str,
        runtime_session_id: str,
        actor_id: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> str:
        operation = getattr(self._client, "invoke_harness", None)
        if operation is None:
            raise HarnessInvocationError("Installed boto3/botocore does not support invoke_harness")
        response = operation(
            harnessArn=self._harness_arn,
            qualifier=self._qualifier,
            runtimeSessionId=runtime_session_id,
            actorId=actor_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            maxIterations=self._limits.max_iterations,
            maxTokens=self._limits.max_tokens,
            timeoutSeconds=self._limits.timeout_seconds,
        )
        return collect_harness_text(response["stream"], on_progress=on_progress)
