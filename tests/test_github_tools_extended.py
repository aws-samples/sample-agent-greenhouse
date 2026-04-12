"""Tests for extended GitHub tools — create_issue, create_review, list_prs.

Tests the new @strands_tool-decorated GitHub tools added for Sprint 2.
Follows the same mock patterns as test_strands_github_tools.py.
"""

from __future__ import annotations

import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from platform_agent.foundation.tools.github import (
    GITHUB_TOOLS,
    _github_request,
    github_create_issue,
    github_create_review,
    github_list_prs,
)


class TestGitHubCreateIssue(unittest.TestCase):
    """Tests for github_create_issue tool."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_create_issue_basic(self, mock_urlopen: MagicMock) -> None:
        """Creates an issue with title and body."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "number": 42,
            "html_url": "https://github.com/org/repo/issues/42",
            "title": "Bug: something broke",
        }).encode()
        mock_resp.status = 201
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result_json = github_create_issue(
            repo="org/repo",
            title="Bug: something broke",
            body="Steps to reproduce...",
        )
        result = json.loads(result_json)

        assert result["status"] == "created"
        assert result["number"] == 42
        assert result["url"] == "https://github.com/org/repo/issues/42"
        assert result["title"] == "Bug: something broke"

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_create_issue_with_labels(self, mock_urlopen: MagicMock) -> None:
        """Creates an issue with labels."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "number": 43,
            "html_url": "https://github.com/org/repo/issues/43",
            "title": "Feature request",
        }).encode()
        mock_resp.status = 201
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result_json = github_create_issue(
            repo="org/repo",
            title="Feature request",
            body="Please add...",
            labels=["enhancement", "p2"],
        )
        result = json.loads(result_json)
        assert result["status"] == "created"

        # Verify the request body included labels
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode())
        assert "labels" in body
        assert body["labels"] == ["enhancement", "p2"]

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_create_issue_without_labels(self, mock_urlopen: MagicMock) -> None:
        """Creates an issue without labels — labels key should be absent."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "number": 44,
            "html_url": "https://github.com/org/repo/issues/44",
            "title": "No labels",
        }).encode()
        mock_resp.status = 201
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        github_create_issue(
            repo="org/repo",
            title="No labels",
            body="body text",
        )

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode())
        assert "labels" not in body


class TestGitHubCreateReview(unittest.TestCase):
    """Tests for github_create_review tool."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_create_comment_review(self, mock_urlopen: MagicMock) -> None:
        """Posts a COMMENT review."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": 101,
            "state": "COMMENTED",
            "html_url": "https://github.com/org/repo/pull/1#pullrequestreview-101",
        }).encode()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result_json = github_create_review(
            repo="org/repo",
            pr_number=1,
            body="Looks good overall.",
            event="COMMENT",
        )
        result = json.loads(result_json)
        assert result["status"] == "created"
        assert result["review_id"] == 101

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_create_approve_review(self, mock_urlopen: MagicMock) -> None:
        """Posts an APPROVE review."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": 102,
            "state": "APPROVED",
            "html_url": "https://github.com/org/repo/pull/1#pullrequestreview-102",
        }).encode()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result_json = github_create_review(
            repo="org/repo",
            pr_number=1,
            body="LGTM",
            event="APPROVE",
        )
        result = json.loads(result_json)
        assert result["status"] == "created"
        assert result["state"] == "APPROVED"

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_create_request_changes_review(self, mock_urlopen: MagicMock) -> None:
        """Posts a REQUEST_CHANGES review."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": 103,
            "state": "CHANGES_REQUESTED",
            "html_url": "https://github.com/org/repo/pull/1#pullrequestreview-103",
        }).encode()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result_json = github_create_review(
            repo="org/repo",
            pr_number=1,
            body="Needs changes",
            event="REQUEST_CHANGES",
        )
        result = json.loads(result_json)
        assert result["status"] == "created"

    def test_invalid_event_returns_error(self) -> None:
        """Invalid event type returns an error without making API call."""
        result_json = github_create_review(
            repo="org/repo",
            pr_number=1,
            body="test",
            event="INVALID",
        )
        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "Invalid event" in result["message"]

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_review_with_inline_comments(self, mock_urlopen: MagicMock) -> None:
        """Posts a review with inline comments."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": 104,
            "state": "COMMENTED",
            "html_url": "https://github.com/org/repo/pull/1#pullrequestreview-104",
        }).encode()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        comments = [
            {"path": "src/main.py", "position": 5, "body": "Consider renaming this"},
        ]
        result_json = github_create_review(
            repo="org/repo",
            pr_number=1,
            body="Some comments",
            event="COMMENT",
            comments=comments,
        )
        result = json.loads(result_json)
        assert result["status"] == "created"

        # Verify comments were included in request body
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode())
        assert "comments" in body
        assert len(body["comments"]) == 1

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_event_case_insensitive(self, mock_urlopen: MagicMock) -> None:
        """Event type is case-insensitive (lowercased input works)."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": 105,
            "state": "APPROVED",
            "html_url": "https://github.com/org/repo/pull/2#pullrequestreview-105",
        }).encode()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result_json = github_create_review(
            repo="org/repo",
            pr_number=2,
            body="approved",
            event="approve",  # lowercase
        )
        result = json.loads(result_json)
        assert result["status"] == "created"


