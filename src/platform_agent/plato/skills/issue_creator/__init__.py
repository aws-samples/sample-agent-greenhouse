"""Issue creator skill pack — creates structured GitHub issues from review findings.

Creates GitHub issues following the spec SS3.5 template when reviews
find spec violations or code quality problems.

Traces to: spec SS3.5 (Structured Issue Creator)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

# ISSUE_CREATOR_PROMPT removed — SKILL.md is the sole prompt source.
class IssueCreatorSkill(SkillPack):
    """Issue creator skill pack.

    Creates structured GitHub issues from compliance check and
    PR review findings using the spec SS3.5 template.

    Traces to: spec SS3.5 (Structured Issue Creator)
    """

    name: str = "issue-creator"
    description: str = (
        "Create structured GitHub issues from review and compliance findings"
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = [  # type: ignore[assignment]
        "create_spec_violation_issue",
        "create_issues_from_review",
    ]

    def configure(self) -> None:
        """No additional configuration needed for MVP."""
        pass


register_skill("issue-creator", IssueCreatorSkill)
