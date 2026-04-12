"""Tests for ApprovalHook — Human-in-the-Loop approval for tool execution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from platform_agent.foundation.hooks.approval_hook import (
    ApprovalHook,
    ApprovalConfig,
    ApprovalRequired,
)


class TestApprovalConfig:
    """Test ApprovalConfig dataclass."""

    def test_default_config(self):
        config = ApprovalConfig(tools_requiring_approval=["dangerous_tool"])
        assert config.tools_requiring_approval == ["dangerous_tool"]
        assert config.default_action == "block"
        assert config.timeout_seconds == 300

    def test_custom_config(self):
        config = ApprovalConfig(
            tools_requiring_approval=["tool1", "tool2"],
            default_action="allow",
            timeout_seconds=600,
        )
        assert config.tools_requiring_approval == ["tool1", "tool2"]
        assert config.default_action == "allow"
        assert config.timeout_seconds == 600


class TestApprovalHook:
    """Test ApprovalHook — Human-in-the-Loop approval mechanism."""

    def test_hook_initializes_with_config_object(self):
        config = ApprovalConfig(
            tools_requiring_approval=["delete_file"],
            default_action="allow",
            timeout_seconds=120,
        )
        hook = ApprovalHook(config=config)
        assert hook.config == config
        assert "delete_file" in hook._required_tools

    def test_hook_initializes_with_individual_params(self):
        hook = ApprovalHook(
            tools_requiring_approval=["write_file", "delete_file"],
            default_action="allow",
            timeout_seconds=180,
        )
        assert hook.config.tools_requiring_approval == ["write_file", "delete_file"]
        assert hook.config.default_action == "allow"
        assert hook.config.timeout_seconds == 180
        assert len(hook._required_tools) == 2

    def test_hook_allows_tools_not_requiring_approval(self):
        hook = ApprovalHook(tools_requiring_approval=["dangerous_tool"])
        event = MagicMock()
        event.tool_use = {"toolUseId": "1", "name": "safe_tool", "input": {}}
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        # Should not cancel safe tools
        assert event.cancel_tool is False

    def test_hook_blocks_tools_requiring_approval_with_default_block(self):
        hook = ApprovalHook(
            tools_requiring_approval=["dangerous_tool"],
            default_action="block"
        )
        event = MagicMock()
        event.tool_use = {"toolUseId": "2", "name": "dangerous_tool", "input": {}}
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        # Should cancel with block message
        assert isinstance(event.cancel_tool, str)
        assert "approval required but not granted" in event.cancel_tool

    def test_hook_allows_tools_requiring_approval_with_default_allow(self):
        hook = ApprovalHook(
            tools_requiring_approval=["admin_tool"],
            default_action="allow"
        )
        event = MagicMock()
        event.tool_use = {"toolUseId": "3", "name": "admin_tool", "input": {}}
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        # Should not cancel with allow default
        assert event.cancel_tool is False

    def test_hook_handles_empty_tool_use(self):
        hook = ApprovalHook(tools_requiring_approval=["any_tool"])
        event = MagicMock()
        event.tool_use = {}
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        # Should not cancel (empty tool name not in required list)
        assert event.cancel_tool is False

    def test_hook_handles_missing_tool_use(self):
        hook = ApprovalHook(tools_requiring_approval=["any_tool"])
        event = MagicMock()
        # No tool_use attribute
        delattr(event, 'tool_use')
        event.tool_name = "safe_tool"
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        # Should not cancel (safe_tool not in required list)
        assert event.cancel_tool is False

    def test_add_required_tool(self):
        hook = ApprovalHook(tools_requiring_approval=["tool1"])
        assert "tool2" not in hook._required_tools

        hook.add_required_tool("tool2")

        assert "tool2" in hook._required_tools
        assert "tool2" in hook.config.tools_requiring_approval

    def test_remove_required_tool(self):
        hook = ApprovalHook(tools_requiring_approval=["tool1", "tool2"])
        assert "tool2" in hook._required_tools

        hook.remove_required_tool("tool2")

        assert "tool2" not in hook._required_tools
        assert "tool2" not in hook.config.tools_requiring_approval
        assert "tool1" in hook._required_tools

    def test_remove_nonexistent_tool(self):
        hook = ApprovalHook(tools_requiring_approval=["tool1"])
        initial_tools = set(hook._required_tools)

        # Should not fail when removing non-existent tool
        hook.remove_required_tool("nonexistent")

        assert hook._required_tools == initial_tools

    def test_get_approval_config(self):
        hook = ApprovalHook(
            tools_requiring_approval=["tool1", "tool2"],
            default_action="allow",
            timeout_seconds=240,
        )

        config = hook.get_approval_config()

        assert set(config["tools_requiring_approval"]) == {"tool1", "tool2"}
        assert config["default_action"] == "allow"
        assert config["timeout_seconds"] == 240

    def test_request_approval_placeholder_behavior(self):
        """Test the placeholder approval mechanism behavior."""
        hook = ApprovalHook(
            tools_requiring_approval=["test_tool"],
            default_action="allow",
        )

        # Test allow behavior
        approved = hook._request_approval("test_tool", {"input": {"param": "value"}})
        assert approved is True

        # Test block behavior
        hook.config.default_action = "block"
        approved = hook._request_approval("test_tool", {"input": {"param": "value"}})
        assert approved is False

    def test_multiple_tools_requiring_approval(self):
        hook = ApprovalHook(
            tools_requiring_approval=["delete_file", "format_disk", "send_email"],
            default_action="block",
        )

        # Test each tool is blocked
        for tool_name in ["delete_file", "format_disk", "send_email"]:
            event = MagicMock()
            event.tool_use = {"toolUseId": f"id_{tool_name}", "name": tool_name, "input": {}}
            event.cancel_tool = False

            hook.on_before_tool_call(event)

            assert isinstance(event.cancel_tool, str)
            assert tool_name in event.cancel_tool

        # Test that other tools are not blocked
        event = MagicMock()
        event.tool_use = {"toolUseId": "safe_id", "name": "read_file", "input": {}}
        event.cancel_tool = False

        hook.on_before_tool_call(event)

        assert event.cancel_tool is False