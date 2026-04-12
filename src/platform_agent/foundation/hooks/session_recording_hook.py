"""SessionRecordingHook -- captures full session interaction data for offline analysis.

Does NOT write to S3 directly. Collects data that the entrypoint/Lambda
will persist. Zero network I/O.

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

# Maximum length for content previews.
_MAX_PREVIEW_LENGTH = 500

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



class SessionRecordingHook(HookBase):
    """Hook that captures full session interaction data for offline analysis.

    Collects messages, tool calls, and model call data into a session record.
    Does NOT perform any network I/O -- the entrypoint/Lambda is responsible
    for persisting the data to S3.

    Implements strands.hooks.HookProvider for native integration.
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        tenant_id: str | None = None,
        skill_name: str | None = None,
    ) -> None:
        self.session_id = session_id or "unknown"
        self.tenant_id = tenant_id or "unknown"
        self.skill_name = skill_name

        self._start_time: float | None = None
        self._end_time: float | None = None
        self._messages: list[dict[str, Any]] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._model_calls: list[dict[str, Any]] = []
        self._pending_tool_calls: dict[str, float] = {}

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)
            registry.add_callback(AfterInvocationEvent, self.on_after_invocation)
            registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call)
            registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    def on_before_invocation(self, event) -> None:
        """Start recording the session."""
        try:
            self._start_time = time.time()

            # Capture the user message if available.
            messages = getattr(event, "messages", None)
            if messages:
                for msg in messages:
                    if isinstance(msg, dict):
                        role = msg.get("role", "unknown")
                        content = str(msg.get("content", ""))
                    else:
                        role = getattr(msg, "role", "unknown")
                        content = str(getattr(msg, "content", ""))

                    self._messages.append({
                        "role": role,
                        "content_preview": content[:_MAX_PREVIEW_LENGTH],
                        "timestamp": time.time(),
                    })
        except Exception:
            logger.debug(
                "SessionRecordingHook: error in on_before_invocation",
                exc_info=True,
            )

    def on_after_invocation(self, event) -> None:
        """Finalize the session recording."""
        try:
            self._end_time = time.time()
        except Exception:
            logger.debug(
                "SessionRecordingHook: error in on_after_invocation",
                exc_info=True,
            )

    def on_before_tool_call(self, event) -> None:
        """Record tool call start for duration tracking."""
        try:
            tool_use = getattr(event, "tool_use", {})
            tool_use_id = (
                tool_use.get("toolUseId", "unknown")
                if isinstance(tool_use, dict)
                else "unknown"
            )
            self._pending_tool_calls[tool_use_id] = time.time()
        except Exception:
            logger.debug(
                "SessionRecordingHook: error in on_before_tool_call",
                exc_info=True,
            )

    def on_after_tool_call(self, event) -> None:
        """Record completed tool call with input/output previews."""
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

            # Calculate duration.
            start_time = self._pending_tool_calls.pop(tool_use_id, None)
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000 if start_time else 0.0

            # Extract input preview.
            tool_input = (
                tool_use.get("input", {})
                if isinstance(tool_use, dict)
                else {}
            )
            input_preview = str(tool_input)[:_MAX_PREVIEW_LENGTH]

            # Extract output preview.
            tool_result = str(getattr(event, "tool_result", ""))
            output_preview = tool_result[:_MAX_PREVIEW_LENGTH]

            # Determine status.
            status = "success"
            if getattr(event, "status", None) == "error":
                status = "error"
            elif isinstance(getattr(event, "tool_result", None), dict):
                if getattr(event, "tool_result", {}).get("status") == "error":
                    status = "error"

            self._tool_calls.append({
                "tool_name": tool_name,
                "input_preview": input_preview,
                "output_preview": output_preview,
                "duration_ms": duration_ms,
                "status": status,
            })
        except Exception:
            logger.debug(
                "SessionRecordingHook: error in on_after_tool_call",
                exc_info=True,
            )

    def get_session_record(self) -> dict[str, Any]:
        """Return the full session record as a dictionary.

        Returns:
            Dictionary with session_id, tenant_id, start_time, end_time,
            messages, tool_calls, model_calls, and metadata.
        """
        total_duration_ms = 0.0
        if self._start_time is not None and self._end_time is not None:
            total_duration_ms = (self._end_time - self._start_time) * 1000

        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "start_time": self._start_time,
            "end_time": self._end_time,
            "messages": list(self._messages),
            "tool_calls": list(self._tool_calls),
            "model_calls": list(self._model_calls),
            "metadata": {
                "skill_name": self.skill_name,
                "total_tool_calls": len(self._tool_calls),
                "total_duration_ms": total_duration_ms,
            },
        }

    def to_s3_key(self) -> str:
        """Generate the S3 key for this session record.

        Format: sessions/{tenant_id}/{YYYY/MM/DD}/{session_id}.json

        Returns:
            S3 key string.
        """
        if self._start_time is not None:
            dt = datetime.fromtimestamp(self._start_time, tz=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        date_path = dt.strftime("%Y/%m/%d")
        return f"sessions/{self.tenant_id}/{date_path}/{self.session_id}.json"

    def to_s3_payload(self) -> str:
        """Serialize the session record to JSON for S3 storage.

        Returns:
            JSON string of the session record.
        """
        return json.dumps(self.get_session_record(), default=str)

    def clear(self) -> None:
        """Reset all recorded state."""
        self._start_time = None
        self._end_time = None
        self._messages.clear()
        self._tool_calls.clear()
        self._model_calls.clear()
        self._pending_tool_calls.clear()
