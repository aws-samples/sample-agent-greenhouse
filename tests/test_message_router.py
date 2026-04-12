"""Tests for Message Router and middleware."""

from __future__ import annotations

from platform_agent.plato.control_plane.message_router import (
    AuditLogMiddleware,
    AuthenticateMiddleware,
    CircuitBreaker,
    ContentFilterMiddleware,
    Message,
    MessageRouter,
    PolicyCheckMiddleware,
)
from platform_agent.plato.control_plane.registry import AgentRegistry
from platform_agent.plato.control_plane.policy_engine import PlatformPolicyEngine
from platform_agent.plato.control_plane.audit import AuditStore
from platform_agent.foundation.guardrails import Effect, Policy, PolicyStore


# ---------------------------------------------------------------------------
# Message dataclass tests
# ---------------------------------------------------------------------------


class TestMessage:
    def test_create_defaults(self):
        msg = Message()
        assert msg.message_id is not None
        assert msg.source_agent == ""
        assert msg.target_agent == ""
        assert msg.intent == ""
        assert msg.payload == {}
        assert msg.timestamp is not None
        assert msg.metadata == {}

    def test_create_with_values(self):
        msg = Message(
            source_agent="a1",
            target_agent="a2",
            intent="greet",
            payload={"text": "hello"},
            tenant_id="t1",
        )
        assert msg.source_agent == "a1"
        assert msg.target_agent == "a2"
        assert msg.intent == "greet"
        assert msg.payload == {"text": "hello"}
        assert msg.tenant_id == "t1"

    def test_to_dict(self):
        msg = Message(
            message_id="m1",
            source_agent="a1",
            target_agent="a2",
            intent="greet",
            tenant_id="t1",
        )
        d = msg.to_dict()
        assert d["message_id"] == "m1"
        assert d["source_agent"] == "a1"
        assert d["target_agent"] == "a2"
        assert d["intent"] == "greet"
        assert d["tenant_id"] == "t1"

    def test_to_dict_includes_metadata(self):
        msg = Message(metadata={"key": "value"})
        d = msg.to_dict()
        assert d["metadata"] == {"key": "value"}

    def test_unique_message_ids(self):
        m1 = Message()
        m2 = Message()
        assert m1.message_id != m2.message_id


# ---------------------------------------------------------------------------
# AuthenticateMiddleware tests
# ---------------------------------------------------------------------------


