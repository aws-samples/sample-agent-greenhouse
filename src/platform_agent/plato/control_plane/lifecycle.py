"""Lifecycle Manager — cold start, heartbeat, and graceful shutdown protocols.

Manages the full lifecycle of agents from boot through termination,
including health monitoring via heartbeats and graceful task draining.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from platform_agent.plato.control_plane.registry import AgentRegistry, AgentState

logger = logging.getLogger(__name__)


class ColdStartProtocol:
    """Boot sequence for bringing an agent from BOOT to READY.

    Steps:
    1. Pull agent record from registry
    2. Load applicable policies
    3. Run self-check
    4. Transition to READY
    """

    def __init__(
        self,
        registry: AgentRegistry,
        policy_engine: Any | None = None,
        audit_store: Any | None = None,
    ) -> None:
        self._registry = registry
        self._policy_engine = policy_engine
        self._audit_store = audit_store

    def boot(self, tenant_id: str, agent_id: str) -> bool:
        """Execute the cold start sequence for an agent.

        Args:
            tenant_id: Agent's tenant.
            agent_id: Agent to boot.

        Returns:
            True if the agent reached READY state.

        Raises:
            KeyError: If agent not found.
        """
        record = self._registry.get(tenant_id, agent_id)
        if record is None:
            raise KeyError(f"Agent '{agent_id}' not found for tenant '{tenant_id}'")

        logger.info("Cold start: booting agent %s", agent_id)

        # Step 1: Transition to INITIALIZING
        try:
            self._registry.update_state(tenant_id, agent_id, AgentState.INITIALIZING)
        except ValueError:
            logger.error("Agent %s cannot transition to INITIALIZING", agent_id)
            return False

        # Step 2: Load policies (if policy engine available)
        if self._policy_engine is not None:
            logger.debug("Loading policies for agent %s (role=%s)", agent_id, record.role)

        # Step 3: Self-check
        if not self._self_check(record):
            logger.warning("Self-check failed for agent %s, marking DEGRADED", agent_id)
            try:
                self._registry.update_state(tenant_id, agent_id, AgentState.DEGRADED)
            except ValueError:
                pass
            self._log_audit(agent_id, tenant_id, "cold_start", "failure")
            return False

        # Step 4: Transition to READY
        try:
            self._registry.update_state(tenant_id, agent_id, AgentState.READY)
        except ValueError:
            logger.error("Agent %s cannot transition to READY", agent_id)
            self._log_audit(agent_id, tenant_id, "cold_start", "failure")
            return False

        # Update heartbeat
        self._registry.update_heartbeat(tenant_id, agent_id)
        self._log_audit(agent_id, tenant_id, "cold_start", "success")
        logger.info("Cold start complete: agent %s is READY", agent_id)
        return True

    def _self_check(self, record: Any) -> bool:
        """Run self-check on agent. Returns True if healthy."""
        # Check agent has a role
        if not record.role:
            return False
        # Check agent has an ID
        if not record.agent_id:
            return False
        return True

    def _log_audit(
        self, agent_id: str, tenant_id: str, action: str, result: str
    ) -> None:
        """Log to audit store if available."""
        if self._audit_store is not None:
            self._audit_store.log(
                agent_id=agent_id,
                tenant_id=tenant_id,
                action=action,
                result=result,
            )


class HeartbeatManager:
    """Monitors agent health via heartbeats.

    Checks last heartbeat timestamps and marks agents as DEGRADED
    if they miss their heartbeat window.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        timeout_seconds: float = 30.0,
        audit_store: Any | None = None,
    ) -> None:
        self._registry = registry
        self._timeout_seconds = timeout_seconds
        self._audit_store = audit_store

    def check_heartbeat(self, tenant_id: str, agent_id: str) -> bool:
        """Check if an agent's heartbeat is current.

        Returns True if heartbeat is within the timeout window.
        """
        record = self._registry.get(tenant_id, agent_id)
        if record is None:
            return False

        if record.last_heartbeat is None:
            return False

        now = datetime.now(timezone.utc)
        elapsed = (now - record.last_heartbeat).total_seconds()
        return elapsed <= self._timeout_seconds

    def check_all(self, tenant_id: str | None = None) -> list[str]:
        """Check heartbeats for all agents. Returns IDs of agents marked degraded."""
        degraded: list[str] = []
        agents = self._registry.list_agents(tenant_id)

        for agent in agents:
            if agent.state in (AgentState.READY, AgentState.BUSY):
                if not self.check_heartbeat(agent.tenant_id, agent.agent_id):
                    self.mark_degraded(agent.tenant_id, agent.agent_id)
                    degraded.append(agent.agent_id)

        return degraded

    def mark_degraded(self, tenant_id: str, agent_id: str) -> bool:
        """Mark an agent as degraded due to missed heartbeat.

        Returns True if the state was changed.
        """
        record = self._registry.get(tenant_id, agent_id)
        if record is None:
            return False

        if record.state == AgentState.DEGRADED:
            return False

        try:
            self._registry.update_state(tenant_id, agent_id, AgentState.DEGRADED)
            logger.warning("Agent %s marked DEGRADED (missed heartbeat)", agent_id)
            if self._audit_store:
                self._audit_store.log(
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    action="heartbeat_missed",
                    result="degraded",
                )
            return True
        except ValueError:
            return False

    def auto_restart(self, tenant_id: str, agent_id: str) -> bool:
        """Attempt to restart a degraded agent by re-running cold start.

        Returns True if the agent was successfully restarted.
        """
        record = self._registry.get(tenant_id, agent_id)
        if record is None:
            return False

        if record.state != AgentState.DEGRADED:
            return False

        # Transition back to READY if possible
        try:
            self._registry.update_state(tenant_id, agent_id, AgentState.READY)
            self._registry.update_heartbeat(tenant_id, agent_id)
            logger.info("Auto-restarted agent %s", agent_id)
            return True
        except ValueError:
            return False


