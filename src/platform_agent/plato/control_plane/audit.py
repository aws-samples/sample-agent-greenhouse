"""Audit Store — structured logging and compliance reporting for agent actions.

Records all significant agent actions with tenant isolation.
Supports querying, violation filtering, and report generation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AuditAction(Enum):
    """Standard audit action types."""

    AGENT_REGISTERED = "agent_registered"
    AGENT_DEREGISTERED = "agent_deregistered"
    STATE_CHANGE = "state_change"
    TASK_CREATED = "task_created"
    TASK_CLAIMED = "task_claimed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    MESSAGE_SENT = "message_sent"
    MESSAGE_FILTERED = "message_filtered"
    POLICY_VIOLATION = "policy_violation"
    CONTENT_FILTERED = "content_filtered"
    CIRCUIT_BROKEN = "circuit_broken"
    HEARTBEAT_MISSED = "heartbeat_missed"
    COLD_START = "cold_start"
    GRACEFUL_SHUTDOWN = "graceful_shutdown"


class AuditResult(Enum):
    """Result of an audited action."""

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    FILTERED = "filtered"


@dataclass
class AuditEntry:
    """A single audit log entry.

    Records who did what, when, and the outcome.
    """

    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: str = ""
    tenant_id: str = ""
    action: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    result: str = "success"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "action": self.action,
            "details": self.details,
            "result": self.result,
        }


class AuditStore:
    """In-memory audit log store with query and reporting capabilities.

    Stores audit entries and provides filtering by tenant, agent, action,
    time range, and result.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def log(
        self,
        agent_id: str = "",
        tenant_id: str = "",
        action: str = "",
        details: dict[str, Any] | None = None,
        result: str = "success",
        timestamp: datetime | None = None,
    ) -> AuditEntry:
        """Record an audit entry.

        Args:
            agent_id: Agent that performed the action.
            tenant_id: Tenant context.
            action: What happened.
            details: Additional structured data.
            result: Outcome (success, failure, denied, filtered).
            timestamp: When it happened; defaults to now.

        Returns:
            The created AuditEntry.
        """
        entry = AuditEntry(
            agent_id=agent_id,
            tenant_id=tenant_id,
            action=action,
            details=details or {},
            result=result,
            timestamp=timestamp or datetime.now(timezone.utc),
        )
        self._entries.append(entry)
        return entry

    def query(
        self,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        action: str | None = None,
        result: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries with optional filters.

        Args:
            tenant_id: Filter by tenant.
            agent_id: Filter by agent.
            action: Filter by action type.
            result: Filter by result.
            since: Only entries at or after this time.
            until: Only entries at or before this time.
            limit: Maximum number of entries to return.
        """
        results: list[AuditEntry] = []
        for entry in reversed(self._entries):
            if tenant_id is not None and entry.tenant_id != tenant_id:
                continue
            if agent_id is not None and entry.agent_id != agent_id:
                continue
            if action is not None and entry.action != action:
                continue
            if result is not None and entry.result != result:
                continue
            if since is not None and entry.timestamp < since:
                continue
            if until is not None and entry.timestamp > until:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def get_violations(
        self, tenant_id: str | None = None, limit: int = 100
    ) -> list[AuditEntry]:
        """Get policy violation entries.

        Returns entries with action=policy_violation or result=denied/filtered.
        """
        violations: list[AuditEntry] = []
        for entry in reversed(self._entries):
            if tenant_id is not None and entry.tenant_id != tenant_id:
                continue
            if (
                entry.action == AuditAction.POLICY_VIOLATION.value
                or entry.result in (AuditResult.DENIED.value, AuditResult.FILTERED.value)
            ):
                violations.append(entry)
                if len(violations) >= limit:
                    break
        return violations

    def generate_report(
        self, tenant_id: str | None = None
    ) -> dict[str, Any]:
        """Generate a summary report of audit activity.

        Returns:
            Dictionary with counts by action, result, and top agents.
        """
        entries = self.query(tenant_id=tenant_id, limit=10000)
        action_counts: dict[str, int] = {}
        result_counts: dict[str, int] = {}
        agent_counts: dict[str, int] = {}

        for entry in entries:
            action_counts[entry.action] = action_counts.get(entry.action, 0) + 1
            result_counts[entry.result] = result_counts.get(entry.result, 0) + 1
            if entry.agent_id:
                agent_counts[entry.agent_id] = agent_counts.get(entry.agent_id, 0) + 1

        violations = self.get_violations(tenant_id=tenant_id)

        return {
            "total_entries": len(entries),
            "action_counts": action_counts,
            "result_counts": result_counts,
            "top_agents": dict(
                sorted(agent_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "violation_count": len(violations),
        }

    @property
    def entry_count(self) -> int:
        """Total number of audit entries."""
        return len(self._entries)

    def clear(self) -> int:
        """Clear all entries. Returns count of entries cleared."""
        count = len(self._entries)
        self._entries.clear()
        return count
