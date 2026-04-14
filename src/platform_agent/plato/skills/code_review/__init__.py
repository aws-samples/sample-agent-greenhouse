"""Code Review skill pack — quality, security, and best practices review for agent codebases.

Complements the design_advisor skill: while design_advisor checks platform readiness
(containerization, config, health checks), code_review focuses on code quality,
security vulnerabilities, and agent-specific best practices.

Reference: docs/design/design-advisor-skill.md (shares some overlap with security checks)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack


# CODE_REVIEW_PROMPT removed — SKILL.md is the sole prompt source.
class CodeReviewSkill(SkillPack):
    """Code quality and security review skill.

    Augments the Foundation Agent with deep code review capabilities focused on
    security vulnerabilities, agent-specific patterns, and code quality.

    Complements design_advisor: design_advisor checks "is this app ready for
    our platform?", code_review checks "is this code safe and well-written?".

    Usage:
        agent = FoundationAgent()
        agent.load_skill(load_skill(CodeReviewSkill))
        result = await agent.run("Review the code at ./my-agent for security and quality")
    """

    name: str = "code-review"
    description: str = (
        "Reviews agent code for security vulnerabilities, quality issues, "
        "and agent-specific best practices. Checks for prompt injection, "
        "credential exposure, unsafe execution, error handling, and testing."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Glob", "Grep"]  # type: ignore[assignment]

    def configure(self) -> None:
        """No additional configuration needed for MVP.

        Future: could add MCP tools for static analysis (bandit, semgrep),
        dependency vulnerability scanning (pip-audit), and coverage reports.
        """
        pass


register_skill("code-review", CodeReviewSkill)
