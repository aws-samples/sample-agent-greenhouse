"""Observability Skill — agent status monitoring, violation tracking, and reporting.

Provides guidance on monitoring agent fleet health, tracking policy violations,
generating compliance reports, and analyzing audit logs.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


# OBSERVABILITY_PROMPT removed — SKILL.md is the sole prompt source.
class ObservabilitySkill(SkillPack):
    """Observability skill for the Plato Control Plane."""

    name: str = "observability"
    description: str = (
        "Observability specialist for agent fleet monitoring, policy violation "
        "tracking, audit log analysis, and compliance reporting. "
        "Use when teams need to check agent status, investigate violations, "
        "analyze audit logs, or generate operational reports."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Glob", "Grep", "Bash"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("observability", ObservabilitySkill)
