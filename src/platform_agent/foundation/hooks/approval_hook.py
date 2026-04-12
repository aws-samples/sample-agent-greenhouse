"""ApprovalHook — Human-in-the-Loop approval for tool execution.

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import BeforeToolCallEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False


@dataclass
class ApprovalConfig:
    """Configuration for approval requirements.

    Args:
        tools_requiring_approval: List of tool names that require human approval.
        default_action: What to do when approval is needed ("block" or "allow").
        timeout_seconds: How long to wait for approval (placeholder for now).
    """
    tools_requiring_approval: list[str]
    default_action: str = "block"
    timeout_seconds: int = 300


class ApprovalRequired(Exception):
    """Exception raised when human approval is required but not granted."""
    pass


class ApprovalHook(HookBase):
    """Hook that enforces human approval for specified tools.

    Works alongside GuardrailsHook: guardrails does auto-judge,
    approval does human checkpoint for critical tools.

    On BeforeToolCallEvent, checks if the tool requires approval.
    For now, implements a placeholder approval mechanism that logs
    and auto-allows with warning.

    Implements strands.hooks.HookProvider for native integration.

    Args:
        config: ApprovalConfig specifying which tools require approval
            and how to handle approval requests.
    """

    def __init__(
        self,
        config: ApprovalConfig | None = None,
        tools_requiring_approval: list[str] | None = None,
        default_action: str = "block",
        timeout_seconds: int = 300,
    ) -> None:
        # Support both config object and individual params for flexibility
        if config is not None:
            self.config = config
        else:
            self.config = ApprovalConfig(
                tools_requiring_approval=tools_requiring_approval or [],
                default_action=default_action,
                timeout_seconds=timeout_seconds,
            )

        self._required_tools = set(self.config.tools_requiring_approval)
        logger.info(
            "ApprovalHook initialized: %d tools require approval, default=%s",
            len(self._required_tools),
            self.config.default_action
        )

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call)

    def on_before_tool_call(self, event) -> None:
        """Check if tool requires approval before execution.

        Args:
            event: BeforeToolCallEvent with tool_use dict and cancel_tool field.
                   tool_use contains: toolUseId, name, input.
        """
        tool_use = getattr(event, "tool_use", {})
        tool_name = tool_use.get("name", "") if isinstance(tool_use, dict) else getattr(event, "tool_name", "")

        if tool_name in self._required_tools:
            # Tool requires approval
            logger.warning(
                "Tool '%s' requires human approval. Requesting approval...",
                tool_name
            )

            # Placeholder approval mechanism
            # In a real implementation, this would:
            # 1. Send approval request to human operator
            # 2. Wait for response or timeout
            # 3. Block or allow based on decision

            approved = self._request_approval(tool_name, tool_use)

            if not approved:
                event.cancel_tool = f"Tool '{tool_name}' blocked: human approval required but not granted."
                logger.warning("Tool %s blocked: approval denied", tool_name)
                return

            logger.info("Tool %s approved for execution", tool_name)

    def _request_approval(self, tool_name: str, tool_use: dict[str, Any]) -> bool:
        """Request human approval for a tool execution.

        This is a placeholder implementation. In production, this would:
        - Send notification to human operator (email, Slack, dashboard)
        - Wait for approval response or timeout
        - Return the approval decision

        Args:
            tool_name: Name of the tool requiring approval.
            tool_use: Full tool_use dict with parameters.

        Returns:
            True if approved, False if denied or timed out.
        """
        # Placeholder: Log the request and auto-allow with warning
        logger.warning(
            "PLACEHOLDER APPROVAL: Tool '%s' would normally require human approval. "
            "Auto-allowing for development. Tool params: %s",
            tool_name,
            tool_use.get("input", {})
        )

        # Honor the default_action setting
        if self.config.default_action == "allow":
            logger.info("Auto-approving '%s' based on default_action=allow", tool_name)
            return True
        else:
            logger.warning("Auto-blocking '%s' based on default_action=block", tool_name)
            return False

    def add_required_tool(self, tool_name: str) -> None:
        """Add a tool to the approval-required list.

        Args:
            tool_name: Name of the tool to require approval for.
        """
        self._required_tools.add(tool_name)
        self.config.tools_requiring_approval = list(self._required_tools)
        logger.info("Added tool '%s' to approval-required list", tool_name)

    def remove_required_tool(self, tool_name: str) -> None:
        """Remove a tool from the approval-required list.

        Args:
            tool_name: Name of the tool to stop requiring approval for.
        """
        self._required_tools.discard(tool_name)
        self.config.tools_requiring_approval = list(self._required_tools)
        logger.info("Removed tool '%s' from approval-required list", tool_name)

    def get_approval_config(self) -> dict[str, Any]:
        """Get current approval configuration.

        Returns:
            Dictionary containing current approval settings.
        """
        return {
            "tools_requiring_approval": sorted(self._required_tools),
            "default_action": self.config.default_action,
            "timeout_seconds": self.config.timeout_seconds,
        }