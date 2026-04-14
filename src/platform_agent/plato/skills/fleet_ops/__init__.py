"""Fleet Ops Skill — agent restart, scaling, draining, and operational management.

Provides guidance on managing agent fleet operations including restarts,
scaling, graceful shutdown, and capacity planning.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


# FLEET_OPS_PROMPT removed — SKILL.md is the sole prompt source.
class FleetOpsSkill(SkillPack):
    """Fleet operations skill for the Plato Control Plane."""

    name: str = "fleet_ops"
    description: str = (
        "Fleet operations specialist for agent restart, scaling, graceful "
        "draining, and capacity planning. "
        "Use when teams need to restart agents, scale the fleet up or down, "
        "drain agents for maintenance, or plan capacity."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Glob", "Grep", "Bash"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("fleet_ops", FleetOpsSkill)
