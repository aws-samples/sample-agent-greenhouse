"""Tests for the PR review skill.

Covers PR review with mocked diffs, code quality checks (bare except, etc.),
spec compliance integration, verdict logic, and review posting.

Traces to: spec SS3.4 — AC-14, AC-15, AC-16, AC-17
"""

from __future__ import annotations

import json

import pytest

from platform_agent.plato.skills.pr_review import PRReviewSkill, register_skill
from platform_agent.plato.skills.pr_review.reviewer import (
    CodeIssue,
    PRReviewResult,
    PRReviewer,
    _split_diff_by_file,
)
from platform_agent.plato.skills.pr_review.tools import PR_REVIEW_TOOLS, review_pull_request
from platform_agent.plato.skills.base import SkillPack, load_skill


# ---------------------------------------------------------------------------
# Sample diffs and data
# ---------------------------------------------------------------------------

CLEAN_DIFF = """\
diff --git a/src/agent.py b/src/agent.py
index abc..def 100644
--- a/src/agent.py
+++ b/src/agent.py
@@ -10,6 +10,10 @@ class Agent:
     def __init__(self):
         self.name = "agent"

+    def process(self, data: dict) -> dict:
+        \"\"\"Process incoming data.\"\"\"
+        return {"status": "ok"}
+
"""

BARE_EXCEPT_DIFF = """\
diff --git a/src/handler.py b/src/handler.py
index abc..def 100644
--- a/src/handler.py
+++ b/src/handler.py
@@ -5,3 +5,8 @@ def handle_request(req):
     try:
         result = process(req)
+    except:
+        result = None
+    return result
"""

TODO_NO_ISSUE_DIFF = """\
diff --git a/src/utils.py b/src/utils.py
index abc..def 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,3 +1,5 @@
+# TODO fix this later
+# TODO(#123) this is fine
 def helper():
     pass
"""

SECRET_DIFF = """\
diff --git a/src/config.py b/src/config.py
index abc..def 100644
--- a/src/config.py
+++ b/src/config.py
@@ -1,3 +1,5 @@
+api_key = "sk-1234567890abcdef"
+password = "mysecretpassword123"
 def get_config():
     pass
"""

MIXED_ISSUES_DIFF = """\
diff --git a/src/handler.py b/src/handler.py
index abc..def 100644
--- a/src/handler.py
+++ b/src/handler.py
@@ -5,3 +5,10 @@ def handle_request(req):
     try:
         result = process(req)
+    except:
+        result = None
+    # TODO fix this later
+    return result
"""

MISSING_DOCSTRING_DIFF = """\
diff --git a/src/new_module.py b/src/new_module.py
index abc..def 100644
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,5 @@
+def undocumented_function(x):
+    return x * 2
+
+class UndocumentedClass:
+    pass
"""


# ---------------------------------------------------------------------------
# Mock GitHub helpers
# ---------------------------------------------------------------------------


def _mock_get_pr_diff(repo: str, pr_number: int, file_path: str = "") -> str:
    """Mock that returns a clean diff."""
    return CLEAN_DIFF


def _mock_get_pr_diff_bare_except(repo: str, pr_number: int, file_path: str = "") -> str:
    """Mock that returns a diff with bare except."""
    return BARE_EXCEPT_DIFF


def _mock_get_pr_diff_mixed(repo: str, pr_number: int, file_path: str = "") -> str:
    """Mock that returns a diff with multiple issues."""
    return MIXED_ISSUES_DIFF


def _mock_get_pr_diff_secret(repo: str, pr_number: int, file_path: str = "") -> str:
    """Mock that returns a diff with hardcoded secrets."""
    return SECRET_DIFF


def _mock_list_pr_files(repo: str, pr_number: int) -> str:
    """Mock that returns a list of changed files."""
    return json.dumps({
        "files": [
            {"filename": "src/agent.py", "status": "modified", "additions": 4, "deletions": 0, "changes": 4},
        ],
        "count": 1,
    })


def _mock_get_file(repo: str, path: str, branch: str = "main") -> str:
    """Mock that returns basic file content."""
    return "# placeholder\n"


# ---------------------------------------------------------------------------
# Skill registration and metadata
# ---------------------------------------------------------------------------


