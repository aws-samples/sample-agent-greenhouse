"""Tests for Task Manager and Task Dispatcher."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from platform_agent.plato.control_plane.task_manager import (
    Task,
    TaskDispatcher,
    TaskManager,
    TaskStatus,
    TaskType,
)
from platform_agent.plato.control_plane.registry import (
    AgentRegistry,
    AgentState,
    Capability,
)


# ---------------------------------------------------------------------------
# Task dataclass tests
# ---------------------------------------------------------------------------


class TestTask:
    def test_create_defaults(self):
        task = Task()
        assert task.task_id is not None
        assert task.status == TaskStatus.PENDING
        assert task.type == TaskType.DIRECT
        assert task.retry_count == 0
        assert task.max_retries == 3
        assert task.priority == 0

    def test_create_with_values(self):
        task = Task(
            tenant_id="t1",
            type=TaskType.BROADCAST,
            intent="review code",
            priority=10,
        )
        assert task.tenant_id == "t1"
        assert task.type == TaskType.BROADCAST
        assert task.intent == "review code"
        assert task.priority == 10

    def test_is_terminal_completed(self):
        task = Task(status=TaskStatus.COMPLETED)
        assert task.is_terminal

    def test_is_terminal_failed(self):
        task = Task(status=TaskStatus.FAILED)
        assert task.is_terminal

    def test_is_terminal_cancelled(self):
        task = Task(status=TaskStatus.CANCELLED)
        assert task.is_terminal

    def test_is_not_terminal_pending(self):
        task = Task(status=TaskStatus.PENDING)
        assert not task.is_terminal

    def test_is_not_terminal_claimed(self):
        task = Task(status=TaskStatus.CLAIMED)
        assert not task.is_terminal

    def test_is_overdue(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        task = Task(deadline=past)
        assert task.is_overdue

    def test_is_not_overdue(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        task = Task(deadline=future)
        assert not task.is_overdue

    def test_is_not_overdue_no_deadline(self):
        task = Task()
        assert not task.is_overdue

    def test_to_dict(self):
        task = Task(
            task_id="t1",
            tenant_id="tenant-1",
            intent="test",
            status=TaskStatus.PENDING,
        )
        d = task.to_dict()
        assert d["task_id"] == "t1"
        assert d["tenant_id"] == "tenant-1"
        assert d["status"] == "pending"
        assert d["type"] == "direct"

    def test_to_dict_with_dates(self):
        now = datetime.now(timezone.utc)
        task = Task(deadline=now, claimed_at=now, completed_at=now)
        d = task.to_dict()
        assert d["deadline"] == now.isoformat()
        assert d["claimed_at"] == now.isoformat()
        assert d["completed_at"] == now.isoformat()

    def test_to_dict_no_dates(self):
        task = Task()
        d = task.to_dict()
        assert d["deadline"] is None
        assert d["claimed_at"] is None
        assert d["completed_at"] is None


class TestTaskType:
    def test_all_types(self):
        values = [t.value for t in TaskType]
        assert "direct" in values
        assert "broadcast" in values
        assert "agent_generated" in values
        assert "scheduled" in values


class TestTaskStatus:
    def test_all_statuses(self):
        values = [s.value for s in TaskStatus]
        assert "pending" in values
        assert "assigned" in values
        assert "claimed" in values
        assert "in_progress" in values
        assert "completed" in values
        assert "failed" in values
        assert "cancelled" in values
        assert "retrying" in values


# ---------------------------------------------------------------------------
# TaskManager tests
# ---------------------------------------------------------------------------


class TestTaskManagerCreate:
    def test_create_task(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="review code")
        assert task.tenant_id == "t1"
        assert task.intent == "review code"
        assert task.status == TaskStatus.PENDING

    def test_create_with_all_params(self):
        tm = TaskManager()
        deadline = datetime.now(timezone.utc) + timedelta(hours=1)
        task = tm.create_task(
            tenant_id="t1",
            intent="deploy",
            task_type=TaskType.SCHEDULED,
            source_agent="scheduler",
            payload={"target": "prod"},
            required_capabilities=["deploy"],
            priority=10,
            max_retries=5,
            parent_task_id="parent-1",
            deadline=deadline,
        )
        assert task.type == TaskType.SCHEDULED
        assert task.source_agent == "scheduler"
        assert task.payload == {"target": "prod"}
        assert task.required_capabilities == ["deploy"]
        assert task.priority == 10
        assert task.max_retries == 5
        assert task.parent_task_id == "parent-1"
        assert task.deadline == deadline

    def test_create_with_explicit_id(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test", task_id="my-task")
        assert task.task_id == "my-task"

    def test_create_increments_count(self):
        tm = TaskManager()
        assert tm.task_count == 0
        tm.create_task(tenant_id="t1", intent="a")
        assert tm.task_count == 1
        tm.create_task(tenant_id="t1", intent="b")
        assert tm.task_count == 2


class TestTaskManagerClaim:
    def test_claim_pending(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        claimed = tm.claim_task(task.task_id, "agent-1")
        assert claimed.status == TaskStatus.CLAIMED
        assert claimed.assigned_to == "agent-1"
        assert claimed.claimed_at is not None

    def test_claim_assigned_correct_agent(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.assign_task(task.task_id, "agent-1")
        claimed = tm.claim_task(task.task_id, "agent-1")
        assert claimed.status == TaskStatus.CLAIMED

    def test_claim_assigned_wrong_agent(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.assign_task(task.task_id, "agent-1")
        with pytest.raises(ValueError, match="assigned to"):
            tm.claim_task(task.task_id, "agent-2")

    def test_claim_already_claimed(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.claim_task(task.task_id, "agent-1")
        with pytest.raises(ValueError, match="cannot be claimed"):
            tm.claim_task(task.task_id, "agent-2")

    def test_claim_completed_raises(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.claim_task(task.task_id, "agent-1")
        tm.update_status(task.task_id, TaskStatus.COMPLETED)
        with pytest.raises(ValueError, match="cannot be claimed"):
            tm.claim_task(task.task_id, "agent-2")

    def test_claim_not_found_raises(self):
        tm = TaskManager()
        with pytest.raises(KeyError):
            tm.claim_task("nonexistent", "agent-1")


class TestTaskManagerAssign:
    def test_assign_pending(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        assigned = tm.assign_task(task.task_id, "agent-1")
        assert assigned.status == TaskStatus.ASSIGNED
        assert assigned.assigned_to == "agent-1"

    def test_assign_not_pending_raises(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.claim_task(task.task_id, "agent-1")
        with pytest.raises(ValueError, match="cannot be assigned"):
            tm.assign_task(task.task_id, "agent-2")

    def test_assign_not_found_raises(self):
        tm = TaskManager()
        with pytest.raises(KeyError):
            tm.assign_task("nonexistent", "agent-1")


class TestTaskManagerUpdateStatus:
    def test_update_to_completed(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.claim_task(task.task_id, "a1")
        updated = tm.update_status(task.task_id, TaskStatus.COMPLETED, {"output": "done"})
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result == {"output": "done"}
        assert updated.completed_at is not None

    def test_update_to_in_progress(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        updated = tm.update_status(task.task_id, TaskStatus.IN_PROGRESS)
        assert updated.status == TaskStatus.IN_PROGRESS

    def test_update_not_found_raises(self):
        tm = TaskManager()
        with pytest.raises(KeyError):
            tm.update_status("nonexistent", TaskStatus.COMPLETED)


class TestTaskManagerGetAndList:
    def test_get_existing(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        found = tm.get_task(task.task_id)
        assert found is not None
        assert found.task_id == task.task_id

    def test_get_nonexistent(self):
        tm = TaskManager()
        assert tm.get_task("nonexistent") is None

    def test_list_all(self):
        tm = TaskManager()
        tm.create_task(tenant_id="t1", intent="a")
        tm.create_task(tenant_id="t2", intent="b")
        assert len(tm.list_tasks()) == 2

    def test_list_by_tenant(self):
        tm = TaskManager()
        tm.create_task(tenant_id="t1", intent="a")
        tm.create_task(tenant_id="t2", intent="b")
        tasks = tm.list_tasks(tenant_id="t1")
        assert len(tasks) == 1
        assert tasks[0].tenant_id == "t1"

    def test_list_by_status(self):
        tm = TaskManager()
        t1 = tm.create_task(tenant_id="t1", intent="a")
        tm.create_task(tenant_id="t1", intent="b")
        tm.claim_task(t1.task_id, "agent-1")
        pending = tm.list_tasks(status=TaskStatus.PENDING)
        assert len(pending) == 1

    def test_list_by_assigned(self):
        tm = TaskManager()
        t1 = tm.create_task(tenant_id="t1", intent="a")
        tm.create_task(tenant_id="t1", intent="b")
        tm.assign_task(t1.task_id, "agent-1")
        assigned = tm.list_tasks(assigned_to="agent-1")
        assert len(assigned) == 1

    def test_list_ordered_by_priority(self):
        tm = TaskManager()
        tm.create_task(tenant_id="t1", intent="low", priority=1)
        tm.create_task(tenant_id="t1", intent="high", priority=10)
        tm.create_task(tenant_id="t1", intent="medium", priority=5)
        tasks = tm.list_tasks()
        assert tasks[0].priority == 10
        assert tasks[1].priority == 5
        assert tasks[2].priority == 1

    def test_list_empty(self):
        tm = TaskManager()
        assert tm.list_tasks() == []


class TestTaskManagerReleaseExpired:
    def test_release_expired(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.claim_task(task.task_id, "agent-1")
        # Simulate old claim
        task.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        released = tm.release_expired_claims(lease_minutes=5)
        assert len(released) == 1
        assert released[0].status == TaskStatus.PENDING
        assert released[0].assigned_to == ""
        assert released[0].claimed_at is None

    def test_no_expired(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.claim_task(task.task_id, "agent-1")
        released = tm.release_expired_claims(lease_minutes=5)
        assert len(released) == 0

    def test_release_only_claimed(self):
        tm = TaskManager()
        t1 = tm.create_task(tenant_id="t1", intent="a")
        tm.create_task(tenant_id="t1", intent="b")
        tm.claim_task(t1.task_id, "agent-1")
        t1.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        released = tm.release_expired_claims(lease_minutes=5)
        assert len(released) == 1
        assert released[0].task_id == t1.task_id

    def test_custom_lease_minutes(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.claim_task(task.task_id, "agent-1")
        task.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=3)
        assert len(tm.release_expired_claims(lease_minutes=5)) == 0
        assert len(tm.release_expired_claims(lease_minutes=2)) == 1


class TestTaskManagerRetryOrFail:
    def test_retry(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test", max_retries=3)
        result = tm.retry_or_fail(task.task_id, error="timeout")
        assert result.status == TaskStatus.PENDING
        assert result.retry_count == 1
        assert result.result == {"last_error": "timeout"}

    def test_retry_exhausted(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test", max_retries=1)
        tm.retry_or_fail(task.task_id, error="first")
        result = tm.retry_or_fail(task.task_id, error="second")
        assert result.status == TaskStatus.FAILED
        assert result.result["retries_exhausted"] is True
        assert result.completed_at is not None

    def test_retry_not_found_raises(self):
        tm = TaskManager()
        with pytest.raises(KeyError):
            tm.retry_or_fail("nonexistent")

    def test_retry_resets_assignment(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="test")
        tm.claim_task(task.task_id, "agent-1")
        result = tm.retry_or_fail(task.task_id, error="failed")
        assert result.assigned_to == ""
        assert result.claimed_at is None


# ---------------------------------------------------------------------------
# TaskDispatcher tests
# ---------------------------------------------------------------------------


class TestTaskDispatcher:
    def _make_registry_with_ready_agents(self):
        """Create a registry with ready agents."""
        reg = AgentRegistry()
        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="a1",
            capabilities=[
                Capability(name="code", confidence=0.9),
                Capability(name="debug", confidence=0.7),
            ],
        )
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)

        reg.register(
            tenant_id="t1",
            role="reviewer",
            agent_id="a2",
            capabilities=[
                Capability(name="review", confidence=0.95),
                Capability(name="code", confidence=0.6),
            ],
        )
        reg.update_state("t1", "a2", AgentState.INITIALIZING)
        reg.update_state("t1", "a2", AgentState.READY)

        return reg

    def test_dispatch_to_best_match(self):
        reg = self._make_registry_with_ready_agents()
        tm = TaskManager()
        dispatcher = TaskDispatcher(tm, reg)

        task = tm.create_task(
            tenant_id="t1",
            intent="write code",
            required_capabilities=["code"],
        )
        dispatcher.dispatch(task)
        assert task.assigned_to == "a1"  # higher confidence for code

    def test_dispatch_no_capabilities(self):
        reg = self._make_registry_with_ready_agents()
        tm = TaskManager()
        dispatcher = TaskDispatcher(tm, reg)

        task = tm.create_task(tenant_id="t1", intent="broadcast")
        dispatcher.dispatch(task)
        assert task.status == TaskStatus.PENDING
        assert task.assigned_to == ""

    def test_dispatch_no_matching_agent(self):
        reg = self._make_registry_with_ready_agents()
        tm = TaskManager()
        dispatcher = TaskDispatcher(tm, reg)

        task = tm.create_task(
            tenant_id="t1",
            intent="deploy",
            required_capabilities=["deploy"],
        )
        dispatcher.dispatch(task)
        assert task.status == TaskStatus.PENDING

    def test_dispatch_multi_capability(self):
        reg = self._make_registry_with_ready_agents()
        tm = TaskManager()
        dispatcher = TaskDispatcher(tm, reg)

        task = tm.create_task(
            tenant_id="t1",
            intent="debug code",
            required_capabilities=["code", "debug"],
        )
        dispatcher.dispatch(task)
        assert task.assigned_to == "a1"  # only a1 has both

    def test_dispatch_tenant_isolation(self):
        reg = self._make_registry_with_ready_agents()
        # Add agent in different tenant
        reg.register(
            tenant_id="t2",
            role="dev",
            agent_id="a3",
            capabilities=[Capability(name="code", confidence=1.0)],
        )
        reg.update_state("t2", "a3", AgentState.INITIALIZING)
        reg.update_state("t2", "a3", AgentState.READY)

        tm = TaskManager()
        dispatcher = TaskDispatcher(tm, reg)

        task = tm.create_task(
            tenant_id="t1",
            intent="code",
            required_capabilities=["code"],
        )
        dispatcher.dispatch(task)
        assert task.assigned_to in ("a1", "a2")  # not a3

    def test_dispatch_only_ready_agents(self):
        reg = AgentRegistry()
        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="a1",
            capabilities=[Capability(name="code", confidence=0.9)],
        )
        # a1 is in BOOT state, not READY
        tm = TaskManager()
        dispatcher = TaskDispatcher(tm, reg)

        task = tm.create_task(
            tenant_id="t1",
            intent="code",
            required_capabilities=["code"],
        )
        dispatcher.dispatch(task)
        assert task.assigned_to == ""

    def test_dispatch_empty_registry(self):
        reg = AgentRegistry()
        tm = TaskManager()
        dispatcher = TaskDispatcher(tm, reg)

        task = tm.create_task(
            tenant_id="t1",
            intent="code",
            required_capabilities=["code"],
        )
        dispatcher.dispatch(task)
        assert task.assigned_to == ""
