"""Structured GitHub issue creator — creates issues from compliance findings.

Formats issues using the spec SS3.5 template and creates them via the
GitHub API. Supports both individual and batch issue creation.

Traces to: spec SS3.5 (Structured Issue Creator)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from platform_agent.plato.skills.spec_compliance.checker import ComplianceReport

logger = logging.getLogger(__name__)

# Issue body template from spec SS3.5
_ISSUE_TEMPLATE = """\
## Spec Violation

**Spec Reference:** spec.md SS{section} — {ac_id}: "{description}"
**Current State:** {current_state}
**Expected State:** {expected_state}
**Relevant Test:** test-cases.md {tc_id}
**Files:** {files}
**Severity:** {severity}
**Suggested Fix:** {suggested_fix}
"""


@dataclass(frozen=True)
class IssueResult:
    """Result of creating a single GitHub issue.

    Attributes:
        ac_id: Acceptance criterion ID this issue relates to.
        issue_number: GitHub issue number (0 if creation failed).
        issue_url: GitHub issue URL (empty if creation failed).
        title: Issue title.
        success: Whether the issue was created successfully.
        error: Error message if creation failed.
    """

    ac_id: str
    issue_number: int = 0
    issue_url: str = ""
    title: str = ""
    success: bool = True
    error: str = ""


def format_issue_body(finding: dict[str, str]) -> str:
    """Format an issue body from a finding dict using the spec template.

    Args:
        finding: Dict with keys: section, ac_id, description, current_state,
                 expected_state, tc_id, files, severity, suggested_fix.

    Returns:
        Formatted markdown issue body.

    Traces to: AC-18 (Issues follow the template exactly)
    """
    return _ISSUE_TEMPLATE.format(
        section=finding.get("section", ""),
        ac_id=finding.get("ac_id", ""),
        description=finding.get("description", ""),
        current_state=finding.get("current_state", "Not found in codebase"),
        expected_state=finding.get("expected_state", ""),
        tc_id=finding.get("tc_id", finding.get("ac_id", "").replace("AC-", "TC-")),
        files=finding.get("files", "N/A"),
        severity=finding.get("severity", "blocking"),
        suggested_fix=finding.get("suggested_fix", ""),
    )


def categorize_severity(entry_status: str, has_test: bool) -> str:
    """Categorize severity based on compliance status.

    Args:
        entry_status: Compliance status ("PASS", "PARTIAL", "NOT_FOUND").
        has_test: Whether a test exists for this criterion.

    Returns:
        "blocking" for spec violations, "non-blocking" for quality improvements.

    Traces to: AC-20 (Severity correctly categorized)
    """
    if entry_status == "NOT_FOUND":
        return "blocking"
    if entry_status == "PARTIAL" and not has_test:
        return "blocking"
    return "non-blocking"


def create_issues_from_compliance(
    repo: str,
    compliance_report: ComplianceReport,
    spec_content: str,
    *,
    _github_create_issue: object | None = None,
) -> list[IssueResult]:
    """Create GitHub issues for failing/partial compliance entries.

    For each FAIL or PARTIAL entry in the compliance report, creates
    a structured GitHub issue following the spec SS3.5 template.

    Args:
        repo: Full repository name (e.g. "org/repo").
        compliance_report: The compliance report to process.
        spec_content: Raw spec.md content (for section references).
        _github_create_issue: Optional override for testing.

    Returns:
        List of IssueResult objects.

    Traces to: AC-18, AC-19, AC-20
    """
    create_issue = _github_create_issue or _import_github_create_issue()

    results: list[IssueResult] = []
    for entry in compliance_report.entries:
        if entry.status == "PASS":
            continue

        severity = categorize_severity(entry.status, entry.test_exists)
        tc_id = entry.ac_id.replace("AC-", "TC-")

        finding = {
            "section": entry.section,
            "ac_id": entry.ac_id,
            "description": entry.description,
            "current_state": _describe_current_state(entry),
            "expected_state": entry.description,
            "tc_id": tc_id,
            "files": entry.impl_file or "N/A",
            "severity": severity,
            "suggested_fix": _suggest_fix(entry),
        }

        body = format_issue_body(finding)
        title = f"[{entry.ac_id}] Spec violation: {entry.description[:60]}"
        labels = ["spec-violation", severity]

        try:
            result_json = create_issue(
                repo=repo,
                title=title,
                body=body,
                labels=labels,
            )
            result_data = json.loads(result_json)
            results.append(IssueResult(
                ac_id=entry.ac_id,
                issue_number=result_data.get("number", 0),
                issue_url=result_data.get("url", ""),
                title=title,
                success=result_data.get("status") == "created",
                error="" if result_data.get("status") == "created" else result_data.get("message", ""),
            ))
        except Exception as e:
            logger.error("Failed to create issue for %s: %s", entry.ac_id, e)
            results.append(IssueResult(
                ac_id=entry.ac_id,
                title=title,
                success=False,
                error=str(e),
            ))

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _import_github_create_issue():
    """Lazy-import github_create_issue."""
    from platform_agent.foundation.tools.github import github_create_issue
    return github_create_issue


def _describe_current_state(entry) -> str:
    """Describe the current state of a compliance entry.

    Args:
        entry: ComplianceEntry to describe.

    Returns:
        Human-readable description of the current state.
    """
    if not entry.implemented and not entry.test_exists:
        return "No implementation or test evidence found in codebase"
    if entry.implemented and not entry.test_exists:
        return f"Implementation found at {entry.impl_file}:{entry.impl_line} but no test coverage"
    if not entry.implemented and entry.test_exists:
        return f"Test found at {entry.test_file} but no implementation evidence"
    return "Partial evidence found"


def _suggest_fix(entry) -> str:
    """Generate a fix suggestion for a compliance entry.

    Args:
        entry: ComplianceEntry to generate a suggestion for.

    Returns:
        Suggested fix guidance.
    """
    if not entry.implemented and not entry.test_exists:
        return (
            f"Implement {entry.ac_id} and add a test case "
            f"{entry.ac_id.replace('AC-', 'TC-')} with a 'Traces to: {entry.ac_id}' comment"
        )
    if entry.implemented and not entry.test_exists:
        return (
            f"Add test case {entry.ac_id.replace('AC-', 'TC-')} covering {entry.ac_id}"
        )
    if not entry.implemented and entry.test_exists:
        return (
            f"Add a 'Traces to: {entry.ac_id}' comment to the implementation code"
        )
    return f"Review compliance for {entry.ac_id}"