class TestSkillRegistration:
    """Tests for PR review skill registration and metadata."""

    def test_skill_is_skillpack_subclass(self) -> None:
        """PRReviewSkill is a SkillPack subclass."""
        assert issubclass(PRReviewSkill, SkillPack)

    def test_skill_name(self) -> None:
        """Skill name is 'pr_review'."""
        skill = PRReviewSkill()
        assert skill.name == "pr_review"

    def test_skill_has_system_prompt(self) -> None:
        """Skill has system_prompt_extension cleared (SKILL.md is sole source)."""
        skill = PRReviewSkill()
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        assert skill.system_prompt_extension == ""

    def test_skill_tools_list(self) -> None:
        """Skill references the review tool."""
        skill = PRReviewSkill()
        assert "review_pull_request" in skill.tools

    def test_load_skill(self) -> None:
        """load_skill creates a configured instance."""
        skill = load_skill(PRReviewSkill)
        assert skill.name == "pr_review"

    def test_skill_registered_in_registry(self) -> None:
        """Skill is available via the registry."""
        from platform_agent.plato.skills import get_skill
        cls = get_skill("pr_review")
        assert cls is PRReviewSkill

    def test_tools_list_has_all_tools(self) -> None:
        """PR_REVIEW_TOOLS contains the review tool."""
        assert len(PR_REVIEW_TOOLS) == 1


# ---------------------------------------------------------------------------
# PR review with mocked diff
# ---------------------------------------------------------------------------


class TestPRReviewClean:
    """Tests for PR review with clean (no issues) diffs.

    Traces to: AC-14 (Can fetch and parse PR diffs)
    """

    def test_clean_pr_approves(self) -> None:
        """Clean PR with no issues gets APPROVE verdict."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        assert result.overall_status == "APPROVE"
        assert len(result.code_issues) == 0

    def test_clean_pr_has_summary(self) -> None:
        """Clean PR review includes a summary."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        assert "PR Review Summary" in result.summary
        assert "None found" in result.summary


# ---------------------------------------------------------------------------
# Code quality checks
# ---------------------------------------------------------------------------


