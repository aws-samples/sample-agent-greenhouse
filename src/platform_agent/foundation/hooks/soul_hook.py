"""SoulSystemHook — loads workspace files into system prompt on BeforeInvocationEvent.

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from platform_agent.foundation.soul import SoulSystem
from platform_agent.foundation.hooks.base import HookBase

logger = logging.getLogger(__name__)

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import BeforeInvocationEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False


class SoulSystemHook(HookBase):
    """Hook that loads workspace soul files before each agent invocation.

    On BeforeInvocationEvent, reloads all soul files from disk and makes
    the assembled prompt available for system prompt construction.

    Implements strands.hooks.HookProvider for native integration.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self.workspace_dir = workspace_dir
        self.soul_system: SoulSystem | None = None
        if workspace_dir:
            self.soul_system = SoulSystem(workspace_dir=workspace_dir)

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry.

        Args:
            registry: HookRegistry instance from strands.hooks.
        """
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)

    def on_before_invocation(self, event) -> None:
        """Reload soul files before each invocation.

        Args:
            event: BeforeInvocationEvent with writable messages field.
        """
        if not self.workspace_dir:
            return

        if self.soul_system is None:
            self.soul_system = SoulSystem(workspace_dir=self.workspace_dir)
        else:
            self.soul_system.reload()

    def get_soul_prompt(self) -> str:
        """Get the assembled soul prompt for system prompt injection."""
        if self.soul_system is None:
            return ""
        return self.soul_system.assemble_prompt()
