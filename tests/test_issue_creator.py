"""Tests for the issue creator skill.

Covers issue body formatting, AC/TC reference linking, severity categorization,
and batch issue creation.

Traces to: spec SS3.5 — AC-18, AC-19, AC-20
"""

from __future__ import annotations

import json

import pytest

from platform_agent.plato.skills.issue_creator import IssueCreatorSkill, register_skill
from platform_agent.plato.skills.issue_creator.creator import (
    IssueResult,
    categorize_severity,
    create_issues_from_compliance,
    format_issue_body,
)
from platform_agent.plato.skills.issue_creator.tools import (
    ISSUE_CREATOR_TOOLS,
    create_issues_from_review,
    create_spec_violation_issue,
)
from platform_agent.plato.skills.spec_compliance.checker import (
    ComplianceEntry,
    ComplianceReport,
)
from platform_agent.plato.skills.base import SkillPack, load_skill


# ---------------------------------------------------------------------------
# Mock GitHub helpers
# ---------------------------------------------------------------------------


def _mock_create_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> str:
    """Mock github_create_issue that returns a success response."""
    return json.dumps({
        "status": "created",
        "number": 42,
        "url": f"https://github.com/{repo}/issues/42",
        "title": title,
    })


_issue_counter = 0


def _mock_create_issue_sequential(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> str:
    """Mock that returns incrementing issue numbers."""
    global _issue_counter
    _issue_counter += 1
    return json.dumps({
        "status": "created",
        "number": _issue_counter,
        "url": f"https://github.com/{repo}/issues/{_issue_counter}",
        "title": title,
    })


def _mock_create_issue_failing(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> str:
    """Mock that raises an error."""
    raise RuntimeError("GitHub API 500: Internal Server Error")


# ---------------------------------------------------------------------------
# Skill registration and metadata
# ---------------------------------------------------------------------------


class TestSkillRegistration:
    """Tests for issue creator skill registration and metadata."""

    def test_skill_is_skillpack_subclass(self) -> None:
        """IssueCreatorSkill is a SkillPack subclass."""
        assert issubclass(IssueCreatorSkill, SkillPack)

    def test_skill_name(self) -> None:
        """Skill name is 'issue-creator'."""
        skill = IssueCreatorSkill()
        assert skill.name == "issue-creator"

    def test_skill_has_system_prompt(self) -> None:
        """Skill has system_prompt_extension cleared (SKILL.md is sole source)."""
        skill = IssueCreatorSkill()
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        assert skill.system_prompt_extension == ""

    def test_skill_tools_list(self) -> None:
        """Skill references both issue creator tools."""
        skill = IssueCreatorSkill()
        assert "create_spec_violation_issue" in skill.tools
        assert "create_issues_from_review" in skill.tools

    def test_load_skill(self) -> None:
        """load_skill creates a configured instance."""
        skill = load_skill(IssueCreatorSkill)
        assert skill.name == "issue-creator"

    def test_skill_registered_in_registry(self) -> None:
        """Skill is available via the registry."""
        from platform_agent.plato.skills import get_skill
        cls = get_skill("issue-creator")
        assert cls is IssueCreatorSkill

    def test_tools_list_has_all_tools(self) -> None:
        """ISSUE_CREATOR_TOOLS contains both tool functions."""
        assert len(ISSUE_CREATOR_TOOLS) == 2


# ---------------------------------------------------------------------------
# Issue body formatting (AC-18)
# ---------------------------------------------------------------------------


class TestIssueBodyFormatting:
    """Tests for issue body formatting.

    Traces to: AC-18 (Issues follow the template exactly, all fields populated)
    """

    def test_format_includes_all_template_fields(self) -> None:
        """Formatted body includes all required template fields."""
        finding = {
            "section": "3.3",
            "ac_id": "AC-001",
            "description": "User can submit a ticket",
            "current_state": "Not implemented",
            "expected_state": "API endpoint for ticket submission",
            "tc_id": "TC-001",
            "files": "src/agent.py",
            "severity": "blocking",
            "suggested_fix": "Add a POST /tickets endpoint",
        }
        body = format_issue_body(finding)

        assert "## Spec Violation" in body
        assert "**Spec Reference:**" in body
        assert "AC-001" in body
        assert "**Current State:**" in body
        assert "Not implemented" in body
        assert "**Expected State:**" in body
        assert "**Relevant Test:**" in body
        assert "TC-001" in body
        assert "**Files:**" in body
        assert "src/agent.py" in body
        assert "**Severity:**" in body
        assert "blocking" in body
        assert "**Suggested Fix:**" in body
        assert "POST /tickets" in body

    def test_format_includes_section_reference(self) -> None:
        """Formatted body includes the spec section reference."""
        finding = {
            "section": "3.3",
            "ac_id": "AC-010",
            "description": "Test criterion",
        }
        body = format_issue_body(finding)
        assert "SS3.3" in body

    def test_format_auto_generates_tc_id(self) -> None:
        """TC-ID is auto-generated from AC-ID if not provided."""
        finding = {
            "ac_id": "AC-015",
            "description": "Some criterion",
        }
        body = format_issue_body(finding)
        assert "TC-015" in body

    def test_format_handles_empty_fields(self) -> None:
        """Formatting works with minimal/empty fields."""
        finding = {
            "ac_id": "AC-001",
            "description": "Minimal",
        }
        body = format_issue_body(finding)
        assert "AC-001" in body
        assert "## Spec Violation" in body


# ---------------------------------------------------------------------------
# AC/TC reference linking (AC-19)
# ---------------------------------------------------------------------------


class TestACTCLinking:
    """Tests for AC/TC reference linking.

    Traces to: AC-19 (Each issue links to specific AC-ID and TC-ID)
    """

    def test_issue_links_ac_and_tc(self) -> None:
        """Issue body contains both AC-ID and corresponding TC-ID."""
        finding = {
            "section": "3.1",
            "ac_id": "AC-005",
            "description": "Auth works",
            "tc_id": "TC-005",
        }
        body = format_issue_body(finding)
        assert "AC-005" in body
        assert "TC-005" in body

    def test_tc_id_derived_from_ac_id(self) -> None:
        """TC-ID is correctly derived from AC-ID."""
        finding = {"ac_id": "AC-123"}
        body = format_issue_body(finding)
        assert "TC-123" in body


# ---------------------------------------------------------------------------
# Severity categorization (AC-20)
# ---------------------------------------------------------------------------


class TestSeverityCategorization:
    """Tests for severity categorization.

    Traces to: AC-20 (blocking = spec violation, non-blocking = quality improvement)
    """

    def test_not_found_is_blocking(self) -> None:
        """NOT_FOUND status is classified as blocking."""
        assert categorize_severity("NOT_FOUND", has_test=False) == "blocking"

    def test_not_found_still_blocking_with_test(self) -> None:
        """NOT_FOUND is blocking even if test somehow exists."""
        assert categorize_severity("NOT_FOUND", has_test=True) == "blocking"

    def test_partial_no_test_is_blocking(self) -> None:
        """PARTIAL without test is blocking (missing test coverage)."""
        assert categorize_severity("PARTIAL", has_test=False) == "blocking"

    def test_partial_with_test_is_non_blocking(self) -> None:
        """PARTIAL with test is non-blocking (quality improvement)."""
        assert categorize_severity("PARTIAL", has_test=True) == "non-blocking"

    def test_pass_is_non_blocking(self) -> None:
        """PASS status is non-blocking."""
        assert categorize_severity("PASS", has_test=True) == "non-blocking"


# ---------------------------------------------------------------------------
# Batch issue creation from compliance report
# ---------------------------------------------------------------------------


class TestBatchIssueCreation:
    """Tests for batch issue creation from compliance reports."""

    @pytest.fixture(autouse=True)
    def _reset_counter(self) -> None:
        """Reset the global issue counter."""
        global _issue_counter
        _issue_counter = 0

    def test_creates_issues_for_non_pass_entries(self) -> None:
        """Issues are created for PARTIAL and NOT_FOUND entries, not PASS."""
        report = ComplianceReport(
            entries=[
                ComplianceEntry(
                    ac_id="AC-001", description="Passing", status="PASS",
                    implemented=True, test_exists=True,
                    impl_file="src/a.py", test_file="tests/test_a.py",
                ),
                ComplianceEntry(
                    ac_id="AC-002", description="Missing", status="NOT_FOUND",
                ),
                ComplianceEntry(
                    ac_id="AC-003", description="Partial", status="PARTIAL",
                    implemented=True, impl_file="src/b.py",
                ),
            ],
            repo="org/repo",
        )
        report.compute_summary()

        results = create_issues_from_compliance(
            repo="org/repo",
            compliance_report=report,
            spec_content="",
            _github_create_issue=_mock_create_issue_sequential,
        )
        assert len(results) == 2  # AC-002 and AC-003
        assert all(r.success for r in results)
        ac_ids = {r.ac_id for r in results}
        assert ac_ids == {"AC-002", "AC-003"}

    def test_skips_pass_entries(self) -> None:
        """PASS entries do not generate issues."""
        report = ComplianceReport(
            entries=[
                ComplianceEntry(
                    ac_id="AC-001", description="Good", status="PASS",
                    implemented=True, test_exists=True,
                ),
            ],
        )
        results = create_issues_from_compliance(
            repo="org/repo",
            compliance_report=report,
            spec_content="",
            _github_create_issue=_mock_create_issue,
        )
        assert len(results) == 0

    def test_handles_api_failure_gracefully(self) -> None:
        """API failures are captured in results, not raised."""
        report = ComplianceReport(
            entries=[
                ComplianceEntry(
                    ac_id="AC-001", description="Fail", status="NOT_FOUND",
                ),
            ],
        )
        results = create_issues_from_compliance(
            repo="org/repo",
            compliance_report=report,
            spec_content="",
            _github_create_issue=_mock_create_issue_failing,
        )
        assert len(results) == 1
        assert results[0].success is False
        assert "500" in results[0].error

    def test_issue_title_includes_ac_id(self) -> None:
        """Created issue titles include the AC-ID."""
        report = ComplianceReport(
            entries=[
                ComplianceEntry(
                    ac_id="AC-042", description="Missing feature", status="NOT_FOUND",
                ),
            ],
        )
        results = create_issues_from_compliance(
            repo="org/repo",
            compliance_report=report,
            spec_content="",
            _github_create_issue=_mock_create_issue,
        )
        assert "AC-042" in results[0].title


# ---------------------------------------------------------------------------
# IssueResult dataclass
# ---------------------------------------------------------------------------


class TestIssueResultDataclass:
    """Tests for IssueResult dataclass."""

    def test_defaults(self) -> None:
        """IssueResult has sensible defaults."""
        result = IssueResult(ac_id="AC-001")
        assert result.success is True
        assert result.error == ""
        assert result.issue_number == 0

    def test_frozen(self) -> None:
        """IssueResult is immutable."""
        result = IssueResult(ac_id="AC-001")
        with pytest.raises(AttributeError):
            result.ac_id = "AC-002"  # type: ignore[misc]
