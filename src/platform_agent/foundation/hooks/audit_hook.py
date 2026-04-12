"""AuditHook — logs all tool calls for observability.

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
audit_logger = logging.getLogger("plato.audit")

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import BeforeToolCallEvent, AfterToolCallEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



class AuditHook(HookBase):
    """Hook that records all tool calls for audit and observability.

    Logs tool invocations with timestamps, inputs, and outputs.
    The audit log can be retrieved for debugging or compliance.

    Implements strands.hooks.HookProvider for native integration.
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        skill_name: str | None = None,
    ) -> None:
        self.tool_calls: list[dict] = []
        self.session_id = session_id
        self.skill_name = skill_name

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call)
            registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    def on_before_tool_call(self, event) -> None:
        """Record a tool call start.

        Args:
            event: BeforeToolCallEvent with tool_use dict containing
                   toolUseId, name, and input fields.
        """
        tool_use = getattr(event, "tool_use", {})
        tool_name = tool_use.get("name", "unknown") if isinstance(tool_use, dict) else "unknown"
        tool_input = tool_use.get("input", {}) if isinstance(tool_use, dict) else {}

        entry: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "status": "started",
            "timestamp": time.time(),
        }
        if self.session_id is not None:
            entry["session_id"] = self.session_id
        if self.skill_name is not None:
            entry["skill_name"] = self.skill_name
        self.tool_calls.append(entry)
        logger.debug("Tool call started: %s", entry["tool_name"])

    def on_after_tool_call(self, event) -> None:
        """Record a tool call completion.

        Args:
            event: AfterToolCallEvent with tool result.
        """
        tool_use = getattr(event, "tool_use", {})
        tool_name = tool_use.get("name", "unknown") if isinstance(tool_use, dict) else "unknown"

        entry: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_output_preview": str(getattr(event, "tool_result", ""))[:200],
            "status": "completed",
            "timestamp": time.time(),
        }
        if self.session_id is not None:
            entry["session_id"] = self.session_id
        if self.skill_name is not None:
            entry["skill_name"] = self.skill_name
        self.tool_calls.append(entry)
        logger.debug("Tool call completed: %s", entry["tool_name"])
        self.emit_structured_log(entry)

    def get_audit_log(self) -> list[dict]:
        """Get the full audit log."""
        return list(self.tool_calls)

    def emit_structured_log(self, entry: dict[str, Any]) -> None:
        """Write an audit entry as structured JSON to the plato.audit logger."""
        log_entry = {
            "event_type": "tool_call",
            "timestamp": datetime.fromtimestamp(
                entry.get("timestamp", time.time()), tz=timezone.utc
            ).isoformat(),
            **entry,
        }
        audit_logger.info(json.dumps(log_entry))

    def to_cloudwatch_format(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Format an audit entry for CloudWatch Logs structured queries.

        Returns:
            Dictionary with fields optimized for CloudWatch Log Insights queries.
        """
        return {
            "event_type": "tool_call",
            "timestamp": datetime.fromtimestamp(
                entry.get("timestamp", time.time()), tz=timezone.utc
            ).isoformat(),
            "session_id": entry.get("session_id", self.session_id),
            "skill_name": entry.get("skill_name", self.skill_name),
            "tool_name": entry.get("tool_name", "unknown"),
            "status": entry.get("status", "unknown"),
            "tool_output_preview": entry.get("tool_output_preview"),
        }

    def to_dynamodb_item(
        self,
        entry: dict[str, Any],
        *,
        tenant_id: str = "default",
    ) -> dict[str, dict[str, str]]:
        """Format an audit entry into the DynamoDB schema format.

        This is a formatting helper only — the actual DDB write is done by
        the entrypoint/Lambda, NOT the hook.

        Args:
            entry: An audit log entry dict (from tool_calls list).
            tenant_id: Tenant identifier for multi-tenancy isolation.

        Returns:
            DynamoDB-formatted item dict with PK, SK, and attributes.
        """
        session_id = entry.get("session_id", self.session_id or "unknown")
        event_type = "tool_call"
        ts = datetime.fromtimestamp(
            entry.get("timestamp", time.time()), tz=timezone.utc
        ).isoformat()

        # TTL: 90 days from now
        expire_at = int(entry.get("timestamp", time.time())) + (90 * 24 * 60 * 60)

        return {
            "PK": {"S": f"TENANT#{tenant_id}#SESSION#{session_id}"},
            "SK": {"S": f"TS#{ts}#EVENT#{event_type}"},
            "session_id": {"S": session_id},
            "tenant_id": {"S": tenant_id},
            "event_type": {"S": event_type},
            "tool_name": {"S": entry.get("tool_name", "unknown")},
            "skill_name": {"S": entry.get("skill_name", self.skill_name or "unknown")},
            "timestamp": {"S": ts},
            "payload": {"M": {
                "tool_input": {"S": json.dumps(entry.get("tool_input", {}))},
                "tool_output_preview": {"S": entry.get("tool_output_preview", "")},
                "status": {"S": entry.get("status", "unknown")},
            }},
            "quality_labels": {"M": {}},
            "expire_at": {"N": str(expire_at)},
        }

    def clear(self) -> None:
        """Clear the audit log."""
        self.tool_calls.clear()
