"""Tests for the spec compliance checker skill.

Covers AC extraction, compliance checking with mocked GitHub API,
report formatting, and PASS/PARTIAL/NOT_FOUND classification.

Traces to: spec SS3.3 — AC-10, AC-11, AC-12, AC-13
"""

from __future__ import annotations

import json

import pytest

from platform_agent.plato.skills.spec_compliance import SpecComplianceSkill, register_skill
from platform_agent.plato.skills.spec_compliance.checker import (
    ComplianceEntry,
    ComplianceReport,
    SpecComplianceChecker,
)
from platform_agent.plato.skills.spec_compliance.tools import (
    SPEC_COMPLIANCE_TOOLS,
    check_single_ac,
    check_spec_compliance,
)
from platform_agent.plato.skills.base import SkillPack, load_skill


# ---------------------------------------------------------------------------
# Sample spec content
# ---------------------------------------------------------------------------

SAMPLE_SPEC = """\
# Test Spec

## 3.1 Feature A

**Acceptance Criteria:**
- AC-001: User can submit a ticket via API
- AC-002: Refund limit enforced at $500

## 3.2 Feature B

**Acceptance Criteria:**
- AC-003: Audit log captures every action
- AC-004: Dashboard shows real-time metrics
"""

SAMPLE_SPEC_SINGLE = """\
# Minimal Spec

### 2.1 Auth

- AC-100: Users can log in with SSO
"""


# ---------------------------------------------------------------------------
# Mock GitHub API helpers
# ---------------------------------------------------------------------------


def _mock_get_tree(repo: str, path: str = "", branch: str = "main") -> str:
    """Mock github_get_tree returning a fixed file list."""
    if path == "":
        return json.dumps({
            "entries": [
                {"name": "src", "type": "dir", "path": "src", "size": 0},
                {"name": "tests", "type": "dir", "path": "tests", "size": 0},
                {"name": "README.md", "type": "file", "path": "README.md", "size": 100},
            ],
            "count": 3,
        })
    if path == "src":
        return json.dumps({
            "entries": [
                {"name": "agent.py", "type": "file", "path": "src/agent.py", "size": 500},
                {"name": "utils.py", "type": "file", "path": "src/utils.py", "size": 200},
            ],
            "count": 2,
        })
    if path == "tests":
        return json.dumps({
            "entries": [
                {"name": "test_agent.py", "type": "file", "path": "tests/test_agent.py", "size": 300},
            ],
            "count": 1,
        })
    return json.dumps({"entries": [], "count": 0})


def _mock_get_file(repo: str, path: str, branch: str = "main") -> str:
    """Mock github_get_file returning fixed file contents."""
    files = {
        "src/agent.py": (
            "# Agent module\n"
            "\n"
            "def submit_ticket(data):\n"
            "    \"\"\"Submit a ticket via the API.\n"
            "\n"
            "    Traces to: AC-001\n"
            "    \"\"\"\n"
            "    return {'status': 'created'}\n"
        ),
        "src/utils.py": (
            "# Utilities\n"
            "\n"
            "def format_date(dt):\n"
            "    return dt.isoformat()\n"
        ),
        "tests/test_agent.py": (
            "# Tests for agent module\n"
            "\n"
            "def test_submit_ticket():\n"
            "    \"\"\"TC-001 (traces to AC-001)\"\"\"\n"
            "    assert submit_ticket({}) == {'status': 'created'}\n"
            "\n"
            "def test_audit_log():\n"
            "    \"\"\"TC-003 (traces to AC-003)\"\"\"\n"
            "    pass\n"
        ),
        "README.md": "# Project\n",
        "spec.md": SAMPLE_SPEC,
    }
    if path in files:
        return files[path]
    raise RuntimeError(f"404: File not found: {path}")


def _mock_get_file_spec(repo: str, path: str, branch: str = "main") -> str:
    """Mock that returns spec.md content."""
    if path == "spec.md":
        return SAMPLE_SPEC
    return _mock_get_file(repo, path, branch)


# ---------------------------------------------------------------------------
# Skill registration and metadata
# ---------------------------------------------------------------------------


