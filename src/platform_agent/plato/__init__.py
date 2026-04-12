"""Plato domain package — Platform Agent for Amazon Bedrock AgentCore.

Public API:
    create_plato_agent(**kwargs) -> FoundationAgent
    create_plato_harness() -> DomainHarness
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from platform_agent.foundation.agent import FoundationAgent


def create_plato_harness():
    """Re-export for convenience."""
    from platform_agent.plato.harness import create_plato_harness as _create
    return _create()


def create_plato_agent(**kwargs) -> FoundationAgent:
    """Create a fully-configured Plato FoundationAgent.

    Args:
        **kwargs: Additional keyword arguments forwarded to FoundationAgent.

    Returns:
        A FoundationAgent configured with the Plato domain harness.
    """
    from platform_agent.foundation import FoundationAgent as _FA
    from platform_agent.plato.harness import create_plato_harness as _create_harness

    harness = _create_harness()
    return _FA(harness=harness, **kwargs)


__all__ = ["create_plato_agent", "create_plato_harness"]