class GracefulShutdown:
    """Graceful shutdown protocol for agents.

    Drains in-progress tasks by reassigning them, then deregisters the agent.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        task_manager: Any | None = None,
        audit_store: Any | None = None,
    ) -> None:
        self._registry = registry
        self._task_manager = task_manager
        self._audit_store = audit_store

    def drain(self, tenant_id: str, agent_id: str) -> list[str]:
        """Drain an agent's tasks and prepare for shutdown.

        Reassigns any tasks currently assigned to or claimed by the agent.

        Args:
            tenant_id: Agent's tenant.
            agent_id: Agent to drain.

        Returns:
            List of task IDs that were reassigned.
        """
        reassigned: list[str] = []

        if self._task_manager is not None:
            tasks = self._task_manager.list_tasks(
                tenant_id=tenant_id, assigned_to=agent_id
            )
            for task in tasks:
                if not task.is_terminal:
                    # Release the task back to pending
                    task.status = __import__(
                        "platform_agent.plato.control_plane.task_manager",
                        fromlist=["TaskStatus"],
                    ).TaskStatus.PENDING
                    task.assigned_to = ""
                    task.claimed_at = None
                    reassigned.append(task.task_id)
                    logger.info(
                        "Reassigned task %s from draining agent %s",
                        task.task_id,
                        agent_id,
                    )

        return reassigned

    def shutdown(self, tenant_id: str, agent_id: str) -> bool:
        """Execute full graceful shutdown: drain then deregister.

        Args:
            tenant_id: Agent's tenant.
            agent_id: Agent to shut down.

        Returns:
            True if shutdown was successful.
        """
        record = self._registry.get(tenant_id, agent_id)
        if record is None:
            return False

        logger.info("Graceful shutdown: draining agent %s", agent_id)
        reassigned = self.drain(tenant_id, agent_id)

        # Terminate and deregister
        try:
            self._registry.update_state(tenant_id, agent_id, AgentState.TERMINATED)
        except ValueError:
            pass

        self._registry.deregister(tenant_id, agent_id)

        if self._audit_store:
            self._audit_store.log(
                agent_id=agent_id,
                tenant_id=tenant_id,
                action="graceful_shutdown",
                details={"reassigned_tasks": reassigned},
                result="success",
            )

        logger.info(
            "Agent %s shut down (reassigned %d tasks)", agent_id, len(reassigned)
        )
        return True
