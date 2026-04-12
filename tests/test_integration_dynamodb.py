"""Integration tests — DynamoDB-backed Control Plane stores.

Uses moto to mock DynamoDB. Validates that DDB-backed stores have
the same behavior as in-memory stores.
"""

from __future__ import annotations


import boto3
import pytest
from moto import mock_aws

from platform_agent.plato.control_plane.dynamodb_store import (
    DynamoDBAgentRegistry,
    DynamoDBAuditStore,
    DynamoDBTaskManager,
    create_table,
)
from platform_agent.plato.control_plane.registry import AgentState, Capability
from platform_agent.plato.control_plane.task_manager import TaskStatus, TaskType


@pytest.fixture
def ddb_table():
    """Create a mocked DynamoDB table for tests."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = create_table(dynamodb, "test-control-plane")
        yield table


@pytest.fixture
def registry(ddb_table):
    return DynamoDBAgentRegistry(ddb_table)


@pytest.fixture
def task_mgr(ddb_table):
    return DynamoDBTaskManager(ddb_table)


@pytest.fixture
def audit(ddb_table):
    return DynamoDBAuditStore(ddb_table)


# ── Registry Tests ──


class TestDynamoDBAgentRegistry:
    """Test DynamoDB-backed agent registry."""

    def test_register_and_get(self, registry):
        rec = registry.register(
            "tenant-a", "support",
            capabilities=[Capability("triage", 0.9)],
            tools=["OrderAPI"],
            agent_id="agent-01",
        )
        assert rec.agent_id == "agent-01"
        assert rec.tenant_id == "tenant-a"
        assert rec.state == AgentState.BOOT

        fetched = registry.get("tenant-a", "agent-01")
        assert fetched is not None
        assert fetched.role == "support"
        assert len(fetched.capabilities) == 1
        assert fetched.capabilities[0].name == "triage"
        assert fetched.capabilities[0].confidence == 0.9
        assert fetched.tools == ["OrderAPI"]

    def test_register_auto_id(self, registry):
        rec = registry.register("t1", "role1")
        assert rec.agent_id  # Auto-generated UUID
        assert registry.get("t1", rec.agent_id) is not None

    def test_register_duplicate_raises(self, registry):
        registry.register("t1", "r1", agent_id="dup")
        with pytest.raises(ValueError, match="already registered"):
            registry.register("t1", "r2", agent_id="dup")

    def test_list_agents_by_tenant(self, registry):
        registry.register("t1", "r1", agent_id="a1")
        registry.register("t1", "r2", agent_id="a2")
        registry.register("t2", "r3", agent_id="a3")

        t1_agents = registry.list_agents("t1")
        assert len(t1_agents) == 2
        ids = {a.agent_id for a in t1_agents}
        assert ids == {"a1", "a2"}

    def test_list_agents_all(self, registry):
        registry.register("t1", "r1", agent_id="a1")
        registry.register("t2", "r2", agent_id="a2")

        all_agents = registry.list_agents()
        assert len(all_agents) == 2

    def test_deregister(self, registry):
        registry.register("t1", "r1", agent_id="a1")
        assert registry.deregister("t1", "a1") is True
        assert registry.get("t1", "a1") is None
        assert registry.deregister("t1", "a1") is False

    def test_get_nonexistent(self, registry):
        assert registry.get("t1", "nope") is None

    def test_update_state(self, registry):
        registry.register("t1", "r1", agent_id="a1")
        # BOOT → INITIALIZING → READY
        rec = registry.update_state("t1", "a1", AgentState.INITIALIZING)
        assert rec is not None
        assert rec.state == AgentState.INITIALIZING

        rec = registry.update_state("t1", "a1", AgentState.READY)
        assert rec.state == AgentState.READY

        # Verify persisted
        fetched = registry.get("t1", "a1")
        assert fetched.state == AgentState.READY

    def test_update_state_invalid_transition(self, registry):
        registry.register("t1", "r1", agent_id="a1")
        # BOOT → READY is not valid (must go through INITIALIZING)
        rec = registry.update_state("t1", "a1", AgentState.READY)
        assert rec is None

    def test_update_state_terminated_deregisters(self, registry):
        registry.register("t1", "r1", agent_id="a1")
        registry.update_state("t1", "a1", AgentState.TERMINATED)
        assert registry.get("t1", "a1") is None

    def test_update_heartbeat(self, registry):
        registry.register("t1", "r1", agent_id="a1")
        assert registry.update_heartbeat("t1", "a1") is True
        rec = registry.get("t1", "a1")
        assert rec.last_heartbeat is not None

    def test_update_heartbeat_nonexistent(self, registry):
        assert registry.update_heartbeat("t1", "nope") is False

    def test_find_by_state(self, registry):
        registry.register("t1", "r1", agent_id="a1")
        registry.register("t1", "r2", agent_id="a2")
        registry.update_state("t1", "a1", AgentState.INITIALIZING)
        registry.update_state("t1", "a1", AgentState.READY)

        ready = registry.find_by_state(AgentState.READY)
        assert len(ready) == 1
        assert ready[0].agent_id == "a1"

        boot = registry.find_by_state(AgentState.BOOT)
        assert len(boot) == 1
        assert boot[0].agent_id == "a2"

    def test_find_by_state_tenant_filter(self, registry):
        registry.register("t1", "r1", agent_id="a1")
        registry.register("t2", "r2", agent_id="a2")

        boot_t1 = registry.find_by_state(AgentState.BOOT, tenant_id="t1")
        assert len(boot_t1) == 1
        assert boot_t1[0].tenant_id == "t1"

    def test_find_by_capability(self, registry):
        registry.register(
            "t1", "r1",
            capabilities=[Capability("triage", 0.9), Capability("refund", 0.7)],
            agent_id="a1",
        )
        registry.register(
            "t1", "r2",
            capabilities=[Capability("triage", 0.6)],
            agent_id="a2",
        )
        registry.register(
            "t2", "r3",
            capabilities=[Capability("hr_qa", 0.8)],
            agent_id="a3",
        )

        triage_agents = registry.find_by_capability("triage")
        assert len(triage_agents) == 2
        ids = {a.agent_id for a in triage_agents}
        assert ids == {"a1", "a2"}

    def test_find_by_capability_min_confidence(self, registry):
        registry.register("t1", "r1", capabilities=[Capability("x", 0.9)], agent_id="a1")
        registry.register("t1", "r2", capabilities=[Capability("x", 0.3)], agent_id="a2")

        high = registry.find_by_capability("x", min_confidence=0.5)
        assert len(high) == 1
        assert high[0].agent_id == "a1"

    def test_find_by_capability_tenant_filter(self, registry):
        registry.register("t1", "r1", capabilities=[Capability("x", 0.9)], agent_id="a1")
        registry.register("t2", "r2", capabilities=[Capability("x", 0.9)], agent_id="a2")

        t1_only = registry.find_by_capability("x", tenant_id="t1")
        assert len(t1_only) == 1
        assert t1_only[0].tenant_id == "t1"

    def test_agent_count(self, registry):
        assert registry.agent_count == 0
        registry.register("t1", "r1", agent_id="a1")
        registry.register("t2", "r2", agent_id="a2")
        assert registry.agent_count == 2

    def test_multi_tenant_isolation(self, registry):
        """Agents from tenant A cannot be seen through tenant B queries."""
        registry.register("team-a", "support", agent_id="a-agent")
        registry.register("team-b", "hr", agent_id="b-agent")

        a_agents = registry.list_agents("team-a")
        assert len(a_agents) == 1
        assert a_agents[0].agent_id == "a-agent"

        b_agents = registry.list_agents("team-b")
        assert len(b_agents) == 1
        assert b_agents[0].agent_id == "b-agent"

        # Cross-tenant get returns None
        assert registry.get("team-a", "b-agent") is None
        assert registry.get("team-b", "a-agent") is None


# ── Task Manager Tests ──


class TestDynamoDBTaskManager:
    """Test DynamoDB-backed task manager."""

    def test_create_and_get(self, task_mgr):
        task = task_mgr.create_task("t1", "do_thing", task_id="task-01")
        assert task.task_id == "task-01"
        assert task.status == TaskStatus.PENDING

        fetched = task_mgr.get_task("task-01", "t1")
        assert fetched is not None
        assert fetched.intent == "do_thing"

    def test_create_auto_id(self, task_mgr):
        task = task_mgr.create_task("t1", "stuff")
        assert task.task_id
        assert task_mgr.get_task(task.task_id, "t1") is not None

    def test_create_with_all_fields(self, task_mgr):
        task_mgr.create_task(
            "t1", "complex_task",
            task_type=TaskType.BROADCAST,
            source_agent="agent-01",
            payload={"amount": 500},
            required_capabilities=["refund"],
            priority=10,
            max_retries=5,
            parent_task_id="parent-01",
            task_id="task-complex",
        )
        fetched = task_mgr.get_task("task-complex", "t1")
        assert fetched.type == TaskType.BROADCAST
        assert fetched.source_agent == "agent-01"
        assert fetched.payload == {"amount": 500}
        assert fetched.required_capabilities == ["refund"]
        assert fetched.priority == 10
        assert fetched.max_retries == 5
        assert fetched.parent_task_id == "parent-01"

    def test_list_tasks_by_tenant(self, task_mgr):
        task_mgr.create_task("t1", "a", task_id="t1-a")
        task_mgr.create_task("t1", "b", task_id="t1-b")
        task_mgr.create_task("t2", "c", task_id="t2-c")

        t1_tasks = task_mgr.list_tasks("t1")
        assert len(t1_tasks) == 2

    def test_list_tasks_all(self, task_mgr):
        task_mgr.create_task("t1", "a", task_id="ta")
        task_mgr.create_task("t2", "b", task_id="tb")
        assert len(task_mgr.list_tasks()) == 2

    def test_claim_task_success(self, task_mgr):
        task_mgr.create_task("t1", "work", task_id="claim-me")
        claimed = task_mgr.claim_task("claim-me", "agent-01")
        assert claimed.status == TaskStatus.CLAIMED
        assert claimed.assigned_to == "agent-01"
        assert claimed.claimed_at is not None

    def test_claim_task_contention(self, task_mgr):
        """Second claim attempt fails atomically."""
        task_mgr.create_task("t1", "work", task_id="contested")
        task_mgr.claim_task("contested", "agent-01")

        with pytest.raises(ValueError, match="not in pending"):
            task_mgr.claim_task("contested", "agent-02")

    def test_claim_nonexistent_raises(self, task_mgr):
        with pytest.raises(KeyError, match="not found"):
            task_mgr.claim_task("nope", "agent-01")

    def test_assign_task(self, task_mgr):
        task_mgr.create_task("t1", "assign_me", task_id="assign-01")
        assigned = task_mgr.assign_task("assign-01", "agent-01")
        assert assigned.assigned_to == "agent-01"
        assert assigned.status == TaskStatus.ASSIGNED

    def test_update_status(self, task_mgr):
        task_mgr.create_task("t1", "progress", task_id="progress-01")
        task_mgr.assign_task("progress-01", "agent-01")

        updated = task_mgr.update_status("progress-01", TaskStatus.IN_PROGRESS)
        assert updated.status == TaskStatus.IN_PROGRESS

        completed = task_mgr.update_status(
            "progress-01", TaskStatus.COMPLETED, result={"success": True}
        )
        assert completed.status == TaskStatus.COMPLETED
        assert completed.result == {"success": True}

    def test_update_status_nonexistent_raises(self, task_mgr):
        with pytest.raises(KeyError, match="not found"):
            task_mgr.update_status("nope", TaskStatus.COMPLETED)

    def test_get_task_scan_fallback(self, task_mgr):
        """Get task without tenant_id uses scan."""
        task_mgr.create_task("t1", "findme", task_id="scantest")
        found = task_mgr.get_task("scantest")  # No tenant_id
        assert found is not None
        assert found.intent == "findme"

    def test_list_tasks_by_status(self, task_mgr):
        task_mgr.create_task("t1", "a", task_id="s1")
        task_mgr.create_task("t1", "b", task_id="s2")
        task_mgr.assign_task("s1", "agent-01")

        pending = task_mgr.list_tasks("t1", status=TaskStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].task_id == "s2"


# ── Audit Store Tests ──


class TestDynamoDBAuditStore:
    """Test DynamoDB-backed audit store."""

    def test_log_and_report(self, audit):
        audit.log("a1", "t1", "register", "Registered agent", "success")
        audit.log("a2", "t1", "register", "Registered agent", "success")
        audit.log("a1", "t1", "task_done", "Completed task", "success")

        report = audit.generate_report("t1")
        assert report["total_entries"] == 3
        assert report["action_counts"]["register"] == 2
        assert report["result_counts"]["success"] == 3
        assert report["top_agents"]["a1"] == 2
        assert report["violation_count"] == 0

    def test_log_with_dict_details(self, audit):
        entry = audit.log("a1", "t1", "test", {"key": "val"}, "success")
        assert entry.agent_id == "a1"

    def test_violations(self, audit):
        audit.log("a1", "t1", "msg_sent", "", "success")
        audit.log("a1", "t1", "policy_violation", "Denied refund", "denied")
        audit.log("a2", "t1", "content_filtered", "Thinking leak", "filtered")

        violations = audit.get_violations("t1")
        assert len(violations) == 2

    def test_report_empty(self, audit):
        report = audit.generate_report()
        assert report["total_entries"] == 0
        assert report["violation_count"] == 0

    def test_multi_tenant_audit(self, audit):
        audit.log("a1", "t1", "action1", "", "success")
        audit.log("a2", "t2", "action2", "", "success")

        t1_report = audit.generate_report("t1")
        assert t1_report["total_entries"] == 1
        assert "a1" in t1_report["top_agents"]

        t2_report = audit.generate_report("t2")
        assert t2_report["total_entries"] == 1
        assert "a2" in t2_report["top_agents"]

    def test_all_tenant_report(self, audit):
        audit.log("a1", "t1", "x", "", "success")
        audit.log("a2", "t2", "y", "", "success")

        report = audit.generate_report()
        assert report["total_entries"] == 2


# ── Full Integration: Registry + Tasks + Audit ──


class TestFullIntegration:
    """End-to-end integration using all DDB stores together."""

    def test_full_user_journey(self, ddb_table):
        registry = DynamoDBAgentRegistry(ddb_table)
        task_mgr = DynamoDBTaskManager(ddb_table)
        audit = DynamoDBAuditStore(ddb_table)

        # 1. Register agents
        registry.register(
            "platform", "support",
            capabilities=[Capability("triage", 0.9), Capability("refund", 0.8)],
            agent_id="support-01",
        )
        registry.register(
            "platform", "finance",
            capabilities=[Capability("refund_process", 0.9)],
            agent_id="finance-01",
        )
        audit.log("support-01", "platform", "register", "", "success")
        audit.log("finance-01", "platform", "register", "", "success")

        # 2. Cold start (state transitions)
        registry.update_state("platform", "support-01", AgentState.INITIALIZING)
        registry.update_state("platform", "support-01", AgentState.READY)
        registry.update_state("platform", "finance-01", AgentState.INITIALIZING)
        registry.update_state("platform", "finance-01", AgentState.READY)

        ready = registry.find_by_state(AgentState.READY, "platform")
        assert len(ready) == 2

        # 3. Create and dispatch task
        task = task_mgr.create_task(
            "platform", "process_refund",
            required_capabilities=["refund_process"],
            priority=10,
        )
        audit.log("", "platform", "task_created", "", "success")

        # 4. Claim
        claimed = task_mgr.claim_task(task.task_id, "finance-01")
        assert claimed.assigned_to == "finance-01"
        audit.log("finance-01", "platform", "task_claimed", "", "success")

        # 5. Complete
        task_mgr.update_status(task.task_id, TaskStatus.COMPLETED, {"ok": True})
        audit.log("finance-01", "platform", "task_done", "", "success")

        # 6. Report
        report = audit.generate_report("platform")
        assert report["total_entries"] == 5
        assert report["violation_count"] == 0

    def test_concurrent_claim_safety(self, ddb_table):
        """Simulate concurrent claims — only one wins."""
        task_mgr = DynamoDBTaskManager(ddb_table)
        task_mgr.create_task("t1", "contested", task_id="race")

        winner = task_mgr.claim_task("race", "agent-a")
        assert winner.assigned_to == "agent-a"

        with pytest.raises(ValueError):
            task_mgr.claim_task("race", "agent-b")

        # Verify winner persists
        fetched = task_mgr.get_task("race", "t1")
        assert fetched.assigned_to == "agent-a"