class TestSkillRegistration:
    """Tests for spec compliance skill registration and metadata."""

    def test_skill_is_skillpack_subclass(self) -> None:
        """SpecComplianceSkill is a SkillPack subclass."""
        assert issubclass(SpecComplianceSkill, SkillPack)

    def test_skill_name(self) -> None:
        """Skill name is 'spec_compliance'."""
        skill = SpecComplianceSkill()
        assert skill.name == "spec_compliance"

    def test_skill_has_system_prompt(self) -> None:
        """Skill has system_prompt_extension cleared (SKILL.md is sole source)."""
        skill = SpecComplianceSkill()
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        assert skill.system_prompt_extension == ""

    def test_skill_tools_list(self) -> None:
        """Skill references both compliance tool names."""
        skill = SpecComplianceSkill()
        assert "check_spec_compliance" in skill.tools
        assert "check_single_ac" in skill.tools

    def test_load_skill(self) -> None:
        """load_skill creates a configured instance."""
        skill = load_skill(SpecComplianceSkill)
        assert skill.name == "spec_compliance"

    def test_skill_registered_in_registry(self) -> None:
        """Skill is available via the registry."""
        from platform_agent.plato.skills import get_skill
        cls = get_skill("spec_compliance")
        assert cls is SpecComplianceSkill

    def test_tools_list_has_all_tools(self) -> None:
        """SPEC_COMPLIANCE_TOOLS contains both tool functions."""
        assert len(SPEC_COMPLIANCE_TOOLS) == 2


# ---------------------------------------------------------------------------
# AC extraction from spec markdown
# ---------------------------------------------------------------------------


class TestACExtraction:
    """Tests for acceptance criteria extraction from spec content."""

    def test_extracts_all_acs(self) -> None:
        """Extracts all AC-xxx entries from spec content.

        Traces to: AC-10 (Checks every AC in spec.md, no skipping)
        """
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        criteria = checker.extract_acceptance_criteria()
        ac_ids = [c["id"] for c in criteria]
        assert ac_ids == ["AC-001", "AC-002", "AC-003", "AC-004"]

    def test_extracts_descriptions(self) -> None:
        """Extracted ACs include their full descriptions."""
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        criteria = checker.extract_acceptance_criteria()
        assert criteria[0]["description"] == "User can submit a ticket via API"
        assert criteria[1]["description"] == "Refund limit enforced at $500"

    def test_extracts_sections(self) -> None:
        """Extracted ACs include their section references."""
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        criteria = checker.extract_acceptance_criteria()
        assert criteria[0]["section"] == "3.1"
        assert criteria[2]["section"] == "3.2"

    def test_empty_spec_returns_empty(self) -> None:
        """Empty spec returns no criteria."""
        checker = SpecComplianceChecker("")
        assert checker.extract_acceptance_criteria() == []

    def test_spec_without_acs_returns_empty(self) -> None:
        """Spec without AC-xxx patterns returns no criteria."""
        checker = SpecComplianceChecker("# Just a heading\n\nSome text.")
        assert checker.extract_acceptance_criteria() == []

    def test_single_ac_extraction(self) -> None:
        """Correctly extracts a single AC from minimal spec."""
        checker = SpecComplianceChecker(SAMPLE_SPEC_SINGLE)
        criteria = checker.extract_acceptance_criteria()
        assert len(criteria) == 1
        assert criteria[0]["id"] == "AC-100"
        assert criteria[0]["section"] == "2.1"


# ---------------------------------------------------------------------------
# Compliance checking with mocked GitHub API
# ---------------------------------------------------------------------------


class TestComplianceChecking:
    """Tests for compliance checking with mocked GitHub API."""

    def test_pass_status_when_impl_and_test(self) -> None:
        """AC-001 is PASS: implementation + test both found.

        Traces to: AC-11 (Links findings to file:line), AC-12 (Distinguishes statuses)
        """
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        ac001 = next(e for e in report.entries if e.ac_id == "AC-001")
        assert ac001.status == "PASS"
        assert ac001.implemented is True
        assert ac001.impl_file == "src/agent.py"
        assert ac001.impl_line is not None
        assert ac001.test_exists is True
        assert ac001.test_file == "tests/test_agent.py"

    def test_not_found_status_when_no_evidence(self) -> None:
        """AC-002 is NOT_FOUND: no implementation or test evidence.

        Traces to: AC-12 (Distinguishes not-implemented)
        """
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        ac002 = next(e for e in report.entries if e.ac_id == "AC-002")
        assert ac002.status == "NOT_FOUND"
        assert ac002.implemented is False
        assert ac002.test_exists is False

    def test_partial_status_when_test_only(self) -> None:
        """AC-003 is PARTIAL: test exists but no impl comment found.

        Traces to: AC-12 (Distinguishes implemented-but-no-test vs test-only)
        """
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        ac003 = next(e for e in report.entries if e.ac_id == "AC-003")
        assert ac003.status == "PARTIAL"
        assert ac003.test_exists is True

    def test_checks_all_criteria(self) -> None:
        """Report includes an entry for every AC in the spec.

        Traces to: AC-10 (Checks every AC, no skipping)
        """
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        assert len(report.entries) == 4
        ac_ids = {e.ac_id for e in report.entries}
        assert ac_ids == {"AC-001", "AC-002", "AC-003", "AC-004"}

    def test_summary_counts(self) -> None:
        """Report summary correctly counts statuses."""
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        assert report.summary["PASS"] == 1  # AC-001
        assert report.summary["PARTIAL"] == 1  # AC-003
        assert report.summary["NOT_FOUND"] == 2  # AC-002, AC-004


