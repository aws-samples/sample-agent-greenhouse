"""MemoryHook — manages memory enrichment and persistence.

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import logging
import os

from platform_agent.foundation.memory import SessionMemory, WorkspaceMemory
from platform_agent.foundation.memory_access_guard import MemoryAccessGuard

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import BeforeInvocationEvent, MessageAddedEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



class MemoryHook(HookBase):
    """Hook that records messages and enriches invocations with memory context.

    - Records all messages to session memory for history tracking.
    - Optionally enriches invocations with workspace memory context.

    Implements strands.hooks.HookProvider for native integration.
    """

    def __init__(
        self,
        workspace_dir: str | None = None,
        namespace_template: str = "",
        namespace_vars: dict[str, str] | None = None,
        ttl_days: int | None = None,
    ) -> None:
        self._namespace_template = namespace_template
        self._namespace_vars = namespace_vars or {}
        self.ttl_days = ttl_days
        self._access_guard = MemoryAccessGuard(strict_mode=False)

        # Compute resolved namespace from template + vars
        self.namespace = self._compute_namespace()

        # Effective workspace path (namespace sub-path when namespace is set)
        effective_workspace = self._effective_workspace(workspace_dir)

        self.session_memory = SessionMemory()
        self.workspace_memory: WorkspaceMemory | None = None
        if effective_workspace:
            self.workspace_memory = WorkspaceMemory(workspace_dir=effective_workspace)

    def _compute_namespace(self) -> str:
        """Resolve namespace_template using namespace_vars."""
        if not self._namespace_template:
            return ""
        try:
            return self._namespace_template.format(**self._namespace_vars)
        except KeyError:
            return self._namespace_template  # keep template literal if vars missing

    def _effective_workspace(self, workspace_dir: str | None) -> str | None:
        """Return workspace_dir with namespace appended when namespace is non-empty."""
        if workspace_dir and self.namespace:
            return os.path.join(workspace_dir, self.namespace)
        return workspace_dir

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(MessageAddedEvent, self.on_message_added)
            registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)

    def on_message_added(self, event) -> None:
        """Record a message to session memory.

        Args:
            event: MessageAddedEvent with message dict.
        """
        msg = event.message
        role = msg.get("role", "user")
        content_parts = msg.get("content", [])
        text = ""
        for part in content_parts:
            if isinstance(part, dict) and "text" in part:
                text += part["text"]
            elif isinstance(part, str):
                text += part
        if text:
            self.session_memory.add_message(role, text)

    def on_before_invocation(self, event) -> None:
        """Enrich invocation with workspace memory context.

        .. note::
            This method is intentionally a no-op beyond access-guard validation.
            LTM injection into ``event.messages`` was removed in v1 — memory
            enrichment is now handled by the agent via workspace tools and the
            AgentCore event-based pipeline.  The hook callback is kept registered
            so that the access-guard validation still fires (preventing invalid
            namespace access) and to avoid breaking the HookRegistry contract.

        Args:
            event: BeforeInvocationEvent (not modified).
        """
        if self.workspace_memory is None:
            return

        # Validate namespace access before any LTM retrieval
        actor_id = self._namespace_vars.get("actorId", "")
        if self.namespace and not self._access_guard.validate_namespace(self.namespace, actor_id):
            logger.warning(
                "MemoryHook: namespace '%s' failed access guard for actor '%s' — skipping LTM retrieval",
                self.namespace,
                actor_id,
            )
            return
