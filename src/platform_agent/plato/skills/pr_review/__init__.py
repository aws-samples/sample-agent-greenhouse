"""PR review skill pack — reviews GitHub PRs for quality and spec compliance.

Fetches PR diffs, runs code quality checks, and optionally verifies
spec compliance on changed files. Posts structured reviews to GitHub.

Traces to: spec SS3.4 (PR Review Capability)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

# PR_REVIEW_PROMPT removed — SKILL.md is the sole prompt source.
class PRReviewSkill(SkillPack):
    """PR review skill pack.

    Reviews GitHub PRs for code quality and spec compliance,
    posting structured reviews via the GitHub review API.

    Traces to: spec SS3.4 (PR Review Capability)
    """

    name: str = "pr-review"
    description: str = (
        "Review GitHub PRs for code quality and spec compliance"
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = [  # type: ignore[assignment]
        "review_pull_request",
    ]

    def configure(self) -> None:
        """No additional configuration needed for MVP."""
        pass


register_skill("pr-review", PRReviewSkill)
