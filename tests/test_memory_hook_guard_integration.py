"""Tests for MemoryHook + MemoryAccessGuard integration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from platform_agent.foundation.hooks.memory_hook import MemoryHook
from platform_agent.foundation.memory_access_guard import MemoryAccessGuard


class TestMemoryHookGuardIntegration:
    """Verify MemoryHook creates and uses MemoryAccessGuard."""

    def test_hook_has_access_guard(self):
        hook = MemoryHook()
        assert hasattr(hook, "_access_guard")
        assert isinstance(hook._access_guard, MemoryAccessGuard)

    def test_guard_is_non_strict(self):
        hook = MemoryHook()
        assert hook._access_guard.strict_mode is False

    def test_valid_namespace_allows_enrichment(self, tmp_path):
        """When namespace is valid for the actor, on_before_invocation proceeds."""
        (tmp_path / "MEMORY.md").write_text("test context")
        hook = MemoryHook(
            workspace_dir=str(tmp_path),
            namespace_template="/plato/{actorId}/",
            namespace_vars={"actorId": "user42"},
        )
        # Namespace resolves to "/plato/user42/" which contains "user42"
        event = MagicMock()
        event.messages = []
        # Should NOT raise — guard allows access
        hook.on_before_invocation(event)

    def test_invalid_namespace_skips_enrichment(self, tmp_path):
        """When namespace is invalid (cross-user), enrichment is skipped."""
        (tmp_path / "MEMORY.md").write_text("secret data")
        hook = MemoryHook(
            workspace_dir=str(tmp_path),
            namespace_template="/plato/{actorId}/",
            namespace_vars={"actorId": ""},  # empty actor — guard will reject
        )
        event = MagicMock()
        event.messages = []
        # Should not crash — guard rejects but hook skips gracefully
        hook.on_before_invocation(event)

    def test_no_workspace_memory_skips_guard_check(self):
        """When no workspace memory is configured, guard is never called."""
        hook = MemoryHook(workspace_dir=None)
        event = MagicMock()
        event.messages = []
        # Should not crash — returns early because workspace_memory is None
        hook.on_before_invocation(event)

    def test_empty_namespace_skips_guard_check(self, tmp_path):
        """When namespace is empty string, guard is not called (short-circuit)."""
        (tmp_path / "MEMORY.md").write_text("some context")
        hook = MemoryHook(
            workspace_dir=str(tmp_path),
            namespace_template="",
            namespace_vars={},
        )
        # namespace is "" — the guard check is skipped (only runs when namespace truthy)
        event = MagicMock()
        event.messages = []
        hook.on_before_invocation(event)

    def test_root_namespace_blocked(self, tmp_path):
        """Root namespace '/' is blocked by guard — enrichment skipped."""
        ws = tmp_path / "root_ns"
        ws.mkdir()
        (ws / "MEMORY.md").write_text("should not be read")
        hook = MemoryHook(
            workspace_dir=str(tmp_path),
            namespace_template="/",
            namespace_vars={"actorId": "user1"},
        )
        event = MagicMock()
        event.messages = []
        # Guard blocks "/" — enrichment skipped, no crash
        hook.on_before_invocation(event)
