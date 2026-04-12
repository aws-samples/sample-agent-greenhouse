"""Tests for MemoryAccessGuard — cross-user memory protection."""

from __future__ import annotations

import pytest

from platform_agent.foundation.memory_access_guard import (
    MemoryAccessGuard,
    MemoryAccessViolation,
    validate_namespace,
)


class TestMemoryAccessGuard:
    """Test MemoryAccessGuard — namespace validation and access control."""

    def test_guard_initializes_with_strict_mode(self):
        guard = MemoryAccessGuard(strict_mode=True)
        assert guard.strict_mode is True

        guard = MemoryAccessGuard(strict_mode=False)
        assert guard.strict_mode is False

    def test_guard_default_strict_mode(self):
        guard = MemoryAccessGuard()
        assert guard.strict_mode is True  # Should default to True

    def test_validate_namespace_allows_user_owned_namespace(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # User's own namespace should be allowed
        assert guard.validate_namespace("user123/session456", "user123") is True
        assert guard.validate_namespace("user456/memories", "user456") is True

    def test_validate_namespace_allows_template_placeholders(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Template placeholders should be allowed
        assert guard.validate_namespace("{actorId}/session", "user123") is True
        assert guard.validate_namespace("memories/{actor_id}/data", "user456") is True

    def test_validate_namespace_allows_shared_namespaces(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Shared and public namespaces should be allowed
        assert guard.validate_namespace("shared/common", "user123") is True
        assert guard.validate_namespace("public/announcements", "user456") is True

    def test_validate_namespace_blocks_root_namespace(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Root namespace should be blocked
        assert guard.validate_namespace("/", "user123") is False

    def test_validate_namespace_blocks_empty_namespace(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Empty namespace should be blocked
        assert guard.validate_namespace("", "user123") is False

    def test_validate_namespace_blocks_cross_user_access(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Cross-user access should be blocked
        assert guard.validate_namespace("user789/private", "user123") is False
        assert guard.validate_namespace("other_user/data", "current_user") is False

    def test_validate_namespace_requires_actor_id(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Missing actor_id should be blocked
        assert guard.validate_namespace("user123/session", "") is False
        assert guard.validate_namespace("some/namespace", None) is False

    def test_strict_mode_raises_exceptions(self):
        guard = MemoryAccessGuard(strict_mode=True)

        # Root namespace should raise exception in strict mode
        with pytest.raises(MemoryAccessViolation) as exc_info:
            guard.validate_namespace("/", "user123")
        assert "Root namespace" in str(exc_info.value)

        # Cross-user access should raise exception
        with pytest.raises(MemoryAccessViolation) as exc_info:
            guard.validate_namespace("other_user/data", "current_user")
        assert "Cross-user access denied" in str(exc_info.value)

    def test_non_strict_mode_logs_warnings(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Should return False but not raise exceptions
        result = guard.validate_namespace("/", "user123")
        assert result is False

        result = guard.validate_namespace("other_user/data", "current_user")
        assert result is False

    def test_validate_retrieval_request_full_validation(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Valid retrieval request
        assert guard.validate_retrieval_request(
            namespace="user123/session456",
            actor_id="user123",
            query="search for memories",
            metadata={"source": "chat"}
        ) is True

        # Invalid retrieval request
        assert guard.validate_retrieval_request(
            namespace="/",  # Root namespace
            actor_id="user123",
            query="search all users"
        ) is False

    def test_validate_retrieval_request_with_strict_mode(self):
        guard = MemoryAccessGuard(strict_mode=True)

        # Invalid request should raise exception
        with pytest.raises(MemoryAccessViolation):
            guard.validate_retrieval_request(
                namespace="other_user/private",
                actor_id="current_user",
                query="try to access other user data"
            )

    def test_get_security_summary(self):
        guard = MemoryAccessGuard(strict_mode=True)
        summary = guard.get_security_summary()

        assert summary["strict_mode"] is True
        assert "rules" in summary
        assert len(summary["rules"]) > 0
        assert any("actor_id" in rule for rule in summary["rules"])

    def test_convenience_function_validate_namespace(self):
        # Test the standalone convenience function
        assert validate_namespace("user123/session", "user123") is True
        assert validate_namespace("/", "user123") is False
        assert validate_namespace("other_user/data", "user123") is False

    def test_edge_cases_and_boundary_conditions(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Test with whitespace
        assert guard.validate_namespace("  ", "user123") is False
        assert guard.validate_namespace("user123/session", "  user123  ") is False

        # Test with very long strings
        long_user_id = "user" + "x" * 1000
        long_namespace = long_user_id + "/session"
        assert guard.validate_namespace(long_namespace, long_user_id) is True

        # Test with special characters in user ID
        special_user = "user@domain.com"
        namespace_with_special = f"{special_user}/memories"
        assert guard.validate_namespace(namespace_with_special, special_user) is True

    def test_namespace_partial_matches_rejected(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Partial matches should be rejected to prevent bypass attempts
        assert guard.validate_namespace("user1/data", "user123") is False
        assert guard.validate_namespace("user123x/data", "user123") is False
        assert guard.validate_namespace("xuser123/data", "user123") is False

        # But exact matches should work
        assert guard.validate_namespace("user123/data", "user123") is True

    def test_case_sensitive_validation(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Case sensitivity should be preserved
        assert guard.validate_namespace("User123/session", "user123") is False
        assert guard.validate_namespace("user123/session", "User123") is False
        assert guard.validate_namespace("user123/session", "user123") is True

    def test_various_template_formats(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Different template formats should work
        template_namespaces = [
            "{actorId}/session",
            "memories/{actorId}",
            "{actorId}/data/{actorId}",  # Multiple occurrences
            "{actor_id}/session",
            "data/{actor_id}/memories",
        ]

        for namespace in template_namespaces:
            assert guard.validate_namespace(namespace, "user123") is True

    def test_shared_namespace_variations(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Various shared namespace patterns
        shared_namespaces = [
            "shared/",
            "shared/common",
            "shared/team/project",
            "public/",
            "public/announcements",
            "public/docs/help",
        ]

        for namespace in shared_namespaces:
            assert guard.validate_namespace(namespace, "any_user") is True

    def test_memory_access_violation_exception(self):
        guard = MemoryAccessGuard(strict_mode=True)

        try:
            guard.validate_namespace("forbidden/namespace", "user123")
            assert False, "Should have raised MemoryAccessViolation"
        except MemoryAccessViolation as e:
            assert "Memory access violation" in str(e)
            assert "forbidden/namespace" in str(e) or "Cross-user access denied" in str(e)

    def test_validate_retrieval_config_filters_unsafe_namespaces(self):
        guard = MemoryAccessGuard(strict_mode=False)

        config = {
            "namespaces": [
                "user123/session",  # safe
                "/",                # unsafe (root)
                "other_user/data",  # unsafe (cross-user)
                "shared/common",    # safe
            ],
            "query": "search memories",
        }

        filtered = guard.validate_retrieval_config(config, "user123")

        assert filtered["namespaces"] == ["user123/session", "shared/common"]
        assert filtered["query"] == "search memories"  # non-namespace fields untouched

    def test_validate_retrieval_config_filters_single_namespace(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # Unsafe single namespace should be cleared
        config = {"namespace": "/", "limit": 10}
        filtered = guard.validate_retrieval_config(config, "user123")
        assert filtered["namespace"] == ""
        assert filtered["limit"] == 10

        # Safe single namespace should be preserved
        config = {"namespace": "user123/memories", "limit": 10}
        filtered = guard.validate_retrieval_config(config, "user123")
        assert filtered["namespace"] == "user123/memories"

    def test_validate_retrieval_config_all_unsafe_returns_empty_list(self):
        guard = MemoryAccessGuard(strict_mode=False)

        config = {"namespaces": ["/", "other/data", ""]}
        filtered = guard.validate_retrieval_config(config, "user123")
        assert filtered["namespaces"] == []

    def test_validate_retrieval_config_empty_config(self):
        guard = MemoryAccessGuard(strict_mode=False)

        # No namespace fields — returned unchanged
        config = {"query": "test", "limit": 5}
        filtered = guard.validate_retrieval_config(config, "user123")
        assert filtered == config

    def test_complex_security_scenarios(self):
        """Test complex real-world security scenarios."""
        guard = MemoryAccessGuard(strict_mode=False)

        # Scenario 1: Multi-tenant application
        tenant_a_user = "tenant_a_user123"
        tenant_b_user = "tenant_b_user456"

        # Users should access their own tenant data
        assert guard.validate_namespace(f"{tenant_a_user}/private", tenant_a_user) is True
        assert guard.validate_namespace(f"{tenant_b_user}/private", tenant_b_user) is True

        # Users should NOT access other tenant data
        assert guard.validate_namespace(f"{tenant_a_user}/private", tenant_b_user) is False
        assert guard.validate_namespace(f"{tenant_b_user}/private", tenant_a_user) is False

        # Scenario 2: Hierarchical permissions
        admin_user = "admin_user"
        regular_user = "regular_user"

        # Regular user can't access admin namespace (even if they try to be clever)
        assert guard.validate_namespace("admin_user/settings", regular_user) is False

        # Scenario 3: Attempt to bypass with path traversal
        malicious_user = "hacker"
        malicious_namespaces = [
            "../other_user/data",
            "user123/../admin/secrets",
            "shared/../private_user/data",  # Path traversal should be blocked
        ]

        # These should all be blocked (they don't contain the actor_id and/or have path traversal)
        for namespace in malicious_namespaces:
            result = guard.validate_namespace(namespace, malicious_user)
            assert result is False, f"Malicious namespace '{namespace}' should be blocked"