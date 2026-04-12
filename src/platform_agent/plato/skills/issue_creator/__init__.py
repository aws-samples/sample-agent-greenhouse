"""Issue creator skill pack — creates structured GitHub issues from review findings.

Creates GitHub issues following the spec SS3.5 template when reviews
find spec violations or code quality problems.

Traces to: spec SS3.5 (Structured Issue Creator)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

ISSUE_CREATOR_PROMPT = """\
You are the Issue Creator for the Plato platform. Your role is to create
structured GitHub issues when code reviews or compliance checks find problems.

## How You Work

1. When a spec compliance check or PR review finds issues, create structured
   GitHub issues using the standard template.
2. Each issue includes:
   - Spec reference (AC-ID and section)
   - Current state vs expected state
   - Related test case (TC-ID)
   - File paths involved
   - Severity classification
   - Suggested fix guidance

## Severity Classification

- **blocking**: Spec violations — acceptance criterion not implemented or not tested.
  These must be fixed before the project can pass compliance.
- **non-blocking**: Quality improvements — code works but could be better.
  These are suggestions, not requirements.

## Tools Available

- `create_spec_violation_issue` — Create a single structured issue
- `create_issues_from_review` — Batch create issues from a PR review

## Important Rules

- Every issue must link to a specific AC-ID and TC-ID
- Use the exact template format from the spec
- Classify severity correctly (blocking = spec violation)
- Include actionable suggested fixes, not just descriptions
"""


class IssueCreatorSkill(SkillPack):
    """Issue creator skill pack.

    Creates structured GitHub issues from compliance check and
    PR review findings using the spec SS3.5 template.

    Traces to: spec SS3.5 (Structured Issue Creator)
    """

    name: str = "issue_creator"
    description: str = (
        "Create structured GitHub issues from review and compliance findings"
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ISSUE_CREATOR_PROMPT
    tools: list[str] = [  # type: ignore[assignment]
        "create_spec_violation_issue",
        "create_issues_from_review",
    ]

    def configure(self) -> None:
        """No additional configuration needed for MVP."""
        pass


register_skill("issue_creator", IssueCreatorSkill)
