"""Knowledge skill — platform documentation and best practices lookup.

Provides the agent with searchable platform knowledge: readiness checklist,
deployment patterns, troubleshooting guides, and architecture decisions.

Uses progressive disclosure: SKILL.md has the workflow, references/ has the
detailed docs that get loaded only when needed.
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack


# KNOWLEDGE_PROMPT removed — SKILL.md is the sole prompt source.
class KnowledgeSkill(SkillPack):
    """Platform knowledge and documentation lookup skill.

    Augments the Foundation Agent with access to platform documentation,
    best practices, and troubleshooting guides. Uses progressive disclosure —
    reference files are loaded on demand, not all at once.

    Usage:
        agent = FoundationAgent()
        agent.load_skill(load_skill(KnowledgeSkill))
        result = await agent.run("What are the C1-C12 readiness checks?")
    """

    name: str = "knowledge"
    description: str = (
        "Platform knowledge base: readiness requirements (C1-C12), "
        "deployment patterns, agent architecture patterns, and "
        "troubleshooting guides. Use when developers ask about platform "
        "capabilities, best practices, requirements, how to deploy, "
        "what is needed, or need help debugging deployment issues."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Glob", "Grep"]  # type: ignore[assignment]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


register_skill("knowledge", KnowledgeSkill)
