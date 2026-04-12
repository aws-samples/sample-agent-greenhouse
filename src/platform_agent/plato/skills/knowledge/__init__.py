"""Knowledge skill — platform documentation and best practices lookup.

Provides the agent with searchable platform knowledge: readiness checklist,
deployment patterns, troubleshooting guides, and architecture decisions.

Uses progressive disclosure: SKILL.md has the workflow, references/ has the
detailed docs that get loaded only when needed.
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack


KNOWLEDGE_PROMPT = """\
You have access to platform knowledge documentation. When a developer asks
about platform capabilities, best practices, or troubleshooting, consult
the relevant reference docs.

## Available Knowledge

Reference files are in the knowledge skill's `references/` directory.
Read the relevant file when you need detailed information:

- **readiness-checklist.md** — Full C1-C12 platform readiness checklist with
  definitions, examples, and auto-fix suggestions. Read when assessing or
  explaining readiness requirements.

- **deployment-patterns.md** — Deployment architecture patterns for AgentCore:
  single agent, multi-agent, sidecar, event-driven. Read when helping with
  deployment design or comparing approaches.

- **troubleshooting.md** — Common deployment failures, error messages, and
  fixes. Read when a developer reports an error or deployment issue.

- **agent-patterns.md** — Agent architecture patterns: tool-use, RAG,
  multi-agent orchestration, human-in-the-loop. Read when advising on
  agent design choices.

## Workflow

1. Identify what the developer needs (readiness info, deployment help,
   debugging, architecture advice)
2. Read the relevant reference file(s)
3. Answer using the reference content + your own knowledge
4. Cite the reference when quoting specific requirements or patterns

## Guidelines

- Don't guess — if the answer is in a reference file, read it first
- Be specific: cite checklist items (C1-C12), pattern names, error codes
- If multiple references are relevant, read the most specific one first
- For questions not covered by references, use your general knowledge
  but note that it's not from platform docs
"""


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
    system_prompt_extension: str = KNOWLEDGE_PROMPT
    tools: list[str] = ["Read", "Glob", "Grep"]  # type: ignore[assignment]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


register_skill("knowledge", KnowledgeSkill)
