"""Task System — creation, assignment, and lifecycle management for agent tasks.

Provides a task queue with capability-based dispatch, atomic claiming,
lease management, and retry logic. Supports multi-tenant isolation.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from platform_agent.plato.control_plane.registry import AgentRegistry

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Task origination types."""

    DIRECT = "direct"
    BROADCAST = "broadcast"
    AGENT_GENERATED = "agent_generated"
    SCHEDULED = "scheduled"


class TaskStatus(Enum):
    """Task lifecycle statuses."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class Task:
    """A unit of work to be performed by an agent.

    Supports hierarchical tasks via parent_task_id, priority ordering,
    capability-based assignment, and deadline tracking.
    """

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    type: TaskType = TaskType.DIRECT
    source_agent: str = ""
    intent: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    required_capabilities: list[str] = field(default_factory=list)
    priority: int = 0
    assigned_to: str = ""
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    parent_task_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deadline: datetime | None = None
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        """Whether the task is in a terminal state."""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    @property
    def is_overdue(self) -> bool:
        """Whether the task has passed its deadline."""
        if self.deadline is None:
            return False
        return datetime.now(timezone.utc) > self.deadline

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "type": self.type.value,
            "source_agent": self.source_agent,
            "intent": self.intent,
            "payload": self.payload,
            "required_capabilities": self.required_capabilities,
            "priority": self.priority,
            "assigned_to": self.assigned_to,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "parent_task_id": self.parent_task_id,
            "created_at": self.created_at.isoformat(),
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "claimed_at": self.claimed_at.isoformat() if self.claimed_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
        }


class TaskManager:
    """Manages the lifecycle of tasks.

    Provides creation, claiming (with atomic check), assignment,
    status updates, and lease management.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def create_task(
        self,
        tenant_id: str,
        intent: str,
        task_type: TaskType = TaskType.DIRECT,
        source_agent: str = "",
        payload: dict[str, Any] | None = None,
        required_capabilities: list[str] | None = None,
        priority: int = 0,
        max_retries: int = 3,
        parent_task_id: str = "",
        deadline: datetime | None = None,
        task_id: str | None = None,
    ) -> Task:
        """Create a new task.

        Args:
            tenant_id: Tenant this task belongs to.
            intent: What the task should accomplish.
            task_type: How the task originated.
            source_agent: Agent that created the task.
            payload: Additional task data.
            required_capabilities: Capabilities needed to handle this task.
            priority: Higher = more important.
            max_retries: Maximum retry attempts.
            parent_task_id: Parent task for hierarchical tasks.
            deadline: When the task must be completed by.
            task_id: Optional explicit ID.

        Returns:
            The created Task.
        """
        task = Task(
            task_id=task_id or str(uuid.uuid4()),
            tenant_id=tenant_id,
            type=task_type,
            source_agent=source_agent,
            intent=intent,
            payload=payload or {},
            required_capabilities=required_capabilities or [],
            priority=priority,
            max_retries=max_retries,
            parent_task_id=parent_task_id,
            deadline=deadline,
        )
        self._tasks[task.task_id] = task
        logger.info("Created task %s: %s (tenant=%s)", task.task_id, intent, tenant_id)
        return task

    def claim_task(self, task_id: str, agent_id: str) -> Task:
        """Atomically claim a task for an agent.

        The task must be in PENDING or ASSIGNED status to be claimed.

        Args:
            task_id: Task to claim.
            agent_id: Agent claiming the task.

        Raises:
            KeyError: If task not found.
            ValueError: If task cannot be claimed (wrong status or already claimed).
        """
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")

        if task.status not in (TaskStatus.PENDING, TaskStatus.ASSIGNED):
            raise ValueError(
                f"Task '{task_id}' cannot be claimed: status is {task.status.value}"
            )

        if task.status == TaskStatus.ASSIGNED and task.assigned_to != agent_id:
            raise ValueError(
                f"Task '{task_id}' is assigned to '{task.assigned_to}', "
                f"not '{agent_id}'"
            )

        task.status = TaskStatus.CLAIMED
        task.assigned_to = agent_id
        task.claimed_at = datetime.now(timezone.utc)
        logger.info("Task %s claimed by %s", task_id, agent_id)
        return task

    def assign_task(self, task_id: str, agent_id: str) -> Task:
        """Assign a task to a specific agent without claiming.

        Args:
            task_id: Task to assign.
            agent_id: Target agent.

        Raises:
            KeyError: If task not found.
            ValueError: If task is not in PENDING status.
        """
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")

        if task.status != TaskStatus.PENDING:
            raise ValueError(
                f"Task '{task_id}' cannot be assigned: status is {task.status.value}"
            )

        task.status = TaskStatus.ASSIGNED
        task.assigned_to = agent_id
        logger.info("Task %s assigned to %s", task_id, agent_id)
        return task

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: dict[str, Any] | None = None,
    ) -> Task:
        """Update a task's status.

        Args:
            task_id: Task to update.
            status: New status.
            result: Optional result data (for completed/failed).

        Raises:
            KeyError: If task not found.
        """
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")

        task.status = status
        if result is not None:
            task.result = result
        if status == TaskStatus.COMPLETED:
            task.completed_at = datetime.now(timezone.utc)
        logger.info("Task %s → %s", task_id, status.value)
        return task

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        tenant_id: str | None = None,
        status: TaskStatus | None = None,
        assigned_to: str | None = None,
    ) -> list[Task]:
        """List tasks with optional filters.

        Results are ordered by priority (descending), then creation time.
        """
        tasks = list(self._tasks.values())
        if tenant_id is not None:
            tasks = [t for t in tasks if t.tenant_id == tenant_id]
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        if assigned_to is not None:
            tasks = [t for t in tasks if t.assigned_to == assigned_to]
        tasks.sort(key=lambda t: (-t.priority, t.created_at))
        return tasks

    def release_expired_claims(self, lease_minutes: int = 5) -> list[Task]:
        """Release tasks whose claim lease has expired.

        Tasks claimed longer than lease_minutes ago are reset to PENDING
        and unassigned.

        Returns:
            List of released tasks.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=lease_minutes)
        released: list[Task] = []

        for task in self._tasks.values():
            if (
                task.status == TaskStatus.CLAIMED
                and task.claimed_at is not None
                and task.claimed_at < cutoff
            ):
                task.status = TaskStatus.PENDING
                task.assigned_to = ""
                task.claimed_at = None
                released.append(task)
                logger.info("Released expired claim on task %s", task.task_id)

        return released

    def retry_or_fail(self, task_id: str, error: str = "") -> Task:
        """Retry a task or mark it as failed if retries are exhausted.

        Args:
            task_id: Task to retry.
            error: Error description.

        Raises:
            KeyError: If task not found.

        Returns:
            The updated task (RETRYING or FAILED).
        """
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")

        task.retry_count += 1
        if task.retry_count > task.max_retries:
            task.status = TaskStatus.FAILED
            task.result = {"error": error, "retries_exhausted": True}
            task.completed_at = datetime.now(timezone.utc)
            logger.warning("Task %s failed after %d retries", task_id, task.max_retries)
        else:
            task.status = TaskStatus.PENDING
            task.assigned_to = ""
            task.claimed_at = None
            task.result = {"last_error": error}
            logger.info(
                "Task %s retrying (%d/%d)", task_id, task.retry_count, task.max_retries
            )

        return task

    @property
    def task_count(self) -> int:
        """Total number of tasks."""
        return len(self._tasks)


class TaskDispatcher:
    """Dispatches tasks to agents based on capabilities.

    Uses the AgentRegistry to find suitable agents and assigns
    tasks to the best match.
    """

    def __init__(
        self, task_manager: TaskManager, registry: AgentRegistry
    ) -> None:
        self._task_manager = task_manager
        self._registry = registry

    def dispatch(self, task: Task) -> Task:
        """Dispatch a task to an appropriate agent.

        Strategy:
        1. Find agents with required capabilities in READY state.
        2. Score by cumulative capability confidence.
        3. Assign to best match.
        4. If no match, leave as PENDING (for broadcast pickup).

        Args:
            task: Task to dispatch.

        Returns:
            The task (possibly assigned to an agent).
        """
        from platform_agent.plato.control_plane.registry import AgentState

        if not task.required_capabilities:
            # No capability requirements — leave for broadcast
            return task

        # Find ready agents with all required capabilities
        candidates: list[tuple[str, float]] = []
        ready_agents = self._registry.find_by_state(
            AgentState.READY, tenant_id=task.tenant_id
        )

        for agent in ready_agents:
            score = 0.0
            has_all = True
            for cap_name in task.required_capabilities:
                if agent.has_capability(cap_name):
                    score += agent.capability_confidence(cap_name)
                else:
                    has_all = False
                    break
            if has_all:
                candidates.append((agent.agent_id, score))

        if not candidates:
            logger.info("No suitable agent found for task %s", task.task_id)
            return task

        # Sort by score descending, assign to best
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_agent_id = candidates[0][0]
        self._task_manager.assign_task(task.task_id, best_agent_id)
        logger.info(
            "Dispatched task %s to agent %s (score=%.2f)",
            task.task_id,
            best_agent_id,
            candidates[0][1],
        )
        return task
