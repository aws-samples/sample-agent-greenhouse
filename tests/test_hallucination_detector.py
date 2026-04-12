"""Tests for HallucinationDetectorHook — data capture for offline analysis.

Tests:
1. Captures review output
2. Captures file tree
3. Captures AC IDs
4. Cross-reference check (file in review not in tree)
5. AC consistency check (AC in test cases not in spec)
6. get_captured_data returns list
7. clear() resets all data
8. Output truncation to 2000 chars
9. Non-relevant tool not captured
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from platform_agent.foundation.hooks.hallucination_detector_hook import (
    HallucinationDetectorHook,
)


@pytest.fixture
def hook() -> HallucinationDetectorHook:
    """Create a fresh HallucinationDetectorHook."""
    return HallucinationDetectorHook(session_id="test_session")


def _make_tool_event(
    tool_name: str,
    tool_result: str = "",
    tool_input: dict | None = None,
):
    """Create a mock AfterToolCallEvent."""
    event = MagicMock()
    event.tool_use = {
        "toolUseId": "tu_001",
        "name": tool_name,
        "input": tool_input or {},
    }
    event.tool_result = tool_result
    return event


class TestCapturesReviewOutput:
    """Test that review tool outputs are captured."""

    def test_captures_review_output(self, hook: HallucinationDetectorHook):
        """After create_pull_request_review, captures text."""
        review_text = (
            "Found issues in src/main.py and tests/test_main.py. "
            "AC-001 is not implemented correctly."
        )
        event = _make_tool_event("create_pull_request_review", tool_result=review_text)
        hook.on_after_tool_call(event)

        data = hook.get_captured_data()
        assert len(data) == 1
        assert data[0]["tool_name"] == "create_pull_request_review"
        assert "src/main.py" in data[0]["output_text"]
        assert "AC-001" in data[0]["output_text"]


class TestCapturesFileTree:
    """Test that github_get_tree outputs are captured."""

    def test_captures_file_tree(self, hook: HallucinationDetectorHook):
        """After github_get_tree, captures tree."""
        tree_result = "src/main.py\nsrc/utils.py\ntests/test_main.py\nlib/helpers.py"
        event = _make_tool_event("github_get_tree", tool_result=tree_result)
        hook.on_after_tool_call(event)

        data = hook.get_captured_data()
        assert len(data) == 1
        assert data[0]["tool_name"] == "github_get_tree"
        assert "src/main.py" in data[0]["file_refs"]


class TestCapturesACIDs:
    """Test AC ID extraction from output."""

    def test_captures_ac_ids(self, hook: HallucinationDetectorHook):
        """Detects AC-xxx patterns in output."""
        result = "Verified AC-001, AC-002, and AC-003 are covered by tests."
        event = _make_tool_event("create_pull_request_review", tool_result=result)
        hook.on_after_tool_call(event)

        data = hook.get_captured_data()
        assert "AC-001" in data[0]["ac_ids"]
        assert "AC-002" in data[0]["ac_ids"]
        assert "AC-003" in data[0]["ac_ids"]


class TestCrossReferenceCheck:
    """Test cross-reference consistency check."""

    def test_cross_reference_check(self, hook: HallucinationDetectorHook):
        """File in review not in tree → flagged."""
        # Capture a file tree.
        tree_event = _make_tool_event(
            "github_get_tree",
            tool_result="src/main.py\nsrc/utils.py\ntests/test_main.py",
        )
        hook.on_after_tool_call(tree_event)

        # Capture a review that references a file NOT in the tree.
        review_event = _make_tool_event(
            "create_pull_request_review",
            tool_result="Issue found in src/missing_file.py — needs fixing",
        )
        hook.on_after_tool_call(review_event)

        report = hook.get_consistency_report()
        assert len(report["cross_reference_issues"]) > 0
        missing = [i["missing_file"] for i in report["cross_reference_issues"]]
        assert "src/missing_file.py" in missing

    def test_no_cross_reference_issue_when_file_exists(self, hook: HallucinationDetectorHook):
        """File in review that IS in tree → no issue."""
        tree_event = _make_tool_event(
            "github_get_tree",
            tool_result="src/main.py\nsrc/utils.py",
        )
        hook.on_after_tool_call(tree_event)

        review_event = _make_tool_event(
            "create_pull_request_review",
            tool_result="Looks good in src/main.py",
        )
        hook.on_after_tool_call(review_event)

        report = hook.get_consistency_report()
        assert len(report["cross_reference_issues"]) == 0


class TestACConsistencyCheck:
    """Test AC consistency check."""

    def test_ac_consistency_check(self, hook: HallucinationDetectorHook):
        """AC in test cases not in spec ACs → flagged."""
        # Simulate spec submission with AC IDs.
        spec_event = _make_tool_event(
            "aidlc_submit_answers",
            tool_result="Defined AC-001, AC-002 for this feature.",
            tool_input={"stage_id": "requirements"},
        )
        hook.on_after_tool_call(spec_event)

        # Simulate a review that references an AC not in the spec.
        review_event = _make_tool_event(
            "check_spec_compliance",
            tool_result="Checking AC-001, AC-003 compliance.",
        )
        hook.on_after_tool_call(review_event)

        report = hook.get_consistency_report()
        assert len(report["ac_consistency_issues"]) > 0
        unmatched = [i["unmatched_ac_id"] for i in report["ac_consistency_issues"]]
        assert "AC-003" in unmatched


class TestGetCapturedData:
    """Test get_captured_data returns list of dicts."""

    def test_get_captured_data(self, hook: HallucinationDetectorHook):
        """Returns list of capture dicts."""
        event = _make_tool_event("create_pull_request_review", tool_result="review text")
        hook.on_after_tool_call(event)

        data = hook.get_captured_data()
        assert isinstance(data, list)
        assert len(data) == 1
        assert isinstance(data[0], dict)
        assert "session_id" in data[0]
        assert "tool_name" in data[0]
        assert "output_text" in data[0]
        assert "file_refs" in data[0]
        assert "ac_ids" in data[0]
        assert "timestamp" in data[0]


class TestClear:
    """Test clear() resets all data."""

    def test_clear(self, hook: HallucinationDetectorHook):
        """Clear removes all captured data."""
        event = _make_tool_event("create_pull_request_review", tool_result="text")
        hook.on_after_tool_call(event)
        assert len(hook.get_captured_data()) == 1

        hook.clear()
        assert len(hook.get_captured_data()) == 0


class TestOutputTruncation:
    """Test output truncation to 2000 chars."""

    def test_output_truncation(self, hook: HallucinationDetectorHook):
        """Long output truncated to 2000 chars."""
        long_text = "x" * 5000
        event = _make_tool_event("create_pull_request_review", tool_result=long_text)
        hook.on_after_tool_call(event)

        data = hook.get_captured_data()
        assert len(data[0]["output_text"]) == 2000


class TestNonRelevantTool:
    """Test that non-relevant tools are not captured."""

    def test_non_relevant_tool(self, hook: HallucinationDetectorHook):
        """Random tool call not captured."""
        event = _make_tool_event("read_file", tool_result="file contents")
        hook.on_after_tool_call(event)

        data = hook.get_captured_data()
        assert len(data) == 0
