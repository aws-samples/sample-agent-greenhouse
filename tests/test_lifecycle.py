"""Tests for Lifecycle Manager — ColdStartProtocol, HeartbeatManager, GracefulShutdown."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from platform_agent.plato.control_plane.lifecycle import (
    ColdStartProtocol,
    GracefulShutdown,
    HeartbeatManager,
)
from platform_agent.plato.control_plane.registry import (
    AgentRegistry,
    AgentState,
)
from platform_agent.plato.control_plane.task_manager import TaskManager, TaskStatus
from platform_agent.plato.control_plane.audit import AuditStore


# ---------------------------------------------------------------------------
# ColdStartProtocol tests
# ---------------------------------------------------------------------------


class TestColdStartProtocol:
    def test_boot_success(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        csp = ColdStartProtocol(reg)
        assert csp.boot("t1", "a1") is True
        record = reg.get("t1", "a1")
        assert record.state == AgentState.READY
        assert record.last_heartbeat is not None

    def test_boot_not_found(self):
        reg = AgentRegistry()
        csp = ColdStartProtocol(reg)
        with pytest.raises(KeyError):
            csp.boot("t1", "a1")

    def test_boot_with_audit(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        audit = AuditStore()
        csp = ColdStartProtocol(reg, audit_store=audit)
        csp.boot("t1", "a1")
        entries = audit.query(agent_id="a1")
        assert len(entries) == 1
        assert entries[0].action == "cold_start"
        assert entries[0].result == "success"

    def test_boot_fails_no_role(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="", agent_id="a1")
        csp = ColdStartProtocol(reg)
        result = csp.boot("t1", "a1")
        assert result is False
        record = reg.get("t1", "a1")
        assert record.state == AgentState.DEGRADED

    def test_boot_with_policy_engine(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")

        class MockPolicyEngine:
            pass

        csp = ColdStartProtocol(reg, policy_engine=MockPolicyEngine())
        assert csp.boot("t1", "a1") is True

    def test_boot_audit_failure(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="", agent_id="a1")
        audit = AuditStore()
        csp = ColdStartProtocol(reg, audit_store=audit)
        csp.boot("t1", "a1")
        entries = audit.query(agent_id="a1")
        assert entries[0].result == "failure"

    def test_boot_from_boot_state(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        csp = ColdStartProtocol(reg)
        assert csp.boot("t1", "a1") is True

    def test_cannot_boot_terminated(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.TERMINATED)
        csp = ColdStartProtocol(reg)
        result = csp.boot("t1", "a1")
        assert result is False


# ---------------------------------------------------------------------------
# HeartbeatManager tests
# ---------------------------------------------------------------------------


class TestHeartbeatManager:
    def test_check_current_heartbeat(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_heartbeat("t1", "a1")
        hm = HeartbeatManager(reg, timeout_seconds=30)
        assert hm.check_heartbeat("t1", "a1") is True

    def test_check_stale_heartbeat(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        stale = datetime.now(timezone.utc) - timedelta(minutes=5)
        reg.update_heartbeat("t1", "a1", timestamp=stale)
        hm = HeartbeatManager(reg, timeout_seconds=30)
        assert hm.check_heartbeat("t1", "a1") is False

    def test_check_no_heartbeat(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        hm = HeartbeatManager(reg, timeout_seconds=30)
        assert hm.check_heartbeat("t1", "a1") is False

    def test_check_nonexistent_agent(self):
        reg = AgentRegistry()
        hm = HeartbeatManager(reg)
        assert hm.check_heartbeat("t1", "a1") is False

    def test_check_all_marks_degraded(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        # No heartbeat set, so it should be marked degraded
        hm = HeartbeatManager(reg, timeout_seconds=30)
        degraded = hm.check_all("t1")
        assert "a1" in degraded
        record = reg.get("t1", "a1")
        assert record.state == AgentState.DEGRADED

    def test_check_all_healthy(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        reg.update_heartbeat("t1", "a1")
        hm = HeartbeatManager(reg, timeout_seconds=30)
        degraded = hm.check_all("t1")
        assert len(degraded) == 0

    def test_check_all_skips_boot(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        hm = HeartbeatManager(reg, timeout_seconds=30)
        degraded = hm.check_all("t1")
        assert len(degraded) == 0  # BOOT agents not checked

    def test_mark_degraded(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        hm = HeartbeatManager(reg)
        assert hm.mark_degraded("t1", "a1") is True
        assert reg.get("t1", "a1").state == AgentState.DEGRADED

    def test_mark_degraded_already_degraded(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.DEGRADED)
        hm = HeartbeatManager(reg)
        assert hm.mark_degraded("t1", "a1") is False

    def test_mark_degraded_nonexistent(self):
        reg = AgentRegistry()
        hm = HeartbeatManager(reg)
        assert hm.mark_degraded("t1", "a1") is False

    def test_mark_degraded_with_audit(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        audit = AuditStore()
        hm = HeartbeatManager(reg, audit_store=audit)
        hm.mark_degraded("t1", "a1")
        entries = audit.query(action="heartbeat_missed")
        assert len(entries) == 1

    def test_auto_restart_degraded(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.DEGRADED)
        hm = HeartbeatManager(reg)
        assert hm.auto_restart("t1", "a1") is True
        record = reg.get("t1", "a1")
        assert record.state == AgentState.READY
        assert record.last_heartbeat is not None

    def test_auto_restart_not_degraded(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        hm = HeartbeatManager(reg)
        assert hm.auto_restart("t1", "a1") is False

    def test_auto_restart_nonexistent(self):
        reg = AgentRegistry()
        hm = HeartbeatManager(reg)
        assert hm.auto_restart("t1", "a1") is False


# ---------------------------------------------------------------------------
# GracefulShutdown tests
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    def test_shutdown_success(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        gs = GracefulShutdown(reg)
        assert gs.shutdown("t1", "a1") is True
        assert reg.get("t1", "a1") is None

    def test_shutdown_nonexistent(self):
        reg = AgentRegistry()
        gs = GracefulShutdown(reg)
        assert gs.shutdown("t1", "a1") is False

    def test_shutdown_with_audit(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        audit = AuditStore()
        gs = GracefulShutdown(reg, audit_store=audit)
        gs.shutdown("t1", "a1")
        entries = audit.query(action="graceful_shutdown")
        assert len(entries) == 1

    def test_drain_reassigns_tasks(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        tm = TaskManager()
        t1 = tm.create_task(tenant_id="t1", intent="task1")
        tm.assign_task(t1.task_id, "a1")
        tm.claim_task(t1.task_id, "a1")

        gs = GracefulShutdown(reg, task_manager=tm)
        reassigned = gs.drain("t1", "a1")
        assert len(reassigned) == 1
        assert t1.status == TaskStatus.PENDING
        assert t1.assigned_to == ""

    def test_drain_skips_terminal_tasks(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        tm = TaskManager()
        t1 = tm.create_task(tenant_id="t1", intent="done")
        tm.claim_task(t1.task_id, "a1")
        tm.update_status(t1.task_id, TaskStatus.COMPLETED)

        gs = GracefulShutdown(reg, task_manager=tm)
        reassigned = gs.drain("t1", "a1")
        assert len(reassigned) == 0

    def test_drain_no_task_manager(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        gs = GracefulShutdown(reg)
        reassigned = gs.drain("t1", "a1")
        assert len(reassigned) == 0

    def test_shutdown_drains_then_deregisters(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        tm = TaskManager()
        t1 = tm.create_task(tenant_id="t1", intent="task1")
        tm.assign_task(t1.task_id, "a1")
        tm.claim_task(t1.task_id, "a1")

        gs = GracefulShutdown(reg, task_manager=tm)
        gs.shutdown("t1", "a1")
        assert t1.status == TaskStatus.PENDING
        assert reg.get("t1", "a1") is None
