"""Tests for Cedar Policy Guardrails."""

from __future__ import annotations


from platform_agent.foundation.guardrails import (
    AuthorizationDecision,
    AuthorizationRequest,
    Decision,
    Effect,
    Policy,
    PolicyEngine,
    PolicyStore,
    create_default_policies,
)


# ---------------------------------------------------------------------------
# Policy tests
# ---------------------------------------------------------------------------


class TestPolicy:
    def test_create(self):
        policy = Policy(
            policy_id="test",
            effect=Effect.PERMIT,
            description="Test policy",
            action="read",
        )
        assert policy.policy_id == "test"
        assert policy.effect == Effect.PERMIT

    def test_matches_exact(self):
        policy = Policy(
            policy_id="p1",
            effect=Effect.PERMIT,
            principal_type="Agent",
            principal_id="design",
            action="read",
            resource_type="File",
            resource_id="main.py",
        )
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="design",
            action="read",
            resource_type="File",
            resource_id="main.py",
        )
        assert policy.matches(request)

    def test_matches_wildcard_principal(self):
        policy = Policy(
            policy_id="p1",
            effect=Effect.PERMIT,
            principal_type="Agent",
            principal_id="*",
            action="read",
        )
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="any-agent",
            action="read",
            resource_type="File",
            resource_id="test",
        )
        assert policy.matches(request)

    def test_matches_wildcard_action(self):
        policy = Policy(
            policy_id="p1",
            effect=Effect.PERMIT,
            action="*",
        )
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="write",
            resource_type="File",
            resource_id="test",
        )
        assert policy.matches(request)

    def test_matches_prefix_resource(self):
        policy = Policy(
            policy_id="p1",
            effect=Effect.PERMIT,
            resource_type="File",
            resource_id="project/*",
        )
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="write",
            resource_type="File",
            resource_id="project/src/main.py",
        )
        assert policy.matches(request)

    def test_no_match_wrong_action(self):
        policy = Policy(
            policy_id="p1",
            effect=Effect.PERMIT,
            action="read",
        )
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="write",
            resource_type="File",
            resource_id="test",
        )
        assert not policy.matches(request)

    def test_no_match_wrong_principal(self):
        policy = Policy(
            policy_id="p1",
            effect=Effect.PERMIT,
            principal_type="Agent",
            principal_id="design",
            action="read",
        )
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="other",
            action="read",
            resource_type="File",
            resource_id="test",
        )
        assert not policy.matches(request)

    def test_matches_with_conditions(self):
        policy = Policy(
            policy_id="p1",
            effect=Effect.PERMIT,
            action="write",
            conditions={"environment": "production"},
        )
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="write",
            resource_type="File",
            resource_id="test",
            context={"environment": "production"},
        )
        assert policy.matches(request)

    def test_no_match_wrong_condition(self):
        policy = Policy(
            policy_id="p1",
            effect=Effect.PERMIT,
            action="write",
            conditions={"environment": "production"},
        )
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="write",
            resource_type="File",
            resource_id="test",
            context={"environment": "staging"},
        )
        assert not policy.matches(request)

    def test_to_cedar(self):
        policy = Policy(
            policy_id="p1",
            effect=Effect.PERMIT,
            principal_type="Agent",
            principal_id="design",
            action="read",
            resource_type="File",
            resource_id="codebase",
        )
        cedar = policy.to_cedar()
        assert "permit(" in cedar
        assert 'Action::"read"' in cedar


# ---------------------------------------------------------------------------
# PolicyStore tests
# ---------------------------------------------------------------------------


class TestPolicyStore:
    def test_add_and_get(self):
        store = PolicyStore()
        policy = Policy(policy_id="p1", effect=Effect.PERMIT)
        store.add_policy(policy)
        assert store.get_policy("p1") is policy

    def test_remove(self):
        store = PolicyStore()
        store.add_policy(Policy(policy_id="p1", effect=Effect.PERMIT))
        assert store.remove_policy("p1") is True
        assert store.get_policy("p1") is None

    def test_remove_nonexistent(self):
        store = PolicyStore()
        assert store.remove_policy("nonexistent") is False

    def test_list_policies(self):
        store = PolicyStore()
        store.add_policy(Policy(policy_id="p1", effect=Effect.PERMIT))
        store.add_policy(Policy(policy_id="p2", effect=Effect.FORBID))
        assert store.policy_count == 2
        assert len(store.list_policies()) == 2


