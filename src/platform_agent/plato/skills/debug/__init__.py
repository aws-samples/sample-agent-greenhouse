"""Debug Skill — helps developers troubleshoot agent deployment issues.

Provides structured debugging workflows for common AgentCore deployment
problems: container failures, IAM permission errors, runtime exceptions,
health check timeouts, and memory/performance issues.

Uses progressive disclosure: the system prompt tells the agent WHERE to find
debugging guides, not the guides themselves.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


# DEBUG_PROMPT removed — SKILL.md is the sole prompt source.
class DebugSkill(SkillPack):
    """Debug skill for troubleshooting AgentCore deployment issues."""

    name: str = "debug"
    description: str = (
        "Debugging specialist for AgentCore deployments: container failures, "
        "IAM permission errors, runtime exceptions, networking issues, and "
        "performance problems. Use when developers report errors, crashes, "
        "deployment failures, or need help troubleshooting their agent applications."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Glob", "Grep", "Bash"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("debug", DebugSkill)
