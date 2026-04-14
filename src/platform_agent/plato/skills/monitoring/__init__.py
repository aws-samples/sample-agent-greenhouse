"""Production Monitoring Skill — helps developers set up and troubleshoot agent monitoring.

Provides guidance on CloudWatch metrics, alarms, dashboards, and
operational best practices for agents running on AgentCore.

Uses progressive disclosure: the system prompt tells the agent WHERE to find
monitoring guides, not the guides themselves.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


# MONITORING_PROMPT removed — SKILL.md is the sole prompt source.
class MonitoringSkill(SkillPack):
    """Production monitoring skill for AgentCore deployments."""

    name: str = "monitoring"
    description: str = (
        "Production monitoring specialist for AgentCore deployments: "
        "CloudWatch metrics, alarms, dashboards, operational best practices. "
        "Use when developers need to set up monitoring, configure alerts, "
        "analyze metrics, troubleshoot performance issues, or build dashboards."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Glob", "Grep", "Bash"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("monitoring", MonitoringSkill)
