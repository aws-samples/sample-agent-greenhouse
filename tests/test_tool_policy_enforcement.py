"""Tests for Tool Policy Enforcement — verifying hardcoded allowlist/denylist enforcement.

These tests extend the existing ToolPolicyHook tests to verify that enforcement
is actually working correctly and tools are properly blocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from platform_agent.foundation.hooks.tool_policy_hook import ToolPolicyHook


class TestToolPolicyEnforcement:
    """Test comprehensive tool policy enforcement scenarios."""

    def test_denylist_enforcement_blocks_execution(self):
        """Verify that denied tools are actually blocked."""
        hook = ToolPolicyHook(denylist=["delete_database", "format_disk"])

        # Test that denied tool is blocked
        event = MagicMock()
        event.tool_use = {
            "toolUseId": "test_001",
            "name": "delete_database",
            "input": {"table": "users"}
        }
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        assert event.cancel_tool is not False  # Should be a string message
        assert isinstance(event.cancel_tool, str)
        assert "blocked by policy" in event.cancel_tool
        assert "denylist" in event.cancel_tool

    def test_allowlist_enforcement_blocks_unlisted_tools(self):
        """Verify that only allowlisted tools are permitted."""
        hook = ToolPolicyHook(allowlist=["read_file", "list_files"])

        # Test that unlisted tool is blocked
        event = MagicMock()
        event.tool_use = {
            "toolUseId": "test_002",
            "name": "write_file",  # Not in allowlist
            "input": {"path": "/tmp/test.txt", "content": "data"}
        }
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        assert event.cancel_tool is not False
        assert isinstance(event.cancel_tool, str)
        assert "not permitted by policy" in event.cancel_tool
        assert "allowlist" in event.cancel_tool

    def test_allowlist_permits_listed_tools(self):
        """Verify that allowlisted tools are permitted."""
        hook = ToolPolicyHook(allowlist=["read_file", "list_files"])

        # Test that allowlisted tool is permitted
        event = MagicMock()
        event.tool_use = {
            "toolUseId": "test_003",
            "name": "read_file",  # In allowlist
            "input": {"path": "/tmp/test.txt"}
        }
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        assert event.cancel_tool is False  # Should remain False (not blocked)

    def test_denylist_precedence_over_allowlist(self):
        """Verify that denylist takes precedence over allowlist."""
        hook = ToolPolicyHook(
            allowlist=["read_file", "write_file", "delete_file"],
            denylist=["delete_file"]  # delete_file is both allowed and denied
        )

        event = MagicMock()
        event.tool_use = {
            "toolUseId": "test_004",
            "name": "delete_file",
            "input": {"path": "/tmp/sensitive.txt"}
        }
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        # Should be blocked due to denylist precedence
        assert event.cancel_tool is not False
        assert "blocked by policy" in event.cancel_tool
        assert "denylist" in event.cancel_tool

    def test_no_policy_allows_all_tools(self):
        """Verify that no policy means all tools are allowed."""
        hook = ToolPolicyHook()  # No allowlist or denylist

        dangerous_tools = [
            "delete_database", "format_disk", "send_email",
            "execute_shell", "modify_system", "access_secrets"
        ]

        for tool_name in dangerous_tools:
            event = MagicMock()
            event.tool_use = {
                "toolUseId": f"test_{tool_name}",
                "name": tool_name,
                "input": {}
            }
            event.cancel_tool = False

            hook.on_before_tool_call(event)

            assert event.cancel_tool is False, f"Tool {tool_name} should be allowed when no policy is set"

    def test_empty_allowlist_blocks_all_tools(self):
        """Verify that an empty allowlist blocks all tools."""
        hook = ToolPolicyHook(allowlist=[])  # Empty allowlist

        common_tools = ["read_file", "write_file", "list_files", "execute_command"]

        for tool_name in common_tools:
            event = MagicMock()
            event.tool_use = {
                "toolUseId": f"test_{tool_name}",
                "name": tool_name,
                "input": {}
            }
            event.cancel_tool = False

            hook.on_before_tool_call(event)

            assert event.cancel_tool is not False, f"Tool {tool_name} should be blocked by empty allowlist"
            assert "not permitted by policy" in event.cancel_tool

    def test_empty_denylist_allows_all_tools(self):
        """Verify that an empty denylist allows all tools."""
        hook = ToolPolicyHook(denylist=[])  # Empty denylist, no allowlist

        tools = ["read_file", "write_file", "delete_file", "execute_command"]

        for tool_name in tools:
            event = MagicMock()
            event.tool_use = {
                "toolUseId": f"test_{tool_name}",
                "name": tool_name,
                "input": {}
            }
            event.cancel_tool = False

            hook.on_before_tool_call(event)

            assert event.cancel_tool is False, f"Tool {tool_name} should be allowed with empty denylist"

    def test_case_sensitive_tool_names(self):
        """Verify that tool name matching is case-sensitive."""
        hook = ToolPolicyHook(denylist=["DeleteFile"])  # Capital D

        event = MagicMock()
        event.tool_use = {
            "toolUseId": "test_case",
            "name": "deleteFile",  # Lowercase d - should NOT match
            "input": {}
        }
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        # Should be allowed because case doesn't match
        assert event.cancel_tool is False

    def test_malformed_tool_use_object(self):
        """Test handling of malformed tool_use objects."""
        hook = ToolPolicyHook(denylist=["dangerous_tool"])

        # Test with missing 'name' field
        event = MagicMock()
        event.tool_use = {"toolUseId": "test_malformed"}  # No 'name' field
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        # Should not crash and should allow (empty string not in denylist)
        assert event.cancel_tool is False

    def test_policy_summary_accuracy(self):
        """Verify that policy summary reflects actual enforcement."""
        allowlist = ["read_file", "write_file"]
        denylist = ["delete_file", "format_disk"]

        hook = ToolPolicyHook(allowlist=allowlist, denylist=denylist)
        summary = hook.get_policy_summary()

        assert set(summary["allowlist"]) == set(allowlist)
        assert set(summary["denylist"]) == set(denylist)

    def test_policy_enforcement_with_special_characters(self):
        """Test policy enforcement with tool names containing special characters."""
        hook = ToolPolicyHook(denylist=["tool_with-dash", "tool.with.dots", "tool_with_underscores"])

        special_tools = ["tool_with-dash", "tool.with.dots", "tool_with_underscores"]

        for tool_name in special_tools:
            event = MagicMock()
            event.tool_use = {
                "toolUseId": f"test_{tool_name.replace('.', '_').replace('-', '_')}",
                "name": tool_name,
                "input": {}
            }
            event.cancel_tool = False

            hook.on_before_tool_call(event)

            assert event.cancel_tool is not False, f"Tool {tool_name} should be blocked"
            assert "blocked by policy" in event.cancel_tool

    def test_comprehensive_enforcement_scenario(self):
        """Test a comprehensive real-world enforcement scenario."""
        # Simulate a restrictive production environment
        hook = ToolPolicyHook(
            allowlist=[
                "read_file", "list_files", "get_status",
                "query_database", "send_notification"
            ],
            denylist=[
                "delete_file", "write_file", "execute_shell",
                "format_disk", "modify_system", "access_secrets"
            ]
        )

        # Test allowed tools
        allowed_tools = ["read_file", "list_files", "get_status"]
        for tool_name in allowed_tools:
            event = MagicMock()
            event.tool_use = {"toolUseId": f"allow_{tool_name}", "name": tool_name, "input": {}}
            event.cancel_tool = False

            hook.on_before_tool_call(event)
            assert event.cancel_tool is False, f"Allowed tool {tool_name} should not be blocked"

        # Test explicitly denied tools (denylist precedence)
        denied_tools = ["delete_file", "write_file"]  # These would be in allowlist if not for denylist
        for tool_name in denied_tools:
            event = MagicMock()
            event.tool_use = {"toolUseId": f"deny_{tool_name}", "name": tool_name, "input": {}}
            event.cancel_tool = False

            hook.on_before_tool_call(event)
            assert event.cancel_tool is not False, f"Denied tool {tool_name} should be blocked"
            assert "denylist" in event.cancel_tool

        # Test tools not in allowlist (should be blocked)
        unlisted_tools = ["random_tool", "new_feature"]
        for tool_name in unlisted_tools:
            event = MagicMock()
            event.tool_use = {"toolUseId": f"unlisted_{tool_name}", "name": tool_name, "input": {}}
            event.cancel_tool = False

            hook.on_before_tool_call(event)
            assert event.cancel_tool is not False, f"Unlisted tool {tool_name} should be blocked"
            assert "allowlist" in event.cancel_tool