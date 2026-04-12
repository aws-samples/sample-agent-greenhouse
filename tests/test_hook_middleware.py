"""Tests for Hook Middleware — registration, event handling, tool policy."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


from platform_agent.foundation.hooks.soul_hook import SoulSystemHook
from platform_agent.foundation.hooks.audit_hook import AuditHook
from platform_agent.foundation.hooks.guardrails_hook import GuardrailsHook
from platform_agent.foundation.hooks.tool_policy_hook import ToolPolicyHook


# ---------------------------------------------------------------------------
# SoulSystemHook
# ---------------------------------------------------------------------------


class TestSoulSystemHook:
    """Test SoulSystemHook — loads workspace files into system prompt."""

    def test_hook_initializes_with_workspace(self, tmp_path):
        hook = SoulSystemHook(workspace_dir=str(tmp_path))
        assert hook.workspace_dir == str(tmp_path)

    def test_hook_loads_soul_on_before_invocation(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("Be creative.")
        hook = SoulSystemHook(workspace_dir=str(tmp_path))
        event = MagicMock()
        event.messages = []
        hook.on_before_invocation(event)
        assert hook.soul_system is not None
        assert hook.soul_system.soul == "Be creative."

    def test_hook_without_workspace_is_noop(self):
        hook = SoulSystemHook(workspace_dir=None)
        event = MagicMock()
        event.messages = []
        hook.on_before_invocation(event)
        # Should not raise

    def test_hook_refreshes_on_each_invocation(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("V1")
        hook = SoulSystemHook(workspace_dir=str(tmp_path))

        event = MagicMock()
        event.messages = []
        hook.on_before_invocation(event)
        assert hook.soul_system.soul == "V1"

        # Change file
        (tmp_path / "SOUL.md").write_text("V2")
        hook.on_before_invocation(event)
        assert hook.soul_system.soul == "V2"


# ---------------------------------------------------------------------------
# AuditHook
# ---------------------------------------------------------------------------


class TestAuditHook:
    """Test AuditHook — logs all tool calls."""

    def test_hook_initializes_with_empty_log(self):
        hook = AuditHook()
        assert hook.tool_calls == []

    def test_logs_before_tool_call(self):
        hook = AuditHook()
        event = MagicMock()
        event.tool_use = {"toolUseId": "123", "name": "read_file", "input": {"path": "/tmp/test.txt"}}
        hook.on_before_tool_call(event)
        assert len(hook.tool_calls) == 1
        assert hook.tool_calls[0]["tool_name"] == "read_file"
        assert hook.tool_calls[0]["status"] == "started"

    def test_logs_after_tool_call(self):
        hook = AuditHook()
        # Before
        before_event = MagicMock()
        before_event.tool_use = {"toolUseId": "123", "name": "read_file", "input": {"path": "/tmp/test.txt"}}
        hook.on_before_tool_call(before_event)
        # After
        after_event = MagicMock()
        after_event.tool_use = {"toolUseId": "123", "name": "read_file", "input": {}}
        after_event.tool_result = "file contents"
        hook.on_after_tool_call(after_event)
        assert len(hook.tool_calls) == 2
        assert hook.tool_calls[1]["status"] == "completed"

    def test_get_audit_log(self):
        hook = AuditHook()
        event = MagicMock()
        event.tool_use = {"toolUseId": "456", "name": "write_file", "input": {"path": "/tmp/out.txt"}}
        hook.on_before_tool_call(event)
        log = hook.get_audit_log()
        assert len(log) == 1
        assert log[0]["tool_name"] == "write_file"

    def test_clear_audit_log(self):
        hook = AuditHook()
        event = MagicMock()
        event.tool_use = {"toolUseId": "789", "name": "test", "input": {}}
        hook.on_before_tool_call(event)
        assert len(hook.tool_calls) == 1
        hook.clear()
        assert len(hook.tool_calls) == 0


# ---------------------------------------------------------------------------
# GuardrailsHook
# ---------------------------------------------------------------------------


class TestGuardrailsHook:
    """Test GuardrailsHook — input/output validation placeholder."""

    def test_hook_initializes(self):
        hook = GuardrailsHook()
        assert hook is not None

    def test_input_validation_passes_by_default(self):
        hook = GuardrailsHook()
        messages = [{"role": "user", "content": [{"text": "Hello"}]}]
        # Default validator should accept all input
        assert hook.validate_input(messages) is True

    def test_output_validation_passes_by_default(self):
        hook = GuardrailsHook()
        event = MagicMock()
        event.result = {"role": "assistant", "content": [{"text": "Response"}]}
        hook.on_after_invocation(event)
        # Should not modify by default

    def test_custom_input_validator(self):
        def block_secrets(messages):
            for msg in messages:
                for content in msg.get("content", []):
                    if "SECRET" in content.get("text", ""):
                        return False
            return True

        hook = GuardrailsHook(input_validator=block_secrets)
        event = MagicMock()
        event.messages = [{"role": "user", "content": [{"text": "My SECRET key"}]}]
        result = hook.validate_input(event.messages)
        assert result is False

    def test_custom_output_validator(self):
        def check_pii(text):
            return "SSN" not in text

        hook = GuardrailsHook(output_validator=check_pii)
        assert hook.validate_output("Here is your SSN: 123") is False
        assert hook.validate_output("Hello there") is True


# ---------------------------------------------------------------------------
# ToolPolicyHook
# ---------------------------------------------------------------------------


class TestToolPolicyHook:
    """Test ToolPolicyHook — allowlist/denylist for tool access."""

    def test_default_allows_all(self):
        hook = ToolPolicyHook()
        event = MagicMock()
        event.tool_use = {"toolUseId": "1", "name": "any_tool", "input": {}}
        event.cancel_tool = False
        hook.on_before_tool_call(event)
        # Should not cancel when no policy is set
        assert event.cancel_tool is False

    def test_allowlist_permits_listed_tool(self):
        hook = ToolPolicyHook(allowlist=["read_file", "write_file"])
        event = MagicMock()
        event.tool_use = {"toolUseId": "2", "name": "read_file", "input": {}}
        event.cancel_tool = False
        hook.on_before_tool_call(event)
        assert event.cancel_tool is False

    def test_allowlist_blocks_unlisted_tool(self):
        hook = ToolPolicyHook(allowlist=["read_file"])
        event = MagicMock()
        event.tool_use = {"toolUseId": "3", "name": "delete_file", "input": {}}
        event.cancel_tool = False
        hook.on_before_tool_call(event)
        assert event.cancel_tool  # String message or True, both truthy

    def test_denylist_blocks_listed_tool(self):
        hook = ToolPolicyHook(denylist=["dangerous_tool"])
        event = MagicMock()
        event.tool_use = {"toolUseId": "4", "name": "dangerous_tool", "input": {}}
        event.cancel_tool = False
        hook.on_before_tool_call(event)
        assert event.cancel_tool  # String message or True, both truthy

    def test_denylist_allows_unlisted_tool(self):
        hook = ToolPolicyHook(denylist=["dangerous_tool"])
        event = MagicMock()
        event.tool_use = {"toolUseId": "5", "name": "safe_tool", "input": {}}
        event.cancel_tool = False
        hook.on_before_tool_call(event)
        assert event.cancel_tool is False

    def test_denylist_takes_precedence_over_allowlist(self):
        hook = ToolPolicyHook(
            allowlist=["read_file", "delete_file"],
            denylist=["delete_file"],
        )
        event = MagicMock()
        event.tool_use = {"toolUseId": "6", "name": "delete_file", "input": {}}
        event.cancel_tool = False
        hook.on_before_tool_call(event)
        assert event.cancel_tool  # String message or True, both truthy

    def test_get_policy_summary(self):
        hook = ToolPolicyHook(
            allowlist=["read_file"],
            denylist=["delete_file"],
        )
        summary = hook.get_policy_summary()
        assert "read_file" in summary["allowlist"]
        assert "delete_file" in summary["denylist"]
