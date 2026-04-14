"""Onboarding Skill — new team onboarding and platform standards guidance.

Provides guidance on onboarding new teams to the platform, including
CLAUDE.md generation, agent setup, and platform standards compliance.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


# ONBOARDING_PROMPT removed — SKILL.md is the sole prompt source.
class OnboardingSkill(SkillPack):
    """Onboarding skill for the Plato Control Plane."""

    name: str = "onboarding"
    description: str = (
        "Onboarding specialist for new team setup, CLAUDE.md generation, "
        "agent configuration, and platform standards compliance. "
        "Use when teams need to onboard to the platform, set up new agents, "
        "generate configuration files, or learn platform standards."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Write", "Glob", "Grep"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("onboarding", OnboardingSkill)
