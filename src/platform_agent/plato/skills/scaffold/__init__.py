"""Scaffold skill pack - project generation and boilerplate creation."""

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

# SCAFFOLD_SYSTEM_PROMPT removed — SKILL.md is the sole prompt source.
class ScaffoldSkill(SkillPack):
    name: str = "scaffold"
    description: str = "Generate project skeletons and boilerplate for agent projects"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Write", "Edit", "Bash", "Glob"]  # type: ignore[assignment]

    def configure(self) -> None:
        pass


register_skill("scaffold", ScaffoldSkill)
