"""PR reviewer — analyses GitHub PRs for code quality and spec compliance.

Fetches PR diffs, runs code quality checks, and optionally integrates
spec compliance checking for changed files.

Traces to: spec SS3.4 (PR Review Capability)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from platform_agent.plato.skills.spec_compliance.checker import (
    ComplianceReport,
    SpecComplianceChecker,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodeIssue:
    """A code quality issue found during PR review.

    Attributes:
        file: File path where the issue was found.
        line: Line number (as string, may be approximate).
        severity: "blocking" or "non-blocking".
        description: What the issue is.
        suggestion: How to fix it.
    """

    file: str
    line: str
    severity: str  # "blocking" | "non-blocking"
    description: str
    suggestion: str


@dataclass
class PRReviewResult:
    """Structured result of a PR review.

    Attributes:
        overall_status: "APPROVE", "REQUEST_CHANGES", or "COMMENT".
        spec_compliance: Optional spec compliance report (if spec was provided).
        code_issues: List of code quality issues found.
        summary: Human-readable summary of the review.
    """

    overall_status: str  # "APPROVE" | "REQUEST_CHANGES" | "COMMENT"
    spec_compliance: ComplianceReport | None = None
    code_issues: list[CodeIssue] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Code quality patterns
# ---------------------------------------------------------------------------

_BARE_EXCEPT_PATTERN = re.compile(r"^\+\s*except\s*:", re.MULTILINE)
_TODO_NO_ISSUE_PATTERN = re.compile(r"^\+.*#\s*TODO(?!\s*\(#\d+\))(?!\s*\(https?://)", re.MULTILINE)
_HARDCODED_SECRET_PATTERNS = [
    re.compile(r'^\+.*(?:password|secret|api_key|apikey|token)\s*=\s*["\'][^"\']{8,}', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\+.*(?:ghp_|sk-|AKIA)[A-Za-z0-9]{10,}', re.MULTILINE),
]
_MISSING_DOCSTRING_PATTERN = re.compile(
    r'^\+\s*(?:def|class)\s+\w+[^#\n]*:\s*\n(?!\+\s*"""|\+\s*\'\'\')',
    re.MULTILINE,
)