class TestAuthenticateMiddleware:
    def _make_registry(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        return reg

    def test_allow_registered_agent(self):
        reg = self._make_registry()
        mw = AuthenticateMiddleware(reg)
        msg = Message(source_agent="a1", target_agent="a2", tenant_id="t1")
        result = mw.process(msg)
        assert result is not None

    def test_deny_unregistered_agent(self):
        reg = self._make_registry()
        mw = AuthenticateMiddleware(reg)
        msg = Message(source_agent="unknown", target_agent="a1", tenant_id="t1")
        result = mw.process(msg)
        assert result is None

    def test_deny_no_source(self):
        reg = self._make_registry()
        mw = AuthenticateMiddleware(reg)
        msg = Message(target_agent="a1", tenant_id="t1")
        result = mw.process(msg)
        assert result is None

    def test_deny_wrong_tenant(self):
        reg = self._make_registry()
        mw = AuthenticateMiddleware(reg)
        msg = Message(source_agent="a1", target_agent="a2", tenant_id="t2")
        result = mw.process(msg)
        assert result is None

    def test_allow_with_multiple_agents(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t1", role="reviewer", agent_id="a2")
        mw = AuthenticateMiddleware(reg)
        msg = Message(source_agent="a2", target_agent="a1", tenant_id="t1")
        result = mw.process(msg)
        assert result is not None


# ---------------------------------------------------------------------------
# PolicyCheckMiddleware tests
# ---------------------------------------------------------------------------


class TestPolicyCheckMiddleware:
    def test_allow_with_permit_policy(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-messages",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        engine = PlatformPolicyEngine(store)
        mw = PolicyCheckMiddleware(engine)
        msg = Message(source_agent="a1", target_agent="a2", tenant_id="t1")
        result = mw.process(msg)
        assert result is not None

    def test_deny_without_policy(self):
        engine = PlatformPolicyEngine()
        mw = PolicyCheckMiddleware(engine)
        msg = Message(source_agent="a1", target_agent="a2", tenant_id="t1")
        result = mw.process(msg)
        assert result is None

    def test_deny_with_forbid_policy(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-messages",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        store.add_policy(Policy(
            policy_id="deny-a1",
            effect=Effect.FORBID,
            principal_type="Agent",
            principal_id="a1",
            action="send_message",
        ))
        engine = PlatformPolicyEngine(store)
        mw = PolicyCheckMiddleware(engine)
        msg = Message(source_agent="a1", target_agent="a2", tenant_id="t1")
        result = mw.process(msg)
        assert result is None


# ---------------------------------------------------------------------------
# ContentFilterMiddleware tests
# ---------------------------------------------------------------------------


class TestContentFilterMiddleware:
    def test_clean_content_passes(self):
        engine = PlatformPolicyEngine()
        mw = ContentFilterMiddleware(engine)
        msg = Message(payload={"text": "Hello world"})
        result = mw.process(msg)
        assert result is not None
        assert result.payload["text"] == "Hello world"

    def test_filter_thinking_tags(self):
        engine = PlatformPolicyEngine()
        mw = ContentFilterMiddleware(engine)
        msg = Message(
            payload={"text": "Answer: <thinking>internal</thinking> 42"}
        )
        result = mw.process(msg)
        assert result is not None
        assert "<thinking>" not in result.payload["text"]
        assert result.metadata.get("content_filtered") is True

    def test_filter_content_field(self):
        engine = PlatformPolicyEngine()
        mw = ContentFilterMiddleware(engine)
        msg = Message(
            payload={"content": "Ok <reasoning>reason</reasoning> done"}
        )
        result = mw.process(msg)
        assert "<reasoning>" not in result.payload["content"]

    def test_filter_body_field(self):
        engine = PlatformPolicyEngine()
        mw = ContentFilterMiddleware(engine)
        msg = Message(
            payload={"body": "<internal>hidden</internal> visible"}
        )
        result = mw.process(msg)
        assert "<internal>" not in result.payload["body"]

    def test_filter_response_field(self):
        engine = PlatformPolicyEngine()
        mw = ContentFilterMiddleware(engine)
        msg = Message(
            payload={"response": "[INTERNAL]secret[/INTERNAL] output"}
        )
        result = mw.process(msg)
        assert "[INTERNAL]" not in result.payload["response"]

    def test_no_text_fields(self):
        engine = PlatformPolicyEngine()
        mw = ContentFilterMiddleware(engine)
        msg = Message(payload={"number": 42})
        result = mw.process(msg)
        assert result is not None

    def test_non_string_values_ignored(self):
        engine = PlatformPolicyEngine()
        mw = ContentFilterMiddleware(engine)
        msg = Message(payload={"text": 123, "content": ["a", "b"]})
        result = mw.process(msg)
        assert result is not None

    def test_empty_payload(self):
        engine = PlatformPolicyEngine()
        mw = ContentFilterMiddleware(engine)
        msg = Message()
        result = mw.process(msg)
        assert result is not None


# ---------------------------------------------------------------------------
# AuditLogMiddleware tests
# ---------------------------------------------------------------------------


class TestAuditLogMiddleware:
    def test_logs_message(self):
        audit = AuditStore()
        mw = AuditLogMiddleware(audit)
        msg = Message(
            message_id="m1",
            source_agent="a1",
            target_agent="a2",
            intent="greet",
            tenant_id="t1",
        )
        result = mw.process(msg)
        assert result is not None
        assert audit.entry_count == 1
        entries = audit.query(agent_id="a1")
        assert len(entries) == 1
        assert entries[0].action == "message_sent"
        assert entries[0].details["message_id"] == "m1"

    def test_logs_every_message(self):
        audit = AuditStore()
        mw = AuditLogMiddleware(audit)
        for i in range(5):
            mw.process(Message(source_agent=f"a{i}", tenant_id="t1"))
        assert audit.entry_count == 5


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_below_threshold(self):
        cb = CircuitBreaker(threshold=5, window_seconds=300)
        for _ in range(4):
            msg = Message(source_agent="a1", target_agent="a2")
            result = cb.process(msg)
            assert result is not None

    def test_at_threshold(self):
        cb = CircuitBreaker(threshold=3, window_seconds=300)
        for _ in range(3):
            cb.process(Message(source_agent="a1", target_agent="a2"))
        msg = Message(source_agent="a1", target_agent="a2")
        result = cb.process(msg)
        assert result is None

    def test_different_pairs_independent(self):
        cb = CircuitBreaker(threshold=2, window_seconds=300)
        for _ in range(2):
            cb.process(Message(source_agent="a1", target_agent="a2"))
        # Different pair should still work
        msg = Message(source_agent="a1", target_agent="a3")
        result = cb.process(msg)
        assert result is not None

    def test_reset(self):
        cb = CircuitBreaker(threshold=2, window_seconds=300)
        for _ in range(2):
            cb.process(Message(source_agent="a1", target_agent="a2"))
        assert cb.process(Message(source_agent="a1", target_agent="a2")) is None
        cb.reset("a1", "a2")
        result = cb.process(Message(source_agent="a1", target_agent="a2"))
        assert result is not None

    def test_get_count(self):
        cb = CircuitBreaker(threshold=10, window_seconds=300)
        assert cb.get_count("a1", "a2") == 0
        cb.process(Message(source_agent="a1", target_agent="a2"))
        cb.process(Message(source_agent="a1", target_agent="a2"))
        assert cb.get_count("a1", "a2") == 2

    def test_directional(self):
        cb = CircuitBreaker(threshold=2, window_seconds=300)
        cb.process(Message(source_agent="a1", target_agent="a2"))
        cb.process(Message(source_agent="a1", target_agent="a2"))
        # Reverse direction is a different pair
        result = cb.process(Message(source_agent="a2", target_agent="a1"))
        assert result is not None

    def test_get_count_nonexistent(self):
        cb = CircuitBreaker(threshold=10, window_seconds=300)
        assert cb.get_count("x", "y") == 0


# ---------------------------------------------------------------------------
# MessageRouter tests
# ---------------------------------------------------------------------------


class TestMessageRouterBasic:
    def test_send_no_middleware(self):
        router = MessageRouter()
        msg = Message(source_agent="a1", target_agent="a2")
        result = router.send(msg)
        assert result is not None
        assert router.delivered_count == 1

    def test_send_delivers_to_inbox(self):
        router = MessageRouter()
        msg = Message(source_agent="a1", target_agent="a2")
        router.send(msg)
        inbox = router.get_inbox("a2")
        assert len(inbox) == 1
        assert inbox[0].source_agent == "a1"

    def test_multiple_messages_to_inbox(self):
        router = MessageRouter()
        for i in range(3):
            router.send(Message(source_agent=f"a{i}", target_agent="target"))
        inbox = router.get_inbox("target")
        assert len(inbox) == 3

    def test_empty_inbox(self):
        router = MessageRouter()
        assert router.get_inbox("nobody") == []

    def test_clear_inbox(self):
        router = MessageRouter()
        router.send(Message(source_agent="a1", target_agent="a2"))
        router.send(Message(source_agent="a1", target_agent="a2"))
        count = router.clear_inbox("a2")
        assert count == 2
        assert router.get_inbox("a2") == []

    def test_clear_empty_inbox(self):
        router = MessageRouter()
        count = router.clear_inbox("nobody")
        assert count == 0

    def test_delivered_messages(self):
        router = MessageRouter()
        router.send(Message(source_agent="a1", target_agent="a2"))
        router.send(Message(source_agent="a3", target_agent="a4"))
        assert len(router.delivered_messages) == 2


class TestMessageRouterMiddleware:
    def test_middleware_can_block(self):
        router = MessageRouter()

        class BlockAll:
            def process(self, message):
                return None

        router.add_middleware(BlockAll())
        msg = Message(source_agent="a1", target_agent="a2")
        result = router.send(msg)
        assert result is None
        assert router.delivered_count == 0

    def test_middleware_can_modify(self):
        router = MessageRouter()

        class AddMetadata:
            def process(self, message):
                message.metadata["processed"] = True
                return message

        router.add_middleware(AddMetadata())
        msg = Message(source_agent="a1", target_agent="a2")
        result = router.send(msg)
        assert result.metadata["processed"] is True

    def test_middleware_chain_order(self):
        router = MessageRouter()
        order = []

        class MW1:
            def process(self, message):
                order.append("mw1")
                return message

        class MW2:
            def process(self, message):
                order.append("mw2")
                return message

        router.add_middleware(MW1())
        router.add_middleware(MW2())
        router.send(Message(source_agent="a1", target_agent="a2"))
        assert order == ["mw1", "mw2"]

    def test_middleware_chain_stops_on_block(self):
        router = MessageRouter()
        reached_second = False

        class BlockFirst:
            def process(self, message):
                return None

        class SecondMW:
            def process(self, message):
                nonlocal reached_second
                reached_second = True
                return message

        router.add_middleware(BlockFirst())
        router.add_middleware(SecondMW())
        router.send(Message(source_agent="a1", target_agent="a2"))
        assert not reached_second


class TestMessageRouterIntegration:
    def _make_router_with_auth(self):
        """Create a router with authentication middleware."""
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t1", role="reviewer", agent_id="a2")

        router = MessageRouter()
        router.add_middleware(AuthenticateMiddleware(reg))
        return router, reg

    def test_authenticated_message_delivered(self):
        router, _ = self._make_router_with_auth()
        msg = Message(source_agent="a1", target_agent="a2", tenant_id="t1")
        result = router.send(msg)
        assert result is not None
        assert router.delivered_count == 1

    def test_unauthenticated_message_blocked(self):
        router, _ = self._make_router_with_auth()
        msg = Message(source_agent="unknown", target_agent="a2", tenant_id="t1")
        result = router.send(msg)
        assert result is None
        assert router.delivered_count == 0

    def test_full_pipeline(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t1", role="reviewer", agent_id="a2")

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

        msg = Message(
            source_agent="a1",
            target_agent="a2",
            intent="review",
            payload={"text": "Please review <thinking>my thought</thinking> this code"},
            tenant_id="t1",
        )
        result = router.send(msg)
        assert result is not None
        assert "<thinking>" not in result.payload["text"]
        assert audit.entry_count == 1
        assert router.delivered_count == 1

    def test_full_pipeline_blocks_unauth(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")

        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-messages",
            effect=Effect.PERMIT,
            action="send_message",
        ))
        audit = AuditStore()

        router = MessageRouter()
        router.add_middleware(AuthenticateMiddleware(reg))
        router.add_middleware(AuditLogMiddleware(audit))

        msg = Message(source_agent="hacker", target_agent="a1", tenant_id="t1")
        result = router.send(msg)
        assert result is None
        assert audit.entry_count == 0  # Blocked before audit
