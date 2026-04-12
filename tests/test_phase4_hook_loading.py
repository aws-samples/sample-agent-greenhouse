"""Phase 4 tests — harness-driven hook loading via DomainHarness.

Directive requirements:
- Minimal DomainHarness (0 extra hooks) → only 4 foundation hooks active
- Plato harness → all non-optional hooks active (4 foundation + 8 domain = 12)
- harness=None backward compat → original 11 hooks
- All hooks in the registry must be HookBase instances
"""

from __future__ import annotations

import pytest

# Import plato.harness FIRST so that platform_agent.plato is loaded before
# platform_agent.foundation.  This breaks the pre-existing circular import:
#   foundation → hooks → aidlc_telemetry_hook → platform_agent.aidlc shim
#   → platform_agent.plato → platform_agent.foundation (circular)
# Loading plato first means plato.aidlc is already in sys.modules when the
# aidlc shim runs, so the circular chain never forms.
from platform_agent.plato.harness import create_plato_harness  # noqa: E402

from platform_agent.foundation.agent import FoundationAgent
from platform_agent.foundation.harness import DomainHarness
from platform_agent.foundation.hooks import HookBase
from platform_agent.foundation.hooks.audit_hook import AuditHook
from platform_agent.foundation.hooks.guardrails_hook import GuardrailsHook
from platform_agent.foundation.hooks.soul_hook import SoulSystemHook
from platform_agent.foundation.hooks.telemetry_hook import TelemetryHook


# ---------------------------------------------------------------------------
# Minimal harness — 0 extra hooks → only 4 foundation hooks
# ---------------------------------------------------------------------------


def test_minimal_harness_loads_only_foundation_hooks():
    """A DomainHarness with no hooks list should produce exactly 4 active hooks."""
    minimal_harness = DomainHarness(name="minimal")
    agent = FoundationAgent(harness=minimal_harness)
    assert len(agent.hook_registry) == 4


def test_minimal_harness_foundation_hooks_are_the_four_always_on():
    """The 4 always-on hooks must be SoulSystemHook, AuditHook, GuardrailsHook, TelemetryHook."""
    minimal_harness = DomainHarness(name="minimal")
    agent = FoundationAgent(harness=minimal_harness)

    hook_types = {type(h) for h in agent.hook_registry}
    assert SoulSystemHook in hook_types
    assert AuditHook in hook_types
    assert GuardrailsHook in hook_types
    assert TelemetryHook in hook_types


# ---------------------------------------------------------------------------
# Plato harness — 4 foundation + 7 domain = 11 always-active hooks
# ---------------------------------------------------------------------------


def test_plato_harness_loads_all_non_optional_hooks():
    """Plato harness (optional hooks disabled) → 12 hooks in registry."""
    harness = create_plato_harness()
    agent = FoundationAgent(harness=harness)

    # Plato harness: 4 foundation + 8 domain always-active; 2 optional disabled
    assert len(agent.hook_registry) == 12


def test_plato_harness_includes_foundation_hooks():
    """Plato harness must include the 4 always-on foundation hooks."""
    harness = create_plato_harness()
    agent = FoundationAgent(harness=harness)

    hook_types = {type(h) for h in agent.hook_registry}
    assert SoulSystemHook in hook_types
    assert AuditHook in hook_types
    assert GuardrailsHook in hook_types
    assert TelemetryHook in hook_types


# ---------------------------------------------------------------------------
# Backward compatibility — harness=None loads 11 hooks as before
# ---------------------------------------------------------------------------


def test_no_harness_loads_eleven_hooks_backward_compat():
    """harness=None must load the original 11 always-active hooks."""
    agent = FoundationAgent()
    assert len(agent.hook_registry) == 11


# ---------------------------------------------------------------------------
# HookBase inheritance
# ---------------------------------------------------------------------------


def test_all_hooks_are_hookbase_instances_minimal_harness():
    """Every hook in the registry must be a HookBase instance (minimal harness)."""
    agent = FoundationAgent(harness=DomainHarness(name="minimal"))
    for hook in agent.hook_registry:
        assert isinstance(hook, HookBase), (
            f"{type(hook).__name__} is not a HookBase instance"
        )


def test_all_hooks_are_hookbase_instances_plato_harness():
    """Every hook in the Plato-harness registry must be a HookBase instance."""
    agent = FoundationAgent(harness=create_plato_harness())
    for hook in agent.hook_registry:
        assert isinstance(hook, HookBase), (
            f"{type(hook).__name__} is not a HookBase instance"
        )


def test_all_hooks_are_hookbase_instances_no_harness():
    """Every hook in the legacy (no-harness) registry must be a HookBase instance."""
    agent = FoundationAgent()
    for hook in agent.hook_registry:
        assert isinstance(hook, HookBase), (
            f"{type(hook).__name__} is not a HookBase instance"
        )


# ---------------------------------------------------------------------------
# Optional hooks — only loaded when enabled_by condition is True
# ---------------------------------------------------------------------------


def test_optional_hooks_not_loaded_when_disabled():
    """MemoryExtractionHook and ConsolidationHook must NOT be loaded when disabled."""
    from platform_agent.foundation.hooks.memory_extraction_hook import MemoryExtractionHook
    from platform_agent.foundation.hooks.consolidation_hook import ConsolidationHook

    harness = create_plato_harness()  # extraction_enabled=False, consolidation_enabled=False
    agent = FoundationAgent(harness=harness)

    hook_types = {type(h) for h in agent.hook_registry}
    assert MemoryExtractionHook not in hook_types
    assert ConsolidationHook not in hook_types


# ---------------------------------------------------------------------------
# HookBase interface
# ---------------------------------------------------------------------------


def test_hookbase_has_lifecycle_methods():
    """HookBase must expose pre_invoke, post_invoke, pre_tool_call, post_tool_call."""
    hook = HookBase()
    # All methods must exist and be callable (no-ops)
    hook.pre_invoke(None)
    hook.post_invoke(None)
    hook.pre_tool_call(None)
    hook.post_tool_call(None)


def test_hookbase_register_hooks_is_noop():
    """HookBase.register_hooks must accept a registry argument without raising."""

    class _FakeRegistry:
        pass

    hook = HookBase()
    hook.register_hooks(_FakeRegistry())  # Should not raise
