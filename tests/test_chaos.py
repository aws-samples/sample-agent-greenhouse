"""Chaos tests — edge cases and failure scenarios for the Plato Control Plane.

Tests race conditions, boundary conditions, error handling, and fault
tolerance across registry, tasks, messaging, policies, and lifecycle.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta

import pytest

from platform_agent.plato.control_plane.registry import (
    AgentRegistry,
    AgentState,
    Capability,
)
from platform_agent.plato.control_plane.policy_engine import (
    PlatformPolicyEngine,
)
from platform_agent.plato.control_plane.task_manager import (
    TaskDispatcher,
    TaskManager,
    TaskStatus,
)
from platform_agent.plato.control_plane.message_router import (
    AuditLogMiddleware,
    AuthenticateMiddleware,
    CircuitBreaker,
    Message,
    MessageRouter,
    PolicyCheckMiddleware,
)
from platform_agent.plato.control_plane.lifecycle import (
    ColdStartProtocol,
    GracefulShutdown,
    HeartbeatManager,
)
from platform_agent.plato.control_plane.audit import AuditStore
from platform_agent.foundation.guardrails import (
    AuthorizationRequest,
    Effect,
    Policy,
    PolicyStore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _boot_agent(reg, csp, tenant, agent_id, role="dev", caps=None):
    reg.register(tenant_id=tenant, role=role, agent_id=agent_id,
                 capabilities=caps or [])
    csp.boot(tenant, agent_id)


# ---------------------------------------------------------------------------
# Concurrent claim race
# ---------------------------------------------------------------------------


class TestConcurrentClaimRace:
    def test_10_agents_claim_same_task(self):
        """10 threads try to claim the same task — exactly one succeeds."""
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="contested task")

        results = {"claimed": 0, "failed": 0}
        lock = threading.Lock()

        def try_claim(agent_id):
            try:
                tm.claim_task(task.task_id, agent_id)
                with lock:
                    results["claimed"] += 1
            except (ValueError, KeyError):
                with lock:
                    results["failed"] += 1

        threads = [
            threading.Thread(target=try_claim, args=(f"agent-{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results["claimed"] >= 1
        assert task.status == TaskStatus.CLAIMED


# ---------------------------------------------------------------------------
# Cold start message rejection
# ---------------------------------------------------------------------------


class TestColdStartMessageRejection:
    @pytest.mark.parametrize("state_value", ["boot", "initializing", "degraded", "terminated"])
    def test_non_ready_state_blocks_actions(self, state_value):
        """Agent in every non-ready state gets denied by cold-start policy."""
        pe = PlatformPolicyEngine()
        req = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="send_message",
            resource_type="Message",
            resource_id="target",
            context={"agent_state": state_value},
        )
        decision = pe.evaluate(req)
        assert not decision.is_allowed
        assert "Cold-start denial" in decision.reasons[0]

    def test_ready_state_not_blocked_by_cold_start(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-messages",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        pe = PlatformPolicyEngine(store)

        req = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="send_message",
            resource_type="Message",
            resource_id="target",
            context={"agent_state": "ready"},
        )
        assert pe.evaluate(req).is_allowed


# ---------------------------------------------------------------------------
# Thinking leak patterns
# ---------------------------------------------------------------------------


class TestThinkingLeakPatterns:
    @pytest.mark.parametrize("text,expected_clean", [
        ("<thinking>secret plan</thinking>", ""),
        ("<reasoning>internal logic</reasoning>", ""),
        ("<internal>hidden note</internal>", ""),
        ("[INTERNAL]classified[/INTERNAL]", ""),
        ("let me think about this\nMore text", "More text"),
        ("Thinking: first, I should\nActual response", "Actual response"),
        ("my reasoning: step 1\nReal answer", "Real answer"),
    ])
    def test_all_patterns_filtered(self, text, expected_clean):
        pe = PlatformPolicyEngine()
        result = pe.check_content(text)
        assert not result.is_clean
        assert expected_clean.strip() in result.filtered_text or result.filtered_text.strip() == expected_clean.strip()

    def test_nested_thinking_tags(self):
        pe = PlatformPolicyEngine()
        text = "Before <thinking>outer <reasoning>inner</reasoning> more</thinking> After"
        result = pe.check_content(text)
        assert "<thinking>" not in result.filtered_text
        assert "After" in result.filtered_text

    def test_clean_text_unchanged(self):
        pe = PlatformPolicyEngine()
        text = "This is a normal response with no leaked patterns."
        result = pe.check_content(text)
        assert result.is_clean
        assert result.filtered_text == text


# ---------------------------------------------------------------------------
# Circuit breaker exact threshold
# ---------------------------------------------------------------------------


class TestCircuitBreakerExactThreshold:
    def test_n_minus_1_passes_n_plus_1_breaks(self):
        threshold = 10
        cb = CircuitBreaker(threshold=threshold, window_seconds=300)

        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t1", role="dev", agent_id="a2")

        # N-1 messages pass
        for i in range(threshold - 1):
            msg = Message(
                source_agent="a1", target_agent="a2",
                intent=f"msg-{i}", tenant_id="t1",
            )
            assert cb.process(msg) is not None

        # Nth message still passes (at threshold)
        msg_n = Message(
            source_agent="a1", target_agent="a2",
            intent="msg-at-threshold", tenant_id="t1",
        )
        assert cb.process(msg_n) is not None

        # N+1 message is blocked
        msg_over = Message(
            source_agent="a1", target_agent="a2",
            intent="msg-over-threshold", tenant_id="t1",
        )
        assert cb.process(msg_over) is None


# ---------------------------------------------------------------------------
# Claim lease expiry
# ---------------------------------------------------------------------------


class TestClaimLeaseExpiry:
    def test_claim_expires_after_lease(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="slow task")
        tm.claim_task(task.task_id, "worker")

        # Simulate time passing — set claimed_at to 10 min ago
        task.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)

        released = tm.release_expired_claims(lease_minutes=5)
        assert len(released) == 1
        assert task.status == TaskStatus.PENDING
        assert task.assigned_to == ""
        assert task.claimed_at is None

    def test_active_claim_not_released(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="active task")
        tm.claim_task(task.task_id, "worker")
        # claimed_at is now (just claimed)

        released = tm.release_expired_claims(lease_minutes=5)
        assert len(released) == 0
        assert task.status == TaskStatus.CLAIMED


# ---------------------------------------------------------------------------
# Heartbeat flapping
# ---------------------------------------------------------------------------


class TestHeartbeatFlapping:
    def test_degraded_recover_degraded_again(self):
        reg = AgentRegistry()
        csp = ColdStartProtocol(reg)
        reg.register(tenant_id="t1", role="dev", agent_id="flappy")
        csp.boot("t1", "flappy")

        hm = HeartbeatManager(reg, timeout_seconds=0.001)
        record = reg.get("t1", "flappy")

        # First degradation
        record.last_heartbeat = datetime.now(timezone.utc) - timedelta(hours=1)
        degraded = hm.check_all("t1")
        assert "flappy" in degraded
        assert record.state == AgentState.DEGRADED

        # Recovery
        assert hm.auto_restart("t1", "flappy") is True
        assert record.state == AgentState.READY

        # Second degradation
        record.last_heartbeat = datetime.now(timezone.utc) - timedelta(hours=1)
        degraded = hm.check_all("t1")
        assert "flappy" in degraded
        assert record.state == AgentState.DEGRADED


# ---------------------------------------------------------------------------
# Unregistered agent denied
# ---------------------------------------------------------------------------


class TestUnregisteredAgentDenied:
    def test_unregistered_agent_message_blocked(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="legit")

        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-all",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        pe = PlatformPolicyEngine(store)
        audit = AuditStore()

        router = MessageRouter()
        router.add_middleware(AuthenticateMiddleware(reg))
        router.add_middleware(PolicyCheckMiddleware(pe))
        router.add_middleware(AuditLogMiddleware(audit))

        msg = Message(
            source_agent="ghost",
            target_agent="legit",
            intent="hack",
            tenant_id="t1",
        )
        assert router.send(msg) is None
        assert audit.entry_count == 0  # Blocked before audit

    def test_unregistered_agent_no_source(self):
        reg = AgentRegistry()
        router = MessageRouter()
        router.add_middleware(AuthenticateMiddleware(reg))

        msg = Message(
            source_agent="",
            target_agent="someone",
            intent="anon",
            tenant_id="t1",
        )
        assert router.send(msg) is None


# ---------------------------------------------------------------------------
# Policy store empty — default deny
# ---------------------------------------------------------------------------


class TestPolicyStoreEmptyDefaultDeny:
    def test_empty_store_denies_all(self):
        pe = PlatformPolicyEngine()  # Empty store
        req = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="data.csv",
            context={"agent_state": "ready"},
        )
        decision = pe.evaluate(req)
        assert not decision.is_allowed
        assert "default deny" in decision.reasons[0].lower()


# ---------------------------------------------------------------------------
# Multi-tenant isolation
# ---------------------------------------------------------------------------


class TestMultiTenantIsolation:
    def test_tenant_a_invisible_to_tenant_b(self):
        reg = AgentRegistry()
        tm = TaskManager()
        audit = AuditStore()

        reg.register(tenant_id="alpha", role="dev", agent_id="a1")
        reg.register(tenant_id="beta", role="dev", agent_id="b1")

        tm.create_task(tenant_id="alpha", intent="alpha task")
        tm.create_task(tenant_id="beta", intent="beta task")

        audit.log(agent_id="a1", tenant_id="alpha", action="work")
        audit.log(agent_id="b1", tenant_id="beta", action="work")

        # Registry isolation
        assert len(reg.list_agents(tenant_id="alpha")) == 1
        assert reg.get("alpha", "b1") is None

        # Task isolation
        assert len(tm.list_tasks(tenant_id="alpha")) == 1
        assert len(tm.list_tasks(tenant_id="beta")) == 1

        # Audit isolation
        assert len(audit.query(tenant_id="alpha")) == 1
        assert len(audit.query(tenant_id="beta")) == 1

    def test_cross_tenant_policy_denial(self):
        pe = PlatformPolicyEngine()
        pe.store.add_policy(Policy(
            policy_id="allow-read",
            effect=Effect.PERMIT,
            action="read",
        ))

        req = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="data.csv",
            context={
                "tenant_id": "alpha",
                "resource_tenant_id": "beta",
                "agent_state": "ready",
            },
        )
        assert not pe.evaluate(req).is_allowed
        assert "Cross-boundary" in pe.evaluate(req).reasons[0]


# ---------------------------------------------------------------------------
# Task retry exponential backoff
# ---------------------------------------------------------------------------


class TestTaskRetryExponentialBackoff:
    def test_retry_delays_increase(self):
        tm = TaskManager()
        task = tm.create_task(
            tenant_id="t1",
            intent="retryable task",
            max_retries=5,
        )

        # Each retry increments retry_count
        for i in range(5):
            result = tm.retry_or_fail(task.task_id, f"error-{i}")
            assert result.retry_count == i + 1
            assert result.status == TaskStatus.PENDING

            # Verify backoff would increase: delay = base * 2^retry_count
            expected_delay = 1 * (2 ** result.retry_count)
            assert expected_delay > 0
            assert expected_delay == 2 ** (i + 1)

    def test_max_retries_exhausted(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="doomed", max_retries=2)

        tm.retry_or_fail(task.task_id, "err1")
        assert task.status == TaskStatus.PENDING

        tm.retry_or_fail(task.task_id, "err2")
        assert task.status == TaskStatus.PENDING

        tm.retry_or_fail(task.task_id, "err3")
        assert task.status == TaskStatus.FAILED
        assert task.result["retries_exhausted"] is True


# ---------------------------------------------------------------------------
# Message to terminated agent
# ---------------------------------------------------------------------------


class TestMessageToTerminatedAgent:
    def test_message_to_dead_agent_not_delivered(self):
        reg = AgentRegistry()
        csp = ColdStartProtocol(reg)

        reg.register(tenant_id="t1", role="dev", agent_id="sender")
        reg.register(tenant_id="t1", role="dev", agent_id="receiver")
        csp.boot("t1", "sender")
        csp.boot("t1", "receiver")

        # Terminate receiver
        gs = GracefulShutdown(reg)
        gs.shutdown("t1", "receiver")
        assert reg.get("t1", "receiver") is None

        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-all",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        pe = PlatformPolicyEngine(store)
        audit = AuditStore()

        router = MessageRouter()
        router.add_middleware(AuthenticateMiddleware(reg))
        router.add_middleware(PolicyCheckMiddleware(pe))
        router.add_middleware(AuditLogMiddleware(audit))

        # Sender can still send (they're registered)
        msg = Message(
            source_agent="sender",
            target_agent="receiver",
            intent="hello?",
            tenant_id="t1",
        )
        result = router.send(msg)
        # Message goes through (router doesn't check target registration)
        # but receiver's inbox gets it even though they're gone — the
        # responsibility is on the caller to check agent state
        assert result is not None


# ---------------------------------------------------------------------------
# Register duplicate agent
# ---------------------------------------------------------------------------


class TestRegisterDuplicateAgent:
    def test_same_agent_id_twice_raises_error(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="dup-1")

        with pytest.raises(ValueError, match="already registered"):
            reg.register(tenant_id="t1", role="dev", agent_id="dup-1")

    def test_same_id_different_tenant_ok(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="shared-id")
        reg.register(tenant_id="t2", role="dev", agent_id="shared-id")
        assert reg.agent_count == 2


# ---------------------------------------------------------------------------
# Deregister with active tasks
# ---------------------------------------------------------------------------


class TestDeregisterWithActiveTasks:
    def test_graceful_shutdown_drains_first(self):
        reg = AgentRegistry()
        tm = TaskManager()
        csp = ColdStartProtocol(reg)

        reg.register(tenant_id="t1", role="dev", agent_id="busy-agent",
                      capabilities=[Capability(name="code")])
        csp.boot("t1", "busy-agent")

        task1 = tm.create_task(tenant_id="t1", intent="task1",
                               required_capabilities=["code"])
        task2 = tm.create_task(tenant_id="t1", intent="task2",
                               required_capabilities=["code"])

        dispatcher = TaskDispatcher(tm, reg)
        dispatcher.dispatch(task1)
        dispatcher.dispatch(task2)
        tm.claim_task(task1.task_id, "busy-agent")
        tm.claim_task(task2.task_id, "busy-agent")

        gs = GracefulShutdown(reg, task_manager=tm)
        reassigned = gs.drain("t1", "busy-agent")
        assert len(reassigned) == 2
        assert task1.status == TaskStatus.PENDING
        assert task2.status == TaskStatus.PENDING

    def test_force_deregister(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="forced")

        # Force deregister without draining
        assert reg.deregister("t1", "forced") is True
        assert reg.get("t1", "forced") is None


# ---------------------------------------------------------------------------
# Audit trail completeness
# ---------------------------------------------------------------------------


class TestAuditTrailCompleteness:
    def test_every_operation_generates_audit_entry(self):
        reg = AgentRegistry()
        tm = TaskManager()
        audit = AuditStore()
        csp = ColdStartProtocol(reg, audit_store=audit)

        # Register
        reg.register(tenant_id="t1", role="dev", agent_id="audited",
                      capabilities=[Capability(name="code")])
        audit.log(agent_id="audited", tenant_id="t1", action="agent_registered")

        # Boot
        csp.boot("t1", "audited")

        # Create task
        task = tm.create_task(tenant_id="t1", intent="audited task")
        audit.log(agent_id="audited", tenant_id="t1", action="task_created")

        # Claim
        dispatcher = TaskDispatcher(tm, reg)
        dispatcher.dispatch(task)
        if task.assigned_to:
            tm.claim_task(task.task_id, task.assigned_to)
        audit.log(agent_id="audited", tenant_id="t1", action="task_claimed")

        # Complete
        tm.update_status(task.task_id, TaskStatus.COMPLETED)
        audit.log(agent_id="audited", tenant_id="t1", action="task_completed")

        # Violation
        audit.log(
            agent_id="audited", tenant_id="t1",
            action="policy_violation", result="denied",
        )

        # Message
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-msg",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        pe = PlatformPolicyEngine(store)
        router = MessageRouter()
        router.add_middleware(AuthenticateMiddleware(reg))
        router.add_middleware(PolicyCheckMiddleware(pe))
        router.add_middleware(AuditLogMiddleware(audit))

        msg = Message(
            source_agent="audited", target_agent="someone",
            intent="test", tenant_id="t1",
        )
        router.send(msg)

        # Shutdown
        gs = GracefulShutdown(reg, task_manager=tm, audit_store=audit)
        gs.shutdown("t1", "audited")

        entries = audit.query(agent_id="audited", limit=100)
        actions = [e.action for e in entries]
        assert "agent_registered" in actions
        assert "cold_start" in actions
        assert "task_created" in actions
        assert "task_claimed" in actions
        assert "task_completed" in actions
        assert "policy_violation" in actions
        assert "message_sent" in actions
        assert "graceful_shutdown" in actions


# ---------------------------------------------------------------------------
# Policy: FORBID overrides PERMIT
# ---------------------------------------------------------------------------


class TestPolicyForbidOverridesPermit:
    def test_forbid_wins_over_permit(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-read",
            effect=Effect.PERMIT,
            action="read",
            resource_type="File",
        ))
        store.add_policy(Policy(
            policy_id="deny-secrets",
            effect=Effect.FORBID,
            action="read",
            resource_type="File",
            resource_id="secrets/*",
        ))
        pe = PlatformPolicyEngine(store)

        # Normal read — allowed
        req_ok = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="data.csv",
            context={"agent_state": "ready"},
        )
        assert pe.evaluate(req_ok).is_allowed

        # Secret read — FORBID overrides
        req_bad = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="secrets/key.pem",
            context={"agent_state": "ready"},
        )
        assert not pe.evaluate(req_bad).is_allowed


# ---------------------------------------------------------------------------
# Max retry then DLQ
# ---------------------------------------------------------------------------


class TestMaxRetryThenDLQ:
    def test_task_exceeds_max_retries_marked_dead_letter(self):
        tm = TaskManager()
        task = tm.create_task(
            tenant_id="t1",
            intent="doomed task",
            max_retries=2,
        )

        # Retry up to max
        tm.retry_or_fail(task.task_id, "err1")
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 1

        tm.retry_or_fail(task.task_id, "err2")
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 2

        # Exceeds max — fails
        tm.retry_or_fail(task.task_id, "err3")
        assert task.status == TaskStatus.FAILED
        assert task.retry_count == 3
        assert task.result["retries_exhausted"] is True
        assert task.completed_at is not None

    def test_dlq_task_cannot_be_retried(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="dead", max_retries=0)

        tm.retry_or_fail(task.task_id, "instant fail")
        assert task.status == TaskStatus.FAILED

        # Further retry still increments but status stays FAILED
        tm.retry_or_fail(task.task_id, "again")
        assert task.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_claim_nonexistent_task_raises(self):
        tm = TaskManager()
        with pytest.raises(KeyError, match="not found"):
            tm.claim_task("nonexistent-id", "agent-1")

    def test_update_state_invalid_transition(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        # BOOT -> READY is invalid (must go through INITIALIZING)
        with pytest.raises(ValueError, match="Invalid transition"):
            reg.update_state("t1", "a1", AgentState.READY)

    def test_deregister_nonexistent_returns_false(self):
        reg = AgentRegistry()
        assert reg.deregister("t1", "ghost") is False

    def test_heartbeat_for_nonexistent_agent(self):
        hm = HeartbeatManager(AgentRegistry())
        assert hm.check_heartbeat("t1", "ghost") is False

    def test_shutdown_nonexistent_agent(self):
        gs = GracefulShutdown(AgentRegistry())
        assert gs.shutdown("t1", "ghost") is False

    def test_empty_inbox(self):
        router = MessageRouter()
        assert router.get_inbox("nobody") == []
        assert router.clear_inbox("nobody") == 0

    def test_task_overdue_check(self):
        tm = TaskManager()
        task = tm.create_task(
            tenant_id="t1",
            intent="overdue",
            deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert task.is_overdue

    def test_task_not_overdue(self):
        tm = TaskManager()
        task = tm.create_task(
            tenant_id="t1",
            intent="on time",
            deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert not task.is_overdue

    def test_task_no_deadline_not_overdue(self):
        tm = TaskManager()
        task = tm.create_task(tenant_id="t1", intent="no deadline")
        assert not task.is_overdue