class PRReviewer:
    """Reviews GitHub PRs for code quality and spec compliance.

    Args:
        github_get_pr_diff: Optional override for the diff fetcher (for testing).
        github_list_pr_files: Optional override for the file lister (for testing).
        github_get_file: Optional override for the file reader (for testing).
    """

    def __init__(
        self,
        *,
        github_get_pr_diff: object | None = None,
        github_list_pr_files: object | None = None,
        github_get_file: object | None = None,
    ) -> None:
        self._get_pr_diff = github_get_pr_diff or _import_get_pr_diff()
        self._list_pr_files = github_list_pr_files or _import_list_pr_files()
        self._get_file = github_get_file or _import_get_file()

    def review_pr(
        self,
        repo: str,
        pr_number: int,
        spec_content: str | None = None,
    ) -> PRReviewResult:
        """Review a GitHub PR.

        Fetches the PR diff and changed files, runs code quality checks,
        and optionally runs spec compliance on changed files.

        Args:
            repo: Full repository name (e.g. "org/repo").
            pr_number: The pull request number.
            spec_content: Optional spec.md content for compliance checking.

        Returns:
            PRReviewResult with overall status, issues, and optional compliance.

        Traces to: AC-14 (Fetch/parse diffs), AC-16 (Spec compliance in review),
                   AC-17 (Blocking vs non-blocking)
        """
        # Fetch diff and file list
        diff_text = self._get_pr_diff(repo=repo, pr_number=pr_number)
        files_json = self._list_pr_files(repo=repo, pr_number=pr_number)
        files_data = json.loads(files_json)
        changed_files = files_data.get("files", [])

        # Run code quality checks on the diff
        code_issues = self._check_code_quality(diff_text, changed_files)

        # Run spec compliance if spec provided
        compliance_report: ComplianceReport | None = None
        if spec_content:
            checker = SpecComplianceChecker(spec_content)

            # Build a tree function from changed files so compliance checker
            # scans only the PR's changed files instead of hitting the real API.
            def _pr_tree(
                repo: str, path: str = "", branch: str = "main"
            ) -> str:
                if path == "":
                    entries = [
                        {
                            "name": f.get("filename", "").rsplit("/", 1)[-1],
                            "type": "file",
                            "path": f["filename"],
                            "size": 0,
                        }
                        for f in changed_files
                    ]
                    return json.dumps(
                        {"entries": entries, "count": len(entries)}
                    )
                return json.dumps({"entries": [], "count": 0})

            compliance_report = checker.check_compliance(
                repo=repo,
                branch="main",
                _github_get_tree=_pr_tree,
                _github_get_file=self._get_file,
            )

        # Determine overall status
        overall_status = self._determine_verdict(code_issues, compliance_report)

        # Build summary
        summary = self._build_summary(
            code_issues, compliance_report, changed_files
        )

        return PRReviewResult(
            overall_status=overall_status,
            spec_compliance=compliance_report,
            code_issues=code_issues,
            summary=summary,
        )

    def _check_code_quality(
        self,
        diff_text: str,
        changed_files: list[dict],
    ) -> list[CodeIssue]:
        """Run code quality checks on the PR diff.

        Args:
            diff_text: The unified diff text.
            changed_files: List of changed file dicts from the API.

        Returns:
            List of CodeIssue objects found.
        """
        issues: list[CodeIssue] = []

        # Parse diff into per-file sections
        file_diffs = _split_diff_by_file(diff_text)

        for filename, file_diff in file_diffs.items():
            # Bare except
            for match in _BARE_EXCEPT_PATTERN.finditer(file_diff):
                line_num = _estimate_line_number(file_diff, match.start())
                issues.append(CodeIssue(
                    file=filename,
                    line=str(line_num),
                    severity="blocking",
                    description="Bare `except:` clause — must catch specific exceptions",
                    suggestion="Replace with `except SpecificException:` or at minimum `except Exception:`",
                ))

            # TODO without issue link
            for match in _TODO_NO_ISSUE_PATTERN.finditer(file_diff):
                line_num = _estimate_line_number(file_diff, match.start())
                issues.append(CodeIssue(
                    file=filename,
                    line=str(line_num),
                    severity="non-blocking",
                    description="TODO comment without linked issue number",
                    suggestion="Add issue reference: `# TODO(#123) description`",
                ))

            # Hardcoded secrets
            for pattern in _HARDCODED_SECRET_PATTERNS:
                for match in pattern.finditer(file_diff):
                    line_num = _estimate_line_number(file_diff, match.start())
                    issues.append(CodeIssue(
                        file=filename,
                        line=str(line_num),
                        severity="blocking",
                        description="Possible hardcoded secret or credential",
                        suggestion="Use environment variables or a secret manager",
                    ))

            # Missing docstring on new functions/classes (Python files only)
            if filename.endswith(".py"):
                for match in _MISSING_DOCSTRING_PATTERN.finditer(file_diff):
                    line_num = _estimate_line_number(file_diff, match.start())
                    issues.append(CodeIssue(
                        file=filename,
                        line=str(line_num),
                        severity="non-blocking",
                        description="New function/class missing docstring",
                        suggestion="Add a Google-style docstring",
                    ))

        return issues

    def _determine_verdict(
        self,
        code_issues: list[CodeIssue],
        compliance_report: ComplianceReport | None,
    ) -> str:
        """Determine the overall review verdict.

        Args:
            code_issues: List of code quality issues.
            compliance_report: Optional compliance report.

        Returns:
            "APPROVE", "REQUEST_CHANGES", or "COMMENT".

        Traces to: AC-17 (Blocking vs non-blocking distinction)
        """
        has_blocking = any(
            issue.severity == "blocking" for issue in code_issues
        )

        # Check for spec failures
        has_spec_failures = False
        if compliance_report:
            has_spec_failures = compliance_report.summary.get("NOT_FOUND", 0) > 0

        if has_blocking:
            return "REQUEST_CHANGES"
        if has_spec_failures:
            return "REQUEST_CHANGES"
        if code_issues:
            return "COMMENT"
        return "APPROVE"

    def _build_summary(
        self,
        code_issues: list[CodeIssue],
        compliance_report: ComplianceReport | None,
        changed_files: list[dict],
    ) -> str:
        """Build a human-readable review summary.

        Args:
            code_issues: List of code quality issues.
            compliance_report: Optional compliance report.
            changed_files: List of changed file dicts.

        Returns:
            Markdown summary string.
        """
        lines: list[str] = [
            "## PR Review Summary",
            "",
            f"**Files changed:** {len(changed_files)}",
        ]

        if code_issues:
            blocking = sum(1 for i in code_issues if i.severity == "blocking")
            non_blocking = len(code_issues) - blocking
            lines.append(
                f"**Code issues:** {blocking} blocking, {non_blocking} non-blocking"
            )
        else:
            lines.append("**Code issues:** None found")

        if compliance_report:
            lines.append("")
            lines.append("### Spec Compliance")
            lines.append(
                f"- PASS: {compliance_report.summary.get('PASS', 0)}"
            )
            lines.append(
                f"- PARTIAL: {compliance_report.summary.get('PARTIAL', 0)}"
            )
            lines.append(
                f"- NOT_FOUND: {compliance_report.summary.get('NOT_FOUND', 0)}"
            )

        if code_issues:
            lines.append("")
            lines.append("### Code Issues")
            for issue in code_issues:
                severity_marker = "**BLOCKING**" if issue.severity == "blocking" else "note"
                lines.append(
                    f"- [{severity_marker}] {issue.file}:{issue.line} — {issue.description}"
                )

        return "\n".join(lines)

    def format_review_body(self, result: PRReviewResult) -> str:
        """Format a PRReviewResult as a GitHub review body.

        Args:
            result: The review result to format.

        Returns:
            Markdown string suitable for posting as a GitHub PR review.
        """
        return result.summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _import_get_pr_diff():
    """Lazy-import github_get_pr_diff."""
    from platform_agent.foundation.tools.github import github_get_pr_diff
    return github_get_pr_diff


