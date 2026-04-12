"""Integration tests for the Plato Control Plane.

Tests cross-module interactions: registry + lifecycle, task dispatch + registry,
message routing with full pipeline, audit tracking across operations, etc.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from platform_agent.plato.control_plane.registry import (
    AgentRegistry,
    AgentState,
    Capability,
)
from platform_agent.plato.control_plane.policy_engine import (
    PlatformPolicyEngine,
    create_agent_policies,
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
    ContentFilterMiddleware,
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
# Registry + Lifecycle integration
# ---------------------------------------------------------------------------


class TestRegistryLifecycleIntegration:
    def test_register_and_boot(self):
        reg = AgentRegistry()
        audit = AuditStore()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        csp = ColdStartProtocol(reg, audit_store=audit)
        assert csp.boot("t1", "a1") is True
        assert reg.get("t1", "a1").state == AgentState.READY
        assert audit.entry_count == 1

    def test_boot_heartbeat_shutdown(self):
        reg = AgentRegistry()
        audit = AuditStore()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")

        csp = ColdStartProtocol(reg, audit_store=audit)
        csp.boot("t1", "a1")

        hm = HeartbeatManager(reg, timeout_seconds=30, audit_store=audit)
        assert hm.check_heartbeat("t1", "a1") is True

        gs = GracefulShutdown(reg, audit_store=audit)
        gs.shutdown("t1", "a1")
        assert reg.get("t1", "a1") is None

    def test_degraded_and_restart(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        csp = ColdStartProtocol(reg)
        csp.boot("t1", "a1")

        hm = HeartbeatManager(reg, timeout_seconds=0.001)
        # Force stale heartbeat
        record = reg.get("t1", "a1")
        record.last_heartbeat = datetime.now(timezone.utc) - timedelta(hours=1)
        degraded = hm.check_all("t1")
        assert "a1" in degraded

        assert hm.auto_restart("t1", "a1") is True
        assert reg.get("t1", "a1").state == AgentState.READY

    def test_multiple_agents_lifecycle(self):
        reg = AgentRegistry()
        csp = ColdStartProtocol(reg)

        for i in range(5):
            reg.register(tenant_id="t1", role="dev", agent_id=f"a{i}")
            csp.boot("t1", f"a{i}")

        ready = reg.find_by_state(AgentState.READY, tenant_id="t1")
        assert len(ready) == 5

        gs = GracefulShutdown(reg)
        gs.shutdown("t1", "a0")
        assert reg.agent_count == 4

    def test_boot_fail_then_retry(self):
        reg = AgentRegistry()
        # Agent with no role will fail self-check
        reg.register(tenant_id="t1", role="", agent_id="a1")
        csp = ColdStartProtocol(reg)
        assert csp.boot("t1", "a1") is False
        assert reg.get("t1", "a1").state == AgentState.DEGRADED

        # Fix the agent and retry via auto_restart
        hm = HeartbeatManager(reg)
        assert hm.auto_restart("t1", "a1") is True


# ---------------------------------------------------------------------------
# Task dispatch + Registry integration
# ---------------------------------------------------------------------------


class TestTaskDispatchIntegration:
    def _setup(self):
        reg = AgentRegistry()
        tm = TaskManager()
        csp = ColdStartProtocol(reg)

        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="coder",
            capabilities=[
                Capability(name="code_generation", confidence=0.95),
                Capability(name="debugging", confidence=0.8),
            ],
        )
        csp.boot("t1", "coder")

        reg.register(
            tenant_id="t1",
            role="reviewer",
            agent_id="reviewer",
            capabilities=[
                Capability(name="code_review", confidence=0.9),
                Capability(name="code_generation", confidence=0.5),
            ],
        )
        csp.boot("t1", "reviewer")

        dispatcher = TaskDispatcher(tm, reg)
        return reg, tm, dispatcher

    def test_dispatch_to_specialist(self):
        _, tm, dispatcher = self._setup()
        task = tm.create_task(
            tenant_id="t1",
            intent="generate code",
            required_capabilities=["code_generation"],
        )
        dispatcher.dispatch(task)
        assert task.assigned_to == "coder"

    def test_dispatch_review_task(self):
        _, tm, dispatcher = self._setup()
        task = tm.create_task(
            tenant_id="t1",
            intent="review pull request",
            required_capabilities=["code_review"],
        )
        dispatcher.dispatch(task)
        assert task.assigned_to == "reviewer"

    def test_dispatch_multi_cap_task(self):
        _, tm, dispatcher = self._setup()
        task = tm.create_task(
            tenant_id="t1",
            intent="debug code",
            required_capabilities=["code_generation", "debugging"],
        )
        dispatcher.dispatch(task)
        assert task.assigned_to == "coder"

    def test_claim_dispatched_task(self):
        _, tm, dispatcher = self._setup()
        task = tm.create_task(
            tenant_id="t1",
            intent="code",
            required_capabilities=["code_generation"],
        )
        dispatcher.dispatch(task)
        claimed = tm.claim_task(task.task_id, "coder")
        assert claimed.status == TaskStatus.CLAIMED

    def test_complete_task_workflow(self):
        _, tm, dispatcher = self._setup()
        task = tm.create_task(
            tenant_id="t1",
            intent="write tests",
            required_capabilities=["code_generation"],
        )
        dispatcher.dispatch(task)
        tm.claim_task(task.task_id, "coder")
        tm.update_status(task.task_id, TaskStatus.IN_PROGRESS)
        tm.update_status(task.task_id, TaskStatus.COMPLETED, {"tests": 10})
        assert task.status == TaskStatus.COMPLETED
        assert task.result["tests"] == 10

    def test_retry_failed_task(self):
        _, tm, dispatcher = self._setup()
        task = tm.create_task(
            tenant_id="t1",
            intent="flaky task",
            required_capabilities=["code_generation"],
            max_retries=2,
        )
        dispatcher.dispatch(task)
        tm.claim_task(task.task_id, "coder")
        result = tm.retry_or_fail(task.task_id, "timeout")
        assert result.status == TaskStatus.PENDING
        # Re-dispatch
        dispatcher.dispatch(result)
        assert result.assigned_to == "coder"

    def test_shutdown_reassigns_tasks(self):
        reg, tm, dispatcher = self._setup()
        task = tm.create_task(
            tenant_id="t1",
            intent="long task",
            required_capabilities=["code_generation"],
        )
        dispatcher.dispatch(task)
        tm.claim_task(task.task_id, "coder")

        gs = GracefulShutdown(reg, task_manager=tm)
        gs.shutdown("t1", "coder")
        assert task.status == TaskStatus.PENDING
        assert task.assigned_to == ""


# ---------------------------------------------------------------------------
# Message routing + Policy integration
# ---------------------------------------------------------------------------


class TestMessageRoutingIntegration:
    def _setup(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="sender")
        reg.register(tenant_id="t1", role="reviewer", agent_id="receiver")

        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-messages",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        policy_engine = PlatformPolicyEngine(store)
        audit = AuditStore()

        router = MessageRouter()
        router.add_middleware(AuthenticateMiddleware(reg))
        router.add_middleware(PolicyCheckMiddleware(policy_engine))
        router.add_middleware(ContentFilterMiddleware(policy_engine))
        router.add_middleware(AuditLogMiddleware(audit))
        router.add_middleware(CircuitBreaker(threshold=100))

        return reg, router, audit, policy_engine

    def test_normal_message_flow(self):
        _, router, audit, _ = self._setup()
        msg = Message(
            source_agent="sender",
            target_agent="receiver",
            intent="review",
            payload={"text": "Please review this code"},
            tenant_id="t1",
        )
        result = router.send(msg)
        assert result is not None
        assert audit.entry_count == 1
        inbox = router.get_inbox("receiver")
        assert len(inbox) == 1

    def test_unauth_message_blocked(self):
        _, router, audit, _ = self._setup()
        msg = Message(
            source_agent="hacker",
            target_agent="receiver",
            intent="attack",
            tenant_id="t1",
        )
        result = router.send(msg)
        assert result is None
        assert audit.entry_count == 0

    def test_content_filtered(self):
        _, router, _, _ = self._setup()
        msg = Message(
            source_agent="sender",
            target_agent="receiver",
            intent="response",
            payload={"text": "Here: <thinking>secret plan</thinking> The answer."},
            tenant_id="t1",
        )
        result = router.send(msg)
        assert result is not None
        assert "<thinking>" not in result.payload["text"]

    def test_bidirectional_communication(self):
        _, router, _, _ = self._setup()
        router.send(Message(
            source_agent="sender",
            target_agent="receiver",
            intent="question",
            tenant_id="t1",
        ))
        router.send(Message(
            source_agent="receiver",
            target_agent="sender",
            intent="answer",
            tenant_id="t1",
        ))
        assert len(router.get_inbox("receiver")) == 1
        assert len(router.get_inbox("sender")) == 1


# ---------------------------------------------------------------------------
# Audit trail integration
# ---------------------------------------------------------------------------


class TestAuditTrailIntegration:
    def test_full_lifecycle_audit(self):
        reg = AgentRegistry()
        audit = AuditStore()

        # Register
        audit.log(agent_id="a1", tenant_id="t1", action="agent_registered")

        # Boot
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        csp = ColdStartProtocol(reg, audit_store=audit)
        csp.boot("t1", "a1")

        # Heartbeat check
        hm = HeartbeatManager(reg, timeout_seconds=30, audit_store=audit)
        hm.check_heartbeat("t1", "a1")

        # Shutdown
        gs = GracefulShutdown(reg, audit_store=audit)
        gs.shutdown("t1", "a1")

        entries = audit.query(agent_id="a1")
        assert len(entries) >= 3
        actions = [e.action for e in entries]
        assert "agent_registered" in actions
        assert "cold_start" in actions
        assert "graceful_shutdown" in actions

    def test_violation_tracking(self):
        audit = AuditStore()
        engine = PlatformPolicyEngine()

        # Simulate violations
        for i in range(5):
            request = AuthorizationRequest(
                principal_type="Agent",
                principal_id=f"a{i}",
                action="read",
                resource_type="File",
                resource_id="data.csv",
                context={"agent_state": "boot"},
            )
            decision = engine.evaluate(request)
            audit.log(
                agent_id=f"a{i}",
                tenant_id="t1",
                action="policy_violation",
                details={"reasons": decision.reasons},
                result="denied",
            )

        violations = audit.get_violations(tenant_id="t1")
        assert len(violations) == 5
        report = audit.generate_report(tenant_id="t1")
        assert report["violation_count"] == 5


# ---------------------------------------------------------------------------
# Policy engine + Registry integration
# ---------------------------------------------------------------------------


class TestPolicyRegistryIntegration:
    def test_agent_policies_with_registry(self):
        reg = AgentRegistry()
        reg.register(
            tenant_id="t1",
            role="developer",
            agent_id="a1",
            capabilities=[Capability(name="code", confidence=0.9)],
        )

        policies = create_agent_policies("developer")
        engine = PlatformPolicyEngine()
        for p in policies:
            engine.store.add_policy(p)

        # Developer can read with correct role context
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="main.py",
            context={"role": "developer", "agent_state": "ready"},
        )
        assert engine.evaluate(request).is_allowed

    def test_cross_tenant_denied(self):
        engine = PlatformPolicyEngine()
        store = engine.store
        store.add_policy(Policy(
            policy_id="allow-read",
            effect=Effect.PERMIT,
            action="read",
        ))

        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="data.csv",
            context={
                "tenant_id": "t1",
                "resource_tenant_id": "t2",
                "agent_state": "ready",
            },
        )
        assert not engine.evaluate(request).is_allowed


# ---------------------------------------------------------------------------
# Multi-tenant integration
# ---------------------------------------------------------------------------


class TestMultiTenantIntegration:
    def test_tenant_isolation(self):
        reg = AgentRegistry()

        # Register agents in different tenants
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t2", role="dev", agent_id="a2")

        assert len(reg.list_agents(tenant_id="t1")) == 1
        assert len(reg.list_agents(tenant_id="t2")) == 1
        assert reg.get("t1", "a2") is None
        assert reg.get("t2", "a1") is None

    def test_tenant_isolated_tasks(self):
        tm = TaskManager()
        tm.create_task(tenant_id="t1", intent="task-1")
        tm.create_task(tenant_id="t2", intent="task-2")
        assert len(tm.list_tasks(tenant_id="t1")) == 1
        assert len(tm.list_tasks(tenant_id="t2")) == 1

    def test_tenant_isolated_audit(self):
        audit = AuditStore()
        audit.log(tenant_id="t1", action="read")
        audit.log(tenant_id="t2", action="write")
        assert len(audit.query(tenant_id="t1")) == 1
        assert len(audit.query(tenant_id="t2")) == 1


# ---------------------------------------------------------------------------
# End-to-end workflow
# ---------------------------------------------------------------------------


class TestEndToEndWorkflow:
    def test_full_agent_workflow(self):
        """Test complete workflow: register → boot → dispatch → execute → shutdown."""
        # Setup
        reg = AgentRegistry()
        tm = TaskManager()
        audit = AuditStore()

        # Register agent
        reg.register(
            tenant_id="t1",
            role="developer",
            agent_id="dev-1",
            capabilities=[Capability(name="code_generation", confidence=0.9)],
        )
        audit.log(agent_id="dev-1", tenant_id="t1", action="agent_registered")

        # Boot
        csp = ColdStartProtocol(reg, audit_store=audit)
        assert csp.boot("t1", "dev-1") is True

        # Create and dispatch task
        task = tm.create_task(
            tenant_id="t1",
            intent="implement feature",
            required_capabilities=["code_generation"],
            priority=5,
        )
        dispatcher = TaskDispatcher(tm, reg)
        dispatcher.dispatch(task)
        assert task.assigned_to == "dev-1"

        # Claim and complete
        tm.claim_task(task.task_id, "dev-1")
        tm.update_status(task.task_id, TaskStatus.IN_PROGRESS)
        tm.update_status(task.task_id, TaskStatus.COMPLETED, {"files_changed": 3})

        # Verify
        assert task.status == TaskStatus.COMPLETED
        assert task.result["files_changed"] == 3

        # Shutdown
        gs = GracefulShutdown(reg, task_manager=tm, audit_store=audit)
        gs.shutdown("t1", "dev-1")
        assert reg.get("t1", "dev-1") is None

        # Audit trail
        report = audit.generate_report(tenant_id="t1")
        assert report["total_entries"] >= 3

    def test_multi_agent_collaboration(self):
        """Test multiple agents working together via tasks and messages."""
        reg = AgentRegistry()
        tm = TaskManager()
        csp = ColdStartProtocol(reg)

        # Register agents
        reg.register(
            tenant_id="t1",
            role="developer",
            agent_id="coder",
            capabilities=[Capability(name="code_generation", confidence=0.9)],
        )
        reg.register(
            tenant_id="t1",
            role="reviewer",
            agent_id="reviewer",
            capabilities=[Capability(name="code_review", confidence=0.95)],
        )
        csp.boot("t1", "coder")
        csp.boot("t1", "reviewer")

        # Set up messaging
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-messages",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        policy_engine = PlatformPolicyEngine(store)
        router = MessageRouter()
        router.add_middleware(AuthenticateMiddleware(reg))
        router.add_middleware(PolicyCheckMiddleware(policy_engine))

        # Coder creates task, reviewer reviews
        code_task = tm.create_task(
            tenant_id="t1",
            intent="write feature",
            required_capabilities=["code_generation"],
        )
        dispatcher = TaskDispatcher(tm, reg)
        dispatcher.dispatch(code_task)
        tm.claim_task(code_task.task_id, "coder")
        tm.update_status(code_task.task_id, TaskStatus.COMPLETED)

        # Coder sends message to reviewer
        msg = Message(
            source_agent="coder",
            target_agent="reviewer",
            intent="review_request",
            payload={"text": "Please review my code"},
            tenant_id="t1",
        )
        result = router.send(msg)
        assert result is not None
        assert len(router.get_inbox("reviewer")) == 1

        # Reviewer creates review task
        review_task = tm.create_task(
            tenant_id="t1",
            intent="review code",
            required_capabilities=["code_review"],
            source_agent="coder",
        )
        dispatcher.dispatch(review_task)
        assert review_task.assigned_to == "reviewer"

    def test_task_failure_and_retry(self):
        """Test task failure with retry and eventual success."""
        reg = AgentRegistry()
        tm = TaskManager()
        csp = ColdStartProtocol(reg)

        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="worker",
            capabilities=[Capability(name="deploy", confidence=0.8)],
        )
        csp.boot("t1", "worker")

        task = tm.create_task(
            tenant_id="t1",
            intent="deploy to prod",
            required_capabilities=["deploy"],
            max_retries=3,
        )
        dispatcher = TaskDispatcher(tm, reg)
        dispatcher.dispatch(task)

        # First attempt fails
        tm.claim_task(task.task_id, "worker")
        result = tm.retry_or_fail(task.task_id, "connection timeout")
        assert result.status == TaskStatus.PENDING
        assert result.retry_count == 1

        # Re-dispatch and succeed
        dispatcher.dispatch(result)
        tm.claim_task(task.task_id, "worker")
        tm.update_status(task.task_id, TaskStatus.COMPLETED, {"deployed": True})
        assert task.status == TaskStatus.COMPLETED

    def test_circuit_breaker_in_pipeline(self):
        """Test circuit breaker triggers in full pipeline."""
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t1", role="dev", agent_id="a2")

        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-all",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        engine = PlatformPolicyEngine(store)

        router = MessageRouter()
        router.add_middleware(AuthenticateMiddleware(reg))
        router.add_middleware(PolicyCheckMiddleware(engine))
        cb = CircuitBreaker(threshold=5, window_seconds=300)
        router.add_middleware(cb)

        for i in range(5):
            msg = Message(
                source_agent="a1", target_agent="a2", intent=f"msg-{i}", tenant_id="t1"
            )
            result = router.send(msg)
            assert result is not None

        # 6th message should be blocked
        msg = Message(
            source_agent="a1", target_agent="a2", intent="overflow", tenant_id="t1"
        )
        result = router.send(msg)
        assert result is None

    def test_expired_claim_redispatch(self):
        """Test expired claims get released and redispatched."""
        reg = AgentRegistry()
        tm = TaskManager()
        csp = ColdStartProtocol(reg)

        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="fast",
            capabilities=[Capability(name="code", confidence=0.9)],
        )
        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="slow",
            capabilities=[Capability(name="code", confidence=0.7)],
        )
        csp.boot("t1", "fast")
        csp.boot("t1", "slow")

        task = tm.create_task(
            tenant_id="t1",
            intent="write code",
            required_capabilities=["code"],
        )
        dispatcher = TaskDispatcher(tm, reg)
        dispatcher.dispatch(task)
        tm.claim_task(task.task_id, task.assigned_to)

        # Simulate expired claim
        task.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        released = tm.release_expired_claims(lease_minutes=5)
        assert len(released) == 1

        # Re-dispatch
        dispatcher.dispatch(task)
        assert task.status == TaskStatus.ASSIGNED


# ---------------------------------------------------------------------------
# Control plane __init__ import tests
# ---------------------------------------------------------------------------


class TestControlPlaneImports:
    def test_import_all(self):
        import platform_agent.plato.control_plane as cp
        assert hasattr(cp, "AgentRecord")
        assert hasattr(cp, "AgentRegistry")
        assert hasattr(cp, "PlatformPolicyEngine")
        assert hasattr(cp, "Task")
        assert hasattr(cp, "TaskManager")
        assert hasattr(cp, "TaskDispatcher")
        assert hasattr(cp, "Message")
        assert hasattr(cp, "MessageRouter")
        assert hasattr(cp, "ColdStartProtocol")
        assert hasattr(cp, "HeartbeatManager")
        assert hasattr(cp, "GracefulShutdown")
        assert hasattr(cp, "AuditEntry")
        assert hasattr(cp, "AuditStore")
