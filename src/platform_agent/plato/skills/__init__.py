"""Skill loading and registration for the Platform Agent.

Skills follow the Foundation Agent + Skills pattern from agent-foundry:
each skill pack adds a system prompt extension and optional MCP tools
to the base FoundationAgent.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from platform_agent.plato.skills.base import SkillPack

# Registry of available skill packs
_registry: dict[str, type[SkillPack]] = {}


def register_skill(name: str, skill_cls: type[SkillPack]) -> None:
    """Register a skill pack class by name."""
    _registry[name] = skill_cls


def get_skill(name: str) -> type[SkillPack]:
    """Retrieve a registered skill pack class by name.

    Raises:
        KeyError: If the skill is not registered.
    """
    if name not in _registry:
        raise KeyError(
            f"Skill '{name}' not found. Available: {list(_registry.keys())}"
        )
    return _registry[name]


def list_skills() -> list[str]:
    """Return names of all registered skill packs."""
    return list(_registry.keys())


def discover_skills(skills_dir: Path | None = None) -> None:
    """Auto-discover and register skill packs from the skills directory.

    Each subdirectory under skills_dir should contain an __init__.py
    that defines a SkillPack subclass and calls register_skill().
    """
    import importlib
    import sys

    if skills_dir is None:
        skills_dir = Path(__file__).parent

    for child in skills_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").exists():
            # Import triggers register_skill() in each skill's __init__.py
            module_name = f"platform_agent.plato.skills.{child.name}"
            try:
                if module_name in sys.modules and child.name not in _registry:
                    # Module cached but registry cleared — reload to re-register
                    importlib.reload(sys.modules[module_name])
                else:
                    __import__(module_name)
            except (ImportError, Exception):
                pass  # Skip skills with missing dependencies
