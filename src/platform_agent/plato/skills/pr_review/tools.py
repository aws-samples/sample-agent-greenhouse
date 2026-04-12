"""Strands tools for PR review.

Provides review_pull_request as a @strands_tool function
for the foundation agent.

Traces to: spec SS3.4 (PR Review Capability)
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

try:
    from strands import tool as strands_tool

    _HAS_STRANDS = True
except ImportError:
    _HAS_STRANDS = False
    import functools

    def strands_tool(fn):  # type: ignore[misc]
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper


@strands_tool
def review_pull_request(
    repo: str,
    pr_number: int,
    spec_path: str = "",
    post_review: bool = True,
) -> str:
    """Review a GitHub PR for code quality and spec compliance.

    Fetches the PR diff and changed files, analyses code quality,
    and optionally checks spec compliance. If post_review is True,
    posts the review to GitHub via the review API.

    Args:
        repo: Full repo name (e.g. 'org/my-agent').
        pr_number: The pull request number.
        spec_path: Path to spec.md in the repo for compliance check.
                   Empty string to skip spec compliance.
        post_review: Whether to post the review to GitHub. Default True.

    Returns:
        JSON string with review result including verdict and issues.

    Traces to: AC-14 (Fetch PR diffs), AC-15 (Post review via API),
               AC-16 (Spec compliance in review), AC-17 (Blocking distinction)
    """
    from platform_agent.plato.skills.pr_review.reviewer import PRReviewer

    spec_content: str | None = None
    if spec_path:
        try:
            from platform_agent.foundation.tools.github import (
                github_get_file,
            )
            spec_content = github_get_file(
                repo=repo, path=spec_path, branch="main"
            )
        except Exception as e:
            logger.warning("Could not read spec at %s: %s", spec_path, e)

    reviewer = PRReviewer()
    result = reviewer.review_pr(
        repo=repo, pr_number=pr_number, spec_content=spec_content
    )

    # Post review to GitHub if requested
    if post_review:
        try:
            from platform_agent.foundation.tools.github import (
                github_create_review,
            )
            review_body = reviewer.format_review_body(result)
            github_create_review(
                repo=repo,
                pr_number=pr_number,
                body=review_body,
                event=result.overall_status,
            )
        except Exception as e:
            logger.error("Failed to post review to GitHub: %s", e)
            return json.dumps({
                "status": "review_complete_post_failed",
                "overall_status": result.overall_status,
                "code_issues_count": len(result.code_issues),
                "summary": result.summary,
                "post_error": str(e),
            })

    # Build response
    code_issues_list = [
        {
            "file": issue.file,
            "line": issue.line,
            "severity": issue.severity,
            "description": issue.description,
            "suggestion": issue.suggestion,
        }
        for issue in result.code_issues
    ]

    response: dict = {
        "status": "review_complete",
        "overall_status": result.overall_status,
        "code_issues": code_issues_list,
        "code_issues_count": len(code_issues_list),
        "posted_to_github": post_review,
        "summary": result.summary,
    }

    if result.spec_compliance:
        response["spec_compliance_summary"] = result.spec_compliance.summary

    return json.dumps(response)


PR_REVIEW_TOOLS = [
    review_pull_request,
]