class TestCodeQualityChecks:
    """Tests for code quality pattern detection."""

    def test_bare_except_detected(self) -> None:
        """Bare `except:` is detected as a blocking issue."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff_bare_except,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        bare_excepts = [
            i for i in result.code_issues
            if "except" in i.description.lower()
        ]
        assert len(bare_excepts) >= 1
        assert bare_excepts[0].severity == "blocking"
        assert bare_excepts[0].file == "src/handler.py"

    def test_todo_without_issue_detected(self) -> None:
        """TODO without issue link is detected as non-blocking."""
        reviewer = PRReviewer(
            github_get_pr_diff=lambda repo, pr_number, file_path="": TODO_NO_ISSUE_DIFF,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        todos = [
            i for i in result.code_issues
            if "TODO" in i.description
        ]
        assert len(todos) >= 1
        assert todos[0].severity == "non-blocking"

    def test_hardcoded_secret_detected(self) -> None:
        """Hardcoded secrets are detected as blocking issues."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff_secret,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        secrets = [
            i for i in result.code_issues
            if "secret" in i.description.lower() or "credential" in i.description.lower()
        ]
        assert len(secrets) >= 1
        assert all(s.severity == "blocking" for s in secrets)

    def test_missing_docstring_detected(self) -> None:
        """Missing docstrings on new functions are detected as non-blocking."""
        reviewer = PRReviewer(
            github_get_pr_diff=lambda repo, pr_number, file_path="": MISSING_DOCSTRING_DIFF,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        docstring_issues = [
            i for i in result.code_issues
            if "docstring" in i.description.lower()
        ]
        assert len(docstring_issues) >= 1
        assert docstring_issues[0].severity == "non-blocking"


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------


class TestVerdictLogic:
    """Tests for review verdict determination.

    Traces to: AC-17 (Blocking = REQUEST_CHANGES, non-blocking = COMMENT)
    """

    def test_blocking_issues_request_changes(self) -> None:
        """Blocking issues result in REQUEST_CHANGES."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff_bare_except,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        assert result.overall_status == "REQUEST_CHANGES"

    def test_only_non_blocking_comments(self) -> None:
        """Only non-blocking issues result in COMMENT."""
        reviewer = PRReviewer(
            github_get_pr_diff=lambda repo, pr_number, file_path="": TODO_NO_ISSUE_DIFF,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        assert result.overall_status == "COMMENT"

    def test_no_issues_approves(self) -> None:
        """No issues result in APPROVE."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        assert result.overall_status == "APPROVE"

    def test_mixed_issues_request_changes(self) -> None:
        """Mixed blocking + non-blocking results in REQUEST_CHANGES."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff_mixed,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        assert result.overall_status == "REQUEST_CHANGES"
        blocking = [i for i in result.code_issues if i.severity == "blocking"]
        non_blocking = [i for i in result.code_issues if i.severity == "non-blocking"]
        assert len(blocking) >= 1
        assert len(non_blocking) >= 1


# ---------------------------------------------------------------------------
# Spec compliance integration in review
# ---------------------------------------------------------------------------


class TestSpecComplianceIntegration:
    """Tests for spec compliance checks within PR review.

    Traces to: AC-16 (Review includes spec compliance results)
    """

    def test_review_with_spec_includes_compliance(self) -> None:
        """Review with spec_content includes compliance report."""
        spec_content = """\
# Spec
## 1.0 Feature
- AC-001: Feature works correctly
"""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(
            repo="org/repo",
            pr_number=1,
            spec_content=spec_content,
        )
        assert result.spec_compliance is not None
        assert len(result.spec_compliance.entries) == 1

    def test_review_without_spec_no_compliance(self) -> None:
        """Review without spec_content has no compliance report."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        assert result.spec_compliance is None

    def test_spec_failures_cause_request_changes(self) -> None:
        """Spec compliance NOT_FOUND entries cause REQUEST_CHANGES."""
        spec_content = """\
# Spec
## 1.0 Feature
- AC-999: Completely missing feature
"""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(
            repo="org/repo",
            pr_number=1,
            spec_content=spec_content,
        )
        # AC-999 won't be found → NOT_FOUND → REQUEST_CHANGES
        assert result.overall_status == "REQUEST_CHANGES"


# ---------------------------------------------------------------------------
# Review summary formatting
# ---------------------------------------------------------------------------


class TestReviewSummary:
    """Tests for review summary formatting."""

    def test_summary_includes_file_count(self) -> None:
        """Summary includes count of changed files."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        assert "Files changed:" in result.summary

    def test_summary_includes_issue_counts(self) -> None:
        """Summary includes blocking/non-blocking issue counts."""
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff_mixed,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(repo="org/repo", pr_number=1)
        assert "blocking" in result.summary

    def test_summary_includes_spec_compliance(self) -> None:
        """Summary includes spec compliance section when spec provided."""
        spec_content = "# Spec\n- AC-001: test\n"
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff,
            github_list_pr_files=_mock_list_pr_files,
            github_get_file=_mock_get_file,
        )
        result = reviewer.review_pr(
            repo="org/repo", pr_number=1, spec_content=spec_content
        )
        assert "Spec Compliance" in result.summary


# ---------------------------------------------------------------------------
# Diff parsing helpers
# ---------------------------------------------------------------------------


class TestDiffParsing:
    """Tests for diff parsing utilities."""

    def test_split_diff_by_file(self) -> None:
        """Splits a multi-file diff into per-file sections."""
        multi_diff = (
            "diff --git a/file1.py b/file1.py\n"
            "+line1\n"
            "diff --git a/file2.py b/file2.py\n"
            "+line2\n"
        )
        result = _split_diff_by_file(multi_diff)
        assert "file1.py" in result
        assert "file2.py" in result

    def test_split_empty_diff(self) -> None:
        """Empty diff returns empty dict."""
        assert _split_diff_by_file("") == {}


# ---------------------------------------------------------------------------
# PRReviewResult and CodeIssue dataclasses
# ---------------------------------------------------------------------------


class TestDataclasses:
    """Tests for PRReviewResult and CodeIssue dataclasses."""

    def test_code_issue_is_frozen(self) -> None:
        """CodeIssue is immutable."""
        issue = CodeIssue(
            file="test.py", line="1", severity="blocking",
            description="test", suggestion="fix"
        )
        with pytest.raises(AttributeError):
            issue.file = "other.py"  # type: ignore[misc]

    def test_pr_review_result_defaults(self) -> None:
        """PRReviewResult has sensible defaults."""
        result = PRReviewResult(overall_status="APPROVE")
        assert result.code_issues == []
        assert result.spec_compliance is None
        assert result.summary == ""