def _import_list_pr_files():
    """Lazy-import github_list_pr_files."""
    from platform_agent.foundation.tools.github import github_list_pr_files
    return github_list_pr_files


def _import_get_file():
    """Lazy-import github_get_file."""
    from platform_agent.foundation.tools.github import github_get_file
    return github_get_file


def _split_diff_by_file(diff_text: str) -> dict[str, str]:
    """Split a unified diff into per-file sections.

    Args:
        diff_text: Full unified diff text.

    Returns:
        Dict mapping filename to that file's diff section.
    """
    file_diffs: dict[str, str] = {}
    current_file: str | None = None
    current_lines: list[str] = []

    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            if current_file and current_lines:
                file_diffs[current_file] = "\n".join(current_lines)
            # Extract filename from "diff --git a/path b/path"
            parts = line.split(" b/", 1)
            current_file = parts[1] if len(parts) > 1 else None
            current_lines = [line]
        elif current_file is not None:
            current_lines.append(line)

    if current_file and current_lines:
        file_diffs[current_file] = "\n".join(current_lines)

    return file_diffs


def _estimate_line_number(diff_section: str, match_pos: int) -> int:
    """Estimate the line number from a position in a diff section.

    Uses @@ hunk headers to track line numbers.

    Args:
        diff_section: The diff text for a single file.
        match_pos: Character position of the match.

    Returns:
        Estimated line number in the new file.
    """
    lines_before = diff_section[:match_pos].split("\n")
    current_line = 1

    hunk_pattern = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)")
    for line in lines_before:
        hunk_match = hunk_pattern.search(line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            current_line += 1
        elif not line.startswith("-") and not line.startswith("---"):
            current_line += 1

    return current_line
