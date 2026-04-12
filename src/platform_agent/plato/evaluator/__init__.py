"""Evaluator agents — quality gates with reflect-refine loops.

The evaluator layer implements the Evaluator-Critic pattern:
specialist agents produce output → evaluator scores against a rubric →
if below threshold, provides feedback → specialist revises → repeat.

Usage:
    from platform_agent.plato.evaluator import get_evaluator, list_evaluators
    from platform_agent.plato.evaluator.base import EvaluationRubric

    evaluator = get_evaluator("design")
    session = await evaluator.evaluate_with_refinement(specialist, request)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from platform_agent.plato.evaluator.base import EvaluatorAgent

# Registry of evaluator classes
_EVALUATORS: dict[str, type[EvaluatorAgent]] = {}


def register_evaluator(name: str, cls: type[EvaluatorAgent]) -> None:
    """Register an evaluator class."""
    _EVALUATORS[name] = cls


def get_evaluator(name: str) -> type[EvaluatorAgent]:
    """Get a registered evaluator class by name."""
    if name not in _EVALUATORS:
        discover_evaluators()
    if name not in _EVALUATORS:
        available = ", ".join(sorted(_EVALUATORS)) or "(none)"
        raise KeyError(f"Unknown evaluator: {name!r}. Available: {available}")
    return _EVALUATORS[name]


def list_evaluators() -> list[str]:
    """List all registered evaluator names."""
    discover_evaluators()
    return sorted(_EVALUATORS.keys())


def discover_evaluators() -> None:
    """Auto-discover and register built-in evaluators."""
    if _EVALUATORS:
        return
    # Import submodules to trigger registration
    from platform_agent.plato.evaluator import design  # noqa: F401
    from platform_agent.plato.evaluator import code_review  # noqa: F401
    from platform_agent.plato.evaluator import scaffold  # noqa: F401
    from platform_agent.plato.evaluator import deployment  # noqa: F401
