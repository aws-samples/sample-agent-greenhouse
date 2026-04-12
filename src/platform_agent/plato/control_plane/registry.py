"""Agent Registry — in-memory registry with DynamoDB-compatible schema.

Manages agent records including registration, state transitions, heartbeats,
and capability-based discovery. Supports multi-tenant isolation.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent lifecycle states."""

    BOOT = "boot"
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    DEGRADED = "degraded"
    TERMINATED = "terminated"


# Valid state transitions
VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.BOOT: {AgentState.INITIALIZING, AgentState.TERMINATED},
    AgentState.INITIALIZING: {AgentState.READY, AgentState.DEGRADED, AgentState.TERMINATED},
    AgentState.READY: {AgentState.BUSY, AgentState.DEGRADED, AgentState.TERMINATED},
    AgentState.BUSY: {AgentState.READY, AgentState.DEGRADED, AgentState.TERMINATED},
    AgentState.DEGRADED: {AgentState.READY, AgentState.TERMINATED},
    AgentState.TERMINATED: set(),
}


@dataclass
class Capability:
    """An agent capability with confidence score."""

    name: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {"name": self.name, "confidence": self.confidence}


@dataclass
class AgentRecord:
    """Record of a registered agent.

    Schema is compatible with DynamoDB for future persistence.
    Primary key: (tenant_id, agent_id).
    """

    agent_id: str
    tenant_id: str
    role: str
    capabilities: list[Capability] = field(default_factory=list)
    state: AgentState = AgentState.BOOT
    tools: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: datetime | None = None
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def has_capability(self, name: str, min_confidence: float = 0.0) -> bool:
        """Check if agent has a capability at or above a confidence threshold."""
        return any(
            c.name == name and c.confidence >= min_confidence
            for c in self.capabilities
        )

    def capability_confidence(self, name: str) -> float:
        """Get confidence for a capability, or 0.0 if not present."""
        for c in self.capabilities:
            if c.name == name:
                return c.confidence
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to DynamoDB-compatible dictionary."""
        return {
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "role": self.role,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "state": self.state.value,
            "tools": self.tools,
            "config": self.config,
            "last_heartbeat": (
                self.last_heartbeat.isoformat() if self.last_heartbeat else None
            ),
            "registered_at": self.registered_at.isoformat(),
        }


class AgentRegistry:
    """In-memory agent registry with multi-tenant support.

    Stores agent records keyed by (tenant_id, agent_id). Provides
    lookup by capability, state, and tenant filtering.
    """

    def __init__(self) -> None:
        self._agents: dict[tuple[str, str], AgentRecord] = {}

    def register(
        self,
        tenant_id: str,
        role: str,
        capabilities: list[Capability] | None = None,
        tools: list[str] | None = None,
        config: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> AgentRecord:
        """Register a new agent and return its record.

        Args:
            tenant_id: Tenant this agent belongs to.
            role: Agent role (e.g., "design-advisor", "monitor").
            capabilities: List of capabilities with confidence scores.
            tools: Tools the agent has access to.
            config: Additional configuration.
            agent_id: Optional explicit ID; auto-generated if not provided.

        Raises:
            ValueError: If an agent with the same ID already exists for this tenant.
        """
        if agent_id is None:
            agent_id = str(uuid.uuid4())

        key = (tenant_id, agent_id)
        if key in self._agents:
            raise ValueError(
                f"Agent '{agent_id}' already registered for tenant '{tenant_id}'"
            )

        record = AgentRecord(
            agent_id=agent_id,
            tenant_id=tenant_id,
            role=role,
            capabilities=capabilities or [],
            tools=tools or [],
            config=config or {},
        )
        self._agents[key] = record
        logger.info("Registered agent %s for tenant %s (role=%s)", agent_id, tenant_id, role)
        return record

    def deregister(self, tenant_id: str, agent_id: str) -> bool:
        """Remove an agent from the registry.

        Returns True if the agent was found and removed.
        """
        key = (tenant_id, agent_id)
        if key in self._agents:
            self._agents[key].state = AgentState.TERMINATED
            del self._agents[key]
            logger.info("Deregistered agent %s from tenant %s", agent_id, tenant_id)
            return True
        return False

    def get(self, tenant_id: str, agent_id: str) -> AgentRecord | None:
        """Get an agent record by tenant and agent ID."""
        return self._agents.get((tenant_id, agent_id))

    def list_agents(self, tenant_id: str | None = None) -> list[AgentRecord]:
        """List agents, optionally filtered by tenant.

        Args:
            tenant_id: If provided, only return agents for this tenant.
        """
        if tenant_id is not None:
            return [r for r in self._agents.values() if r.tenant_id == tenant_id]
        return list(self._agents.values())

    def update_state(
        self, tenant_id: str, agent_id: str, new_state: AgentState
    ) -> AgentRecord:
        """Transition an agent to a new state.

        Args:
            tenant_id: Tenant ID.
            agent_id: Agent ID.
            new_state: Target state.

        Raises:
            KeyError: If agent not found.
            ValueError: If state transition is invalid.
        """
        record = self.get(tenant_id, agent_id)
        if record is None:
            raise KeyError(f"Agent '{agent_id}' not found for tenant '{tenant_id}'")

        valid = VALID_TRANSITIONS.get(record.state, set())
        if new_state not in valid:
            raise ValueError(
                f"Invalid transition: {record.state.value} → {new_state.value} "
                f"(valid: {[s.value for s in valid]})"
            )
        old_state = record.state
        record.state = new_state
        logger.info(
            "Agent %s state: %s → %s", agent_id, old_state.value, new_state.value
        )
        return record

    def update_heartbeat(
        self, tenant_id: str, agent_id: str, timestamp: datetime | None = None
    ) -> AgentRecord:
        """Update an agent's heartbeat timestamp.

        Raises:
            KeyError: If agent not found.
        """
        record = self.get(tenant_id, agent_id)
        if record is None:
            raise KeyError(f"Agent '{agent_id}' not found for tenant '{tenant_id}'")

        record.last_heartbeat = timestamp or datetime.now(timezone.utc)
        return record

    def find_by_capability(
        self,
        capability: str,
        tenant_id: str | None = None,
        min_confidence: float = 0.0,
    ) -> list[AgentRecord]:
        """Find agents that have a given capability.

        Args:
            capability: Capability name to search for.
            tenant_id: Optional tenant filter.
            min_confidence: Minimum confidence threshold.
        """
        agents = self.list_agents(tenant_id)
        return [
            a for a in agents
            if a.has_capability(capability, min_confidence)
        ]

    def find_by_state(
        self, state: AgentState, tenant_id: str | None = None
    ) -> list[AgentRecord]:
        """Find agents in a given state."""
        agents = self.list_agents(tenant_id)
        return [a for a in agents if a.state == state]

    @property
    def agent_count(self) -> int:
        """Total number of registered agents."""
        return len(self._agents)