class TestGitHubListPRs(unittest.TestCase):
    """Tests for github_list_prs tool."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_list_open_prs(self, mock_urlopen: MagicMock) -> None:
        """Lists open pull requests."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {
                "number": 1,
                "title": "Add feature",
                "state": "open",
                "html_url": "https://github.com/org/repo/pull/1",
                "head": {"ref": "feat/add-feature"},
                "base": {"ref": "main"},
                "user": {"login": "dev1"},
                "updated_at": "2026-04-03T10:00:00Z",
            },
            {
                "number": 2,
                "title": "Fix bug",
                "state": "open",
                "html_url": "https://github.com/org/repo/pull/2",
                "head": {"ref": "fix/bug"},
                "base": {"ref": "main"},
                "user": {"login": "dev2"},
                "updated_at": "2026-04-03T11:00:00Z",
            },
        ]).encode()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result_json = github_list_prs(repo="org/repo", state="open")
        result = json.loads(result_json)

        assert result["count"] == 2
        assert len(result["prs"]) == 2
        assert result["prs"][0]["number"] == 1
        assert result["prs"][0]["title"] == "Add feature"
        assert result["prs"][0]["head"] == "feat/add-feature"
        assert result["prs"][1]["user"] == "dev2"

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_list_empty_prs(self, mock_urlopen: MagicMock) -> None:
        """Returns empty list when no PRs match."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([]).encode()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result_json = github_list_prs(repo="org/repo", state="closed")
        result = json.loads(result_json)
        assert result["count"] == 0
        assert result["prs"] == []

    def test_invalid_state_returns_error(self) -> None:
        """Invalid state parameter returns an error."""
        result_json = github_list_prs(
            repo="org/repo",
            state="invalid",
        )
        result = json.loads(result_json)
        assert result["status"] == "error"
        assert "Invalid state" in result["message"]

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_list_prs_with_per_page(self, mock_urlopen: MagicMock) -> None:
        """Passes per_page parameter to API."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([]).encode()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        github_list_prs(repo="org/repo", per_page=5)

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "per_page=5" in req.full_url

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_per_page_capped_at_100(self, mock_urlopen: MagicMock) -> None:
        """per_page is capped at 100 even if a larger value is passed."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([]).encode()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        github_list_prs(repo="org/repo", per_page=200)

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "per_page=100" in req.full_url


class TestGitHubToolsListExtended(unittest.TestCase):
    """Tests that the new tools are registered in GITHUB_TOOLS."""

    def test_create_issue_in_tools_list(self) -> None:
        """github_create_issue is in GITHUB_TOOLS."""
        assert github_create_issue in GITHUB_TOOLS

    def test_create_review_in_tools_list(self) -> None:
        """github_create_review is in GITHUB_TOOLS."""
        assert github_create_review in GITHUB_TOOLS

    def test_list_prs_in_tools_list(self) -> None:
        """github_list_prs is in GITHUB_TOOLS."""
        assert github_list_prs in GITHUB_TOOLS

    def test_total_tools_count(self) -> None:
        """GITHUB_TOOLS has the expected total count (10 existing + 3 new)."""
        assert len(GITHUB_TOOLS) == 13
