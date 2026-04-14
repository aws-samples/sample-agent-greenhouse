"""Design Advisor skill pack — platform readiness assessment for agent applications.

Evaluates agent apps against a 12-item platform readiness checklist and provides
actionable recommendations for deployment to Amazon Bedrock AgentCore.

Reference: docs/design/design-advisor-skill.md
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack


# DESIGN_ADVISOR_PROMPT removed — SKILL.md is the sole prompt source.
class DesignAdvisorSkill(SkillPack):
    """Platform readiness assessment skill.

    Augments the Foundation Agent with the ability to evaluate agent applications
    against the platform's deployment readiness checklist (12 checks across
    BLOCKER, WARNING, and INFO severity levels).

    Usage:
        agent = FoundationAgent()
        agent.load_skill(load_skill(DesignAdvisorSkill))
        result = await agent.run("Review the agent app at ./my-agent for platform readiness")
    """

    name: str = "design-advisor"
    description: str = (
        "Reviews agent applications for platform deployment readiness. "
        "Checks containerization, secrets, config, health endpoints, "
        "statefulness, error handling, dependencies, and security."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Glob", "Grep"]  # type: ignore[assignment]

    def configure(self) -> None:
        """No additional configuration needed for MVP.

        Future: could load platform-specific checklist from config file,
        or add MCP tools for automated secret scanning.
        """
        pass


register_skill("design-advisor", DesignAdvisorSkill)
