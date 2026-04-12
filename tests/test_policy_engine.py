"""Tests for Platform Policy Engine."""

from __future__ import annotations

from platform_agent.plato.control_plane.policy_engine import (
    PlatformPolicyEngine,
    RateLimitConfig,
    THINKING_LEAK_PATTERNS,
    create_agent_policies,
)
from platform_agent.foundation.guardrails import (
    AuthorizationRequest,
    Effect,
    Policy,
    PolicyStore,
)


# ---------------------------------------------------------------------------
# PlatformPolicyEngine — cold start denial
# ---------------------------------------------------------------------------


class TestColdStartDenial:
    def test_deny_boot_state(self):
        engine = PlatformPolicyEngine()
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="main.py",
            context={"agent_state": "boot"},
        )
        decision = engine.evaluate(request)
        assert not decision.is_allowed
        assert "cold_start_deny" in decision.matching_policies[0]

    def test_deny_initializing_state(self):
        engine = PlatformPolicyEngine()
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="main.py",
            context={"agent_state": "initializing"},
        )
        decision = engine.evaluate(request)
        assert not decision.is_allowed

    def test_allow_ready_state(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-read",
            effect=Effect.PERMIT,
            action="read",
        ))
        engine = PlatformPolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="main.py",
            context={"agent_state": "ready"},
        )
        decision = engine.evaluate(request)
        assert decision.is_allowed

    def test_no_state_context_falls_through(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-read",
            effect=Effect.PERMIT,
            action="read",
        ))
        engine = PlatformPolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="main.py",
        )
        decision = engine.evaluate(request)
        assert decision.is_allowed

    def test_deny_degraded_state(self):
        engine = PlatformPolicyEngine()
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="main.py",
            context={"agent_state": "degraded"},
        )
        decision = engine.evaluate(request)
        assert not decision.is_allowed


# ---------------------------------------------------------------------------
# PlatformPolicyEngine — cross-boundary denial
# ---------------------------------------------------------------------------


class TestCrossBoundaryDenial:
    def test_deny_cross_tenant(self):
        engine = PlatformPolicyEngine()
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="data.csv",
            context={
                "tenant_id": "tenant-a",
                "resource_tenant_id": "tenant-b",
            },
        )
        decision = engine.evaluate(request)
        assert not decision.is_allowed
        assert "cross_boundary_deny" in decision.matching_policies[0]

    def test_allow_same_tenant(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-read",
            effect=Effect.PERMIT,
            action="read",
        ))
        engine = PlatformPolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="data.csv",
            context={
                "tenant_id": "tenant-a",
                "resource_tenant_id": "tenant-a",
            },
        )
        decision = engine.evaluate(request)
        assert decision.is_allowed

    def test_no_tenant_context_falls_through(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-read",
            effect=Effect.PERMIT,
            action="read",
        ))
        engine = PlatformPolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="data.csv",
        )
        decision = engine.evaluate(request)
        assert decision.is_allowed


# ---------------------------------------------------------------------------
# PlatformPolicyEngine — rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_within_limit(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-all",
            effect=Effect.PERMIT,
            action="*",
        ))
        engine = PlatformPolicyEngine(store)
        engine.set_rate_limit("a1", RateLimitConfig(max_requests=5, window_seconds=60))

        for _ in range(5):
            request = AuthorizationRequest(
                principal_type="Agent",
                principal_id="a1",
                action="read",
                resource_type="File",
                resource_id="main.py",
            )
            decision = engine.evaluate(request)
            assert decision.is_allowed

    def test_exceed_limit(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-all",
            effect=Effect.PERMIT,
            action="*",
        ))
        engine = PlatformPolicyEngine(store)
        engine.set_rate_limit("a1", RateLimitConfig(max_requests=2, window_seconds=60))

        for _ in range(2):
            request = AuthorizationRequest(
                principal_type="Agent",
                principal_id="a1",
                action="read",
                resource_type="File",
                resource_id="main.py",
            )
            engine.evaluate(request)

        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="main.py",
        )
        decision = engine.evaluate(request)
        assert not decision.is_allowed
        assert "rate_limit" in decision.matching_policies[0]

    def test_no_rate_limit_configured(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-all",
            effect=Effect.PERMIT,
            action="*",
        ))
        engine = PlatformPolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="main.py",
        )
        decision = engine.evaluate(request)
        assert decision.is_allowed

    def test_rate_limit_custom_key(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-all",
            effect=Effect.PERMIT,
            action="*",
        ))
        engine = PlatformPolicyEngine(store)
        engine.set_rate_limit("custom-key", RateLimitConfig(max_requests=1, window_seconds=60))

        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="a1",
            action="read",
            resource_type="File",
            resource_id="main.py",
            context={"rate_limit_key": "custom-key"},
        )
        engine.evaluate(request)

        decision = engine.evaluate(request)
        assert not decision.is_allowed


# ---------------------------------------------------------------------------
# PlatformPolicyEngine — store access
# ---------------------------------------------------------------------------