# ---------------------------------------------------------------------------
# PolicyEngine tests
# ---------------------------------------------------------------------------


class TestPolicyEngine:
    def test_default_deny(self):
        """No matching policies → deny."""
        store = PolicyStore()
        engine = PolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="read",
            resource_type="File",
            resource_id="test",
        )
        decision = engine.evaluate(request)
        assert not decision.is_allowed
        assert "default deny" in decision.reasons[0].lower()

    def test_permit(self):
        """Matching permit → allow."""
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-read",
            effect=Effect.PERMIT,
            action="read",
        ))
        engine = PolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="read",
            resource_type="File",
            resource_id="test",
        )
        decision = engine.evaluate(request)
        assert decision.is_allowed

    def test_forbid_overrides_permit(self):
        """Explicit forbid overrides permit (Cedar semantics)."""
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="allow-all",
            effect=Effect.PERMIT,
            action="*",
        ))
        store.add_policy(Policy(
            policy_id="deny-secrets",
            effect=Effect.FORBID,
            resource_type="File",
            resource_id="secrets/*",
        ))
        engine = PolicyEngine(store)

        # Regular read: allowed
        normal_request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="read",
            resource_type="File",
            resource_id="src/main.py",
        )
        assert engine.evaluate(normal_request).is_allowed

        # Secret read: denied
        secret_request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="read",
            resource_type="File",
            resource_id="secrets/api-key.txt",
        )
        decision = engine.evaluate(secret_request)
        assert not decision.is_allowed
        assert "deny-secrets" in decision.matching_policies

    def test_multiple_permits(self):
        store = PolicyStore()
        store.add_policy(Policy(
            policy_id="p1", effect=Effect.PERMIT, action="read",
        ))
        store.add_policy(Policy(
            policy_id="p2", effect=Effect.PERMIT, action="*",
        ))
        engine = PolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="read",
            resource_type="File",
            resource_id="test",
        )
        decision = engine.evaluate(request)
        assert decision.is_allowed
        assert len(decision.matching_policies) == 2


# ---------------------------------------------------------------------------
# Default policies tests
# ---------------------------------------------------------------------------


class TestDefaultPolicies:
    def test_create_default(self):
        store = create_default_policies()
        assert store.policy_count == 4

    def test_agents_can_read(self):
        store = create_default_policies()
        engine = PolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="design-advisor",
            action="read",
            resource_type="File",
            resource_id="src/main.py",
        )
        assert engine.evaluate(request).is_allowed

    def test_agents_can_write_project(self):
        store = create_default_policies()
        engine = PolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="scaffold",
            action="write",
            resource_type="File",
            resource_id="project/src/app.py",
        )
        assert engine.evaluate(request).is_allowed

    def test_agents_cannot_read_secrets(self):
        store = create_default_policies()
        engine = PolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="any-agent",
            action="read",
            resource_type="File",
            resource_id="secrets/api-key.txt",
        )
        assert not engine.evaluate(request).is_allowed

    def test_agents_cannot_rm(self):
        store = create_default_policies()
        engine = PolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="any-agent",
            action="execute",
            resource_type="Command",
            resource_id="rm",
        )
        assert not engine.evaluate(request).is_allowed

    def test_agents_cannot_write_outside_project(self):
        store = create_default_policies()
        engine = PolicyEngine(store)
        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id="test",
            action="write",
            resource_type="File",
            resource_id="/etc/passwd",
        )
        assert not engine.evaluate(request).is_allowed


# ---------------------------------------------------------------------------
# AuthorizationDecision tests
# ---------------------------------------------------------------------------


class TestAuthorizationDecision:
    def test_allow(self):
        d = AuthorizationDecision(decision=Decision.ALLOW)
        assert d.is_allowed

    def test_deny(self):
        d = AuthorizationDecision(decision=Decision.DENY)
        assert not d.is_allowed
