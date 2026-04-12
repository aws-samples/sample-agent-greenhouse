"""Strands tools for structured issue creation.

Provides create_spec_violation_issue and create_issues_from_review
as @strands_tool functions for the foundation agent.

Traces to: spec SS3.5 (Structured Issue Creator)
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
def create_spec_violation_issue(
    repo: str,
    ac_id: str,
    current_state: str,
    expected_state: str,
    files: str,
    severity: str = "blocking",
    suggested_fix: str = "",
    section: str = "",
) -> str:
    """Create a structured GitHub issue for a spec violation.

    Creates an issue following the spec SS3.5 template with all required
    fields populated.

    Args:
        repo: Full repo name (e.g. 'org/my-agent').
        ac_id: Acceptance criterion ID (e.g. 'AC-001').
        current_state: What currently exists (or doesn't).
        expected_state: What should exist per the spec.
        files: File paths involved (comma-separated).
        severity: 'blocking' or 'non-blocking'. Default 'blocking'.
        suggested_fix: Brief guidance on how to fix. Optional.
        section: Spec section reference (e.g. '3.3'). Optional.

    Returns:
        JSON string with issue number, URL, and status.

    Traces to: AC-18 (Template compliance), AC-19 (AC/TC linking), AC-20 (Severity)
    """
    from platform_agent.plato.skills.issue_creator.creator import format_issue_body

    valid_severities = {"blocking", "non-blocking"}
    if severity not in valid_severities:
        return json.dumps({
            "status": "error",
            "message": f"Invalid severity '{severity}'. Must be one of: {sorted(valid_severities)}",
        })

    tc_id = ac_id.replace("AC-", "TC-")

    finding = {
        "section": section,
        "ac_id": ac_id,
        "description": expected_state,
        "current_state": current_state,
        "expected_state": expected_state,
        "tc_id": tc_id,
        "files": files,
        "severity": severity,
        "suggested_fix": suggested_fix or f"Implement {ac_id} per spec requirements",
    }

    body = format_issue_body(finding)
    title = f"[{ac_id}] Spec violation: {expected_state[:60]}"
    labels = ["spec-violation", severity]

    try:
        from platform_agent.foundation.tools.github import (
            github_create_issue,
        )
        result_json = github_create_issue(
            repo=repo,
            title=title,
            body=body,
            labels=labels,
        )
        return result_json
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to create issue: {e}",
        })


@strands_tool
def create_issues_from_review(
    repo: str,
    review_json: str,
) -> str:
    """Batch create GitHub issues from a PR review result's findings.

    Takes the JSON output from review_pull_request and creates
    individual issues for each blocking code issue found.

    Args:
        repo: Full repo name (e.g. 'org/my-agent').
        review_json: JSON string from review_pull_request tool output.

    Returns:
        JSON string with list of created issues and counts.
    """
    try:
        review_data = json.loads(review_json)
    except (json.JSONDecodeError, TypeError) as e:
        return json.dumps({
            "status": "error",
            "message": f"Invalid review JSON: {e}",
        })

    code_issues = review_data.get("code_issues", [])
    if not code_issues:
        return json.dumps({
            "status": "ok",
            "message": "No code issues to create issues for",
            "created": 0,
        })

    from platform_agent.plato.skills.issue_creator.creator import format_issue_body

    created_issues: list[dict] = []
    errors: list[str] = []

    for issue in code_issues:
        severity = issue.get("severity", "non-blocking")
        file_path = issue.get("file", "unknown")
        line = issue.get("line", "")
        description = issue.get("description", "Code quality issue")
        suggestion = issue.get("suggestion", "")

        finding = {
            "section": "",
            "ac_id": "CODE-QUALITY",
            "description": description,
            "current_state": f"Issue found at {file_path}:{line}",
            "expected_state": suggestion or description,
            "tc_id": "N/A",
            "files": file_path,
            "severity": severity,
            "suggested_fix": suggestion,
        }

        body = format_issue_body(finding)
        title = f"[Code Review] {description[:60]}"
        labels = ["code-review", severity]

        try:
            from platform_agent.foundation.tools.github import (
                github_create_issue,
            )
            result_json = github_create_issue(
                repo=repo,
                title=title,
                body=body,
                labels=labels,
            )
            result_data = json.loads(result_json)
            created_issues.append({
                "number": result_data.get("number"),
                "url": result_data.get("url"),
                "title": title,
            })
        except Exception as e:
            errors.append(f"Failed to create issue for '{description}': {e}")

    return json.dumps({
        "status": "ok",
        "created": len(created_issues),
        "issues": created_issues,
        "errors": errors,
    })


ISSUE_CREATOR_TOOLS = [
    create_spec_violation_issue,
    create_issues_from_review,
]
