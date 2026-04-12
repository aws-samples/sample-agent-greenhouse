"""HookBase — base class for all Foundation Agent hooks.

Provides no-op default implementations of lifecycle methods so every hook
can be registered through the same interface regardless of whether it uses
the Strands HookProvider event system or an alternative mechanism.
"""

from __future__ import annotations

try:
    from strands.hooks import HookProvider as _StrandsHookProvider
except ImportError:
    class _StrandsHookProvider:  # type: ignore[no-redef]
        """Fallback base when strands is not installed."""

        def register_hooks(self, registry) -> None:
            pass


class HookBase(_StrandsHookProvider):
    """Base class for all Foundation Agent hooks.

    Provides no-op default implementations of lifecycle methods.
    Strands-based hooks override ``register_hooks()`` to subscribe to events.
    Non-Strands hooks (e.g., ``AIDLCTelemetryHook``) may use other
    registration mechanisms and leave ``register_hooks`` as a no-op.

    Lifecycle methods (all no-ops by default):
        pre_invoke: Before each agent invocation.
        post_invoke: After each agent invocation.
        pre_tool_call: Before each tool call.
        post_tool_call: After each tool call.
    """

    def pre_invoke(self, event) -> None:
        """Called before agent invocation. No-op by default."""

    def post_invoke(self, event) -> None:
        """Called after agent invocation. No-op by default."""

    def pre_tool_call(self, event) -> None:
        """Called before a tool call. No-op by default."""

    def post_tool_call(self, event) -> None:
        """Called after a tool call. No-op by default."""
