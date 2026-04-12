"""ToolPolicyHook — allowlist/denylist for tool access control.

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import BeforeToolCallEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



class ToolPolicyHook(HookBase):
    """Hook that enforces tool access policies via allowlist/denylist.

    On BeforeToolCallEvent, checks whether the tool is permitted.
    Sets cancel_tool on the event to block disallowed tools.

    Implements strands.hooks.HookProvider for native integration.

    Rules:
    - If denylist is set and tool is in it, block (highest priority).
    - If allowlist is set and tool is NOT in it, block.
    - If neither is set, allow all.

    Args:
        allowlist: Optional list of permitted tool names.
        denylist: Optional list of blocked tool names.
    """

    def __init__(
        self,
        allowlist: list[str] | None = None,
        denylist: list[str] | None = None,
    ) -> None:
        self.allowlist = set(allowlist) if allowlist is not None else None
        self.denylist = set(denylist) if denylist is not None else None

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call)

    def on_before_tool_call(self, event) -> None:
        """Check tool access policy before execution.

        Args:
            event: BeforeToolCallEvent with tool_use dict and cancel_tool field.
                   tool_use contains: toolUseId, name, input.
        """
        tool_use = getattr(event, "tool_use", {})
        tool_name = tool_use.get("name", "") if isinstance(tool_use, dict) else getattr(event, "tool_name", "")

        # Denylist takes precedence
        if self.denylist and tool_name in self.denylist:
            event.cancel_tool = f"Tool '{tool_name}' is blocked by policy (denylist)."
            logger.warning("Tool %s blocked by denylist", tool_name)
            return

        # Allowlist check - if allowlist is provided (even if empty), only tools in it are allowed
        if self.allowlist is not None and tool_name not in self.allowlist:
            event.cancel_tool = f"Tool '{tool_name}' is not permitted by policy (not in allowlist)."
            logger.warning("Tool %s not in allowlist", tool_name)
            return

    def get_policy_summary(self) -> dict:
        """Get a summary of the current policy configuration."""
        return {
            "allowlist": sorted(self.allowlist) if self.allowlist else [],
            "denylist": sorted(self.denylist) if self.denylist else [],
        }