class TestPlatformPolicyEngineStore:
    def test_default_store(self):
        engine = PlatformPolicyEngine()
        assert engine.store is not None
        assert engine.store.policy_count == 0

    def test_custom_store(self):
        store = PolicyStore()
        store.add_policy(Policy(policy_id="p1", effect=Effect.PERMIT))
        engine = PlatformPolicyEngine(store)
        assert engine.store.policy_count == 1


# ---------------------------------------------------------------------------
# Content filtering
# ---------------------------------------------------------------------------


class TestContentFilter:
    def test_clean_text(self):
        engine = PlatformPolicyEngine()
        result = engine.check_content("Hello, this is a normal response.")
        assert result.is_clean
        assert result.filtered_text == "Hello, this is a normal response."
        assert result.patterns_found == []

    def test_filter_thinking_tags(self):
        engine = PlatformPolicyEngine()
        text = "Here is the answer. <thinking>internal reasoning</thinking> The result is 42."
        result = engine.check_content(text)
        assert not result.is_clean
        assert "<thinking>" not in result.filtered_text
        assert "42" in result.filtered_text

    def test_filter_reasoning_tags(self):
        engine = PlatformPolicyEngine()
        text = "Response. <reasoning>my reasoning here</reasoning> Done."
        result = engine.check_content(text)
        assert not result.is_clean
        assert "<reasoning>" not in result.filtered_text

    def test_filter_internal_tags(self):
        engine = PlatformPolicyEngine()
        text = "Output: <internal>secret stuff</internal> visible."
        result = engine.check_content(text)
        assert not result.is_clean
        assert "<internal>" not in result.filtered_text

    def test_filter_internal_brackets(self):
        engine = PlatformPolicyEngine()
        text = "[INTERNAL]hidden reasoning[/INTERNAL] visible text"
        result = engine.check_content(text)
        assert not result.is_clean
        assert "[INTERNAL]" not in result.filtered_text

    def test_filter_thinking_prefix(self):
        engine = PlatformPolicyEngine()
        text = "let me think about this\nThe answer is 42."
        result = engine.check_content(text)
        assert not result.is_clean

    def test_multiple_patterns(self):
        engine = PlatformPolicyEngine()
        text = "<thinking>thought</thinking> Hello <reasoning>reason</reasoning>"
        result = engine.check_content(text)
        assert not result.is_clean
        assert len(result.patterns_found) == 2

    def test_patterns_list(self):
        assert len(THINKING_LEAK_PATTERNS) >= 5


# ---------------------------------------------------------------------------
# create_agent_policies
# ---------------------------------------------------------------------------


class TestCreateAgentPolicies:
    def test_developer_policies(self):
        policies = create_agent_policies("developer")
        ids = [p.policy_id for p in policies]
        assert "developer:read-files" in ids
        assert "developer:send-messages" in ids
        assert "developer:write-project" in ids
        assert "developer:deny-secrets" in ids

    def test_reviewer_policies(self):
        policies = create_agent_policies("reviewer")
        ids = [p.policy_id for p in policies]
        assert "reviewer:read-files" in ids
        assert "reviewer:review-code" in ids
        assert "reviewer:deny-secrets" in ids

    def test_admin_policies(self):
        policies = create_agent_policies("admin")
        ids = [p.policy_id for p in policies]
        assert "admin:manage-agents" in ids
        assert "admin:manage-policies" in ids
        assert "admin:write-project" in ids

    def test_monitor_policies(self):
        policies = create_agent_policies("monitor")
        ids = [p.policy_id for p in policies]
        assert "monitor:read-metrics" in ids
        assert "monitor:read-audit" in ids

    def test_all_roles_get_deny_secrets(self):
        for role in ("developer", "reviewer", "admin", "monitor"):
            policies = create_agent_policies(role)
            ids = [p.policy_id for p in policies]
            assert f"{role}:deny-secrets" in ids

    def test_all_roles_get_read_files(self):
        for role in ("developer", "reviewer", "admin", "monitor"):
            policies = create_agent_policies(role)
            ids = [p.policy_id for p in policies]
            assert f"{role}:read-files" in ids

    def test_unknown_role_gets_basics(self):
        policies = create_agent_policies("unknown")
        ids = [p.policy_id for p in policies]
        assert "unknown:read-files" in ids
        assert "unknown:send-messages" in ids
        assert "unknown:deny-secrets" in ids
        # Should not have admin/developer extras
        assert "unknown:write-project" not in ids
        assert "unknown:manage-agents" not in ids

    def test_policies_have_conditions(self):
        policies = create_agent_policies("developer")
        for p in policies:
            assert p.conditions.get("role") == "developer"

    def test_deny_policies_are_forbid(self):
        policies = create_agent_policies("developer")
        deny_policies = [p for p in policies if "deny" in p.policy_id]
        for p in deny_policies:
            assert p.effect == Effect.FORBID
