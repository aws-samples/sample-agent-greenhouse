"""PR review skill pack — reviews GitHub PRs for quality and spec compliance.

Fetches PR diffs, runs code quality checks, and optionally verifies
spec compliance on changed files. Posts structured reviews to GitHub.

Traces to: spec SS3.4 (PR Review Capability)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

PR_REVIEW_PROMPT = """\
You are the PR Review Agent for the Plato platform. Your role is to review
GitHub pull requests for code quality and spec compliance.

## How You Work

1. Fetch the PR diff and list of changed files.
2. Run code quality checks:
   - Bare `except:` clauses (blocking)
   - TODO comments without linked issues (non-blocking)
   - Hardcoded secrets or credentials (blocking)
   - Missing docstrings on new functions/classes (non-blocking)
3. If a spec.md path is provided, run spec compliance checks on the changed code.
4. Determine verdict:
   - **APPROVE**: No issues found
   - **REQUEST_CHANGES**: Blocking issues or spec violations found
   - **COMMENT**: Only non-blocking suggestions
5. Post the review to GitHub via the review API.

## Tools Available

- `review_pull_request` — Full PR review with optional spec compliance

## Important Rules

- Always post structured feedback, not freeform prose
- Blocking issues must be fixed before merge
- Non-blocking issues are suggestions for improvement
- Include file:line references for every issue
"""


class PRReviewSkill(SkillPack):
    """PR review skill pack.

    Reviews GitHub PRs for code quality and spec compliance,
    posting structured reviews via the GitHub review API.

    Traces to: spec SS3.4 (PR Review Capability)
    """

    name: str = "pr_review"
    description: str = (
        "Review GitHub PRs for code quality and spec compliance"
    )
    version: str = "0.1.0"
    system_prompt_extension: str = PR_REVIEW_PROMPT
    tools: list[str] = [  # type: ignore[assignment]
        "review_pull_request",
    ]

    def configure(self) -> None:
        """No additional configuration needed for MVP."""
        pass


register_skill("pr_review", PRReviewSkill)