# ---------------------------------------------------------------------------
# Report formatting (AC-13: structured/parseable)
# ---------------------------------------------------------------------------


class TestReportFormatting:
    """Tests for compliance report formatting.

    Traces to: AC-13 (Output is structured/parseable, not freeform prose)
    """

    def test_format_is_markdown_table(self) -> None:
        """Report contains a markdown table with header row."""
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        formatted = checker.format_report(report)
        assert "| AC ID |" in formatted
        assert "|-------|" in formatted

    def test_format_includes_all_entries(self) -> None:
        """Formatted report includes a row for every AC."""
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        formatted = checker.format_report(report)
        assert "AC-001" in formatted
        assert "AC-002" in formatted
        assert "AC-003" in formatted
        assert "AC-004" in formatted

    def test_format_includes_status_values(self) -> None:
        """Formatted report includes PASS, PARTIAL, NOT_FOUND status values."""
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        formatted = checker.format_report(report)
        assert "PASS" in formatted
        assert "PARTIAL" in formatted
        assert "NOT_FOUND" in formatted

    def test_format_includes_file_references(self) -> None:
        """Formatted report includes file:line references for found items.

        Traces to: AC-11 (Links findings to specific file:line references)
        """
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        formatted = checker.format_report(report)
        assert "src/agent.py" in formatted

    def test_format_includes_summary_counts(self) -> None:
        """Formatted report includes summary counts at the top."""
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        formatted = checker.format_report(report)
        assert "PASS:" in formatted
        assert "PARTIAL:" in formatted
        assert "NOT_FOUND:" in formatted

    def test_format_is_parseable(self) -> None:
        """Formatted report can be parsed by splitting on | characters."""
        checker = SpecComplianceChecker(SAMPLE_SPEC)
        report = checker.check_compliance(
            repo="org/test-repo",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )
        formatted = checker.format_report(report)
        table_lines = [
            line for line in formatted.split("\n")
            if line.startswith("|") and "---" not in line
        ]
        # Header + 4 data rows
        assert len(table_lines) == 5
        # Each row should have at least 5 columns
        for line in table_lines:
            columns = [c.strip() for c in line.split("|") if c.strip()]
            assert len(columns) >= 5


# ---------------------------------------------------------------------------
# ComplianceEntry and ComplianceReport dataclasses
# ---------------------------------------------------------------------------


class TestDataclasses:
    """Tests for ComplianceEntry and ComplianceReport dataclasses."""

    def test_compliance_entry_defaults(self) -> None:
        """ComplianceEntry has sensible defaults."""
        entry = ComplianceEntry(ac_id="AC-001", description="Test")
        assert entry.status == "NOT_FOUND"
        assert entry.implemented is False
        assert entry.test_exists is False
        assert entry.impl_file is None
        assert entry.test_file is None

    def test_compliance_report_compute_summary(self) -> None:
        """ComplianceReport.compute_summary correctly aggregates."""
        report = ComplianceReport(entries=[
            ComplianceEntry(ac_id="AC-1", description="a", status="PASS"),
            ComplianceEntry(ac_id="AC-2", description="b", status="PASS"),
            ComplianceEntry(ac_id="AC-3", description="c", status="PARTIAL"),
            ComplianceEntry(ac_id="AC-4", description="d", status="NOT_FOUND"),
        ])
        report.compute_summary()
        assert report.summary == {"PASS": 2, "PARTIAL": 1, "NOT_FOUND": 1}

    def test_compliance_entry_is_frozen(self) -> None:
        """ComplianceEntry is immutable (frozen dataclass)."""
        entry = ComplianceEntry(ac_id="AC-001", description="Test")
        with pytest.raises(AttributeError):
            entry.ac_id = "AC-002"  # type: ignore[misc]
