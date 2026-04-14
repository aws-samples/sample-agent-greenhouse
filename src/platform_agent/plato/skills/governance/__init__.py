"""Governance Skill — agent registration, policy management, and routing governance.

Provides guidance on registering agents, configuring Cedar policies,
setting up message routing patterns, and enforcing platform governance.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


# GOVERNANCE_PROMPT removed — SKILL.md is the sole prompt source.
class GovernanceSkill(SkillPack):
    """Governance skill for the Plato Control Plane."""

    name: str = "governance"
    description: str = (
        "Governance specialist for agent registration, Cedar policy management, "
        "message routing configuration, and platform compliance. "
        "Use when teams need to register agents, configure policies, "
        "set up routing patterns, or enforce governance standards."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Glob", "Grep"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("governance", GovernanceSkill)
