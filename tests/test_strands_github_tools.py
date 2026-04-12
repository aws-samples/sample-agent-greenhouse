"""Tests for Strands GitHub tools.

Tests the @strands_tool-decorated GitHub tools in
platform_agent.foundation.tools.github.
"""

import base64
import json
import os
import time
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from platform_agent.foundation.tools.github import (
    GITHUB_TOOLS,
    _get_token,
    _github_request,
    github_commit_files,
    github_create_branch,
    github_create_pr,
    github_create_repo,
    github_get_file,
    github_get_tree,
    github_list_pr_files,
    github_get_pr_diff,
    github_list_repos,
    github_push_file,
)


class TestGetToken(unittest.TestCase):
    """Tests for _get_token helper."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"})
    def test_returns_token_from_env(self):
        """Falls back to env var when Identity is not available."""
        import platform_agent.foundation.tools.github as gh_mod
        gh_mod._cached_identity_token = None
        gh_mod._cached_identity_token_ts = 0
        assert _get_token() == "ghp_test123"

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_token_raises(self):
        """Raises ValueError when neither Identity nor env var is configured."""
        import platform_agent.foundation.tools.github as gh_mod
        gh_mod._cached_identity_token = None
        gh_mod._cached_identity_token_ts = 0
        os.environ.pop("GITHUB_TOKEN", None)
        with self.assertRaises(ValueError) as ctx:
            _get_token()
        assert "GitHub authentication not configured" in str(ctx.exception)

    @patch("platform_agent.foundation.tools.github._get_token_via_requires_api_key")
    def test_identity_takes_priority_over_env(self, mock_identity):
        """AgentCore Identity token takes priority over env var."""
        mock_identity.return_value = "identity_token_123"
        import platform_agent.foundation.tools.github as gh_mod
        gh_mod._cached_identity_token = None
        gh_mod._cached_identity_token_ts = 0
        os.environ["GITHUB_TOKEN"] = "env_token"
        try:
            token = _get_token()
            assert token == "identity_token_123"
        finally:
            os.environ.pop("GITHUB_TOKEN", None)

    @patch("platform_agent.foundation.tools.github._get_token_via_requires_api_key")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "env_fallback"})
    def test_falls_back_to_env_when_identity_returns_none(self, mock_identity):
        """Falls back to env var when Identity returns None."""
        mock_identity.return_value = None
        import platform_agent.foundation.tools.github as gh_mod
        gh_mod._cached_identity_token = None
        gh_mod._cached_identity_token_ts = 0
        token = _get_token()
        assert token == "env_fallback"

    def test_cached_token_expires_after_ttl(self):
        """Cached token expires after TOKEN_CACHE_TTL."""
        import platform_agent.foundation.tools.github as gh_mod
        gh_mod._cached_identity_token = "old_token"
        gh_mod._cached_identity_token_ts = time.time() - gh_mod.TOKEN_CACHE_TTL - 1
        os.environ["GITHUB_TOKEN"] = "fresh_env"
        try:
            token = _get_token()
            assert token == "fresh_env"
        finally:
            os.environ.pop("GITHUB_TOKEN", None)
            gh_mod._cached_identity_token = None
            gh_mod._cached_identity_token_ts = 0


class TestGithubRequest(unittest.TestCase):
    """Tests for _github_request helper."""

    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_get_request(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": 1}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _github_request("GET", "/repos/test/test", token="tok123")
        assert result == {"id": 1}

    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_post_request_with_body(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"created": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _github_request(
            "POST", "/user/repos", body={"name": "test"}, token="tok"
        )
        assert result == {"created": True}


    @patch("platform_agent.foundation.tools.github.time.sleep")
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_retries_on_429(self, mock_urlopen, mock_sleep):
        """Verify 429 rate limit triggers retry with Retry-After header."""
        # First call: 429 with Retry-After
        err_429 = urllib.error.HTTPError(
            "https://api.github.com/test", 429, "rate limited", {"Retry-After": "2"}, None
        )
        # Second call: success
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [err_429, mock_resp]

        result = _github_request("GET", "/test", token="tok")
        assert result == {"ok": True}
        mock_sleep.assert_called_once_with(2)
        assert mock_urlopen.call_count == 2

    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_raises_after_max_retries(self, mock_urlopen):
        """Verify error raised after exhausting retries."""
        err_429 = urllib.error.HTTPError(
            "https://api.github.com/test", 429, "rate limited", {}, None
        )
        mock_urlopen.side_effect = [err_429, err_429, err_429, err_429]

        with self.assertRaises(RuntimeError) as ctx:
            _github_request("GET", "/test", token="tok", _retries=3)
        assert "429" in str(ctx.exception)

    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_403_permission_denied_no_retry(self, mock_urlopen):
        """403 without rate-limit headers should NOT retry."""
        err_403 = urllib.error.HTTPError(
            "https://api.github.com/test", 403, "forbidden", {}, None
        )
        mock_urlopen.side_effect = [err_403]

        with self.assertRaises(RuntimeError) as ctx:
            _github_request("GET", "/test", token="tok")
        assert "403" in str(ctx.exception)
        assert mock_urlopen.call_count == 1  # No retries

    @patch("platform_agent.foundation.tools.github.time.sleep")
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_403_secondary_rate_limit_retries(self, mock_urlopen, mock_sleep):
        """403 with x-ratelimit-remaining: 0 should retry."""
        err_403 = urllib.error.HTTPError(
            "https://api.github.com/test", 403, "secondary rate limit",
            {"x-ratelimit-remaining": "0"}, None
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [err_403, mock_resp]

        result = _github_request("GET", "/test", token="tok")
        assert result == {"ok": True}
        assert mock_urlopen.call_count == 2

    @patch("platform_agent.foundation.tools.github.time.sleep")
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_retry_after_non_numeric_fallback(self, mock_urlopen, mock_sleep):
        """Non-numeric Retry-After should fallback to exponential backoff."""
        err_429 = urllib.error.HTTPError(
            "https://api.github.com/test", 429, "rate limited",
            {"Retry-After": "not-a-number"}, None
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [err_429, mock_resp]

        result = _github_request("GET", "/test", token="tok")
        assert result == {"ok": True}
        # Attempt 0 → 2**0 = 1
        mock_sleep.assert_called_once_with(1)


class TestGithubCreateRepo(unittest.TestCase):
    """Tests for github_create_repo tool."""

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_create_user_repo(self, mock_req):
        mock_req.return_value = {
            "html_url": "https://github.com/user/new-repo",
            "clone_url": "https://github.com/user/new-repo.git",
            "full_name": "user/new-repo",
            "private": True,
        }

        # Strands tools may wrap the function; call the underlying
        fn = github_create_repo
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        result = json.loads(fn(name="new-repo", description="A test repo"))

        assert result["status"] == "created"
        assert result["full_name"] == "user/new-repo"
        mock_req.assert_called_once()
        call_args = mock_req.call_args
        assert call_args[0][1] == "/user/repos"

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_create_org_repo(self, mock_req):
        mock_req.return_value = {
            "html_url": "https://github.com/myorg/new-repo",
            "clone_url": "https://github.com/myorg/new-repo.git",
            "full_name": "myorg/new-repo",
            "private": False,
        }

        fn = github_create_repo
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        result = json.loads(
            fn(name="new-repo", description="test", org="myorg", private=False)
        )

        assert result["full_name"] == "myorg/new-repo"
        call_args = mock_req.call_args
        assert call_args[0][1] == "/orgs/myorg/repos"


class TestGithubPushFile(unittest.TestCase):
    """Tests for github_push_file tool."""

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_push_new_file(self, mock_req):
        # First call (GET) raises → file doesn't exist
        # Second call (PUT) succeeds
        mock_req.side_effect = [
            RuntimeError("404"),
            {
                "content": {"sha": "abc123"},
                "commit": {"html_url": "https://github.com/user/repo/commit/abc"},
            },
        ]

        fn = github_push_file
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        result = json.loads(
            fn(repo="user/repo", path="README.md", content="# Hello")
        )

        assert result["status"] == "created"
        assert result["sha"] == "abc123"

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_push_update_existing(self, mock_req):
        mock_req.side_effect = [
            {"sha": "old_sha"},  # GET existing
            {
                "content": {"sha": "new_sha"},
                "commit": {"html_url": "https://github.com/user/repo/commit/new"},
            },
        ]

        fn = github_push_file
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        result = json.loads(
            fn(repo="user/repo", path="README.md", content="# Updated")
        )

        assert result["status"] == "updated"
        # Verify SHA was passed in PUT body for update
        put_call = mock_req.call_args_list[1]
        assert put_call[0][0] == "PUT"
        put_body = put_call[0][2] if len(put_call[0]) > 2 else put_call[1].get("body", {})
        assert put_body.get("sha") == "old_sha", f"Expected SHA 'old_sha' in PUT body, got: {put_body}"

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_push_encodes_content_base64(self, mock_req):
        mock_req.side_effect = [
            RuntimeError("404"),
            {
                "content": {"sha": "abc"},
                "commit": {"html_url": "https://example.com"},
            },
        ]

        fn = github_push_file
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        fn(repo="user/repo", path="test.txt", content="Hello World")

        put_call = mock_req.call_args_list[1]
        body = put_call[0][2] if len(put_call[0]) > 2 else put_call[1].get("body", {})
        expected_b64 = base64.b64encode(b"Hello World").decode()
        assert body.get("content") == expected_b64

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_push_url_encodes_path(self, mock_req):
        """Verify file paths with spaces/special chars are URL-encoded."""
        mock_req.side_effect = [
            RuntimeError("404"),
            {
                "content": {"sha": "abc"},
                "commit": {"html_url": "https://example.com"},
            },
        ]

        fn = github_push_file
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        fn(repo="user/repo", path="docs/my file.md", content="test")

        # GET call should have URL-encoded path
        get_call = mock_req.call_args_list[0]
        assert "docs/my%20file.md" in get_call[0][1]
        # PUT call too
        put_call = mock_req.call_args_list[1]
        assert "docs/my%20file.md" in put_call[0][1]


class TestGithubGetFile(unittest.TestCase):
    """Tests for github_get_file tool."""

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_get_file(self, mock_req):
        content = base64.b64encode(b"# Hello World").decode()
        mock_req.return_value = {"content": content}

        fn = github_get_file
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        result = fn(repo="user/repo", path="README.md")

        assert result == "# Hello World"

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_get_file_with_newlines_in_base64(self, mock_req):
        """Verify base64 content with GitHub-style newlines is handled."""
        raw = b"Hello World, this is a longer content string for testing"
        # Simulate GitHub's base64 with newlines every 60 chars
        b64 = base64.b64encode(raw).decode()
        b64_with_newlines = "\n".join(b64[i:i+60] for i in range(0, len(b64), 60))
        mock_req.return_value = {"content": b64_with_newlines}

        fn = github_get_file
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        result = fn(repo="user/repo", path="test.txt")
        assert result == raw.decode()

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_get_file_custom_branch(self, mock_req):
        content = base64.b64encode(b"dev content").decode()
        mock_req.return_value = {"content": content}

        fn = github_get_file
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        fn(repo="user/repo", path="test.py", branch="develop")

        call_path = mock_req.call_args[0][1]
        assert "ref=develop" in call_path


class TestGithubListRepos(unittest.TestCase):
    """Tests for github_list_repos tool."""

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_list_user_repos(self, mock_req):
        mock_req.return_value = [
            {
                "full_name": "user/repo1",
                "description": "First repo",
                "private": False,
                "html_url": "https://github.com/user/repo1",
                "updated_at": "2026-03-26T00:00:00Z",
            },
        ]

        fn = github_list_repos
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        result = json.loads(fn())

        assert result["count"] == 1
        assert result["repos"][0]["name"] == "user/repo1"

    @patch("platform_agent.foundation.tools.github._github_request")
    @patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"})
    def test_list_org_repos(self, mock_req):
        mock_req.return_value = []

        fn = github_list_repos
        if hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        result = json.loads(fn(org="myorg"))

        assert result["count"] == 0
        call_path = mock_req.call_args[0][1]
        assert "/orgs/myorg/repos" in call_path


class TestGithubToolsList(unittest.TestCase):
    """Tests for GITHUB_TOOLS export list."""

    def test_all_tools_in_list(self):
        assert len(GITHUB_TOOLS) == 13

    def test_tools_are_callable(self):
        for tool in GITHUB_TOOLS:
            assert callable(tool)


class TestEntrypointRegistration(unittest.TestCase):
    """Test that GitHub tools are registered in the entrypoint."""

    def test_entrypoint_imports_github_tools(self):
        """Verify the entrypoint uses GitHub tools (via FoundationStrandsAgent or direct imports)."""
        import importlib.util
        import os

        entrypoint_path = os.path.join(
            os.path.dirname(__file__), "..", "entrypoint.py"
        )
        if not os.path.exists(entrypoint_path):
            self.skipTest("entrypoint.py not found at expected path")

        with open(entrypoint_path) as f:
            source = f.read()

        # Entrypoint imports individual GitHub tools from github_tool module
        assert "from platform_agent.foundation.tools.github_tool import" in source
        assert "github_get_repo" in source


if __name__ == "__main__":
    unittest.main()


# ── github_get_tree ────────────────────────────────────────────────


class TestGithubGetTree(unittest.TestCase):
    @patch("platform_agent.foundation.tools.github._github_request")
    def test_get_tree_root(self, mock_req):
        """List files at repo root."""
        mock_req.return_value = [
            {"name": "README.md", "type": "file", "path": "README.md", "size": 1234},
            {"name": "src", "type": "dir", "path": "src", "size": 0},
        ]
        result = json.loads(github_get_tree(repo="owner/repo"))
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["entries"][0]["name"], "README.md")
        self.assertEqual(result["entries"][1]["type"], "dir")

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_get_tree_subdirectory(self, mock_req):
        """List files in a subdirectory."""
        mock_req.return_value = [
            {"name": "main.py", "type": "file", "path": "src/main.py", "size": 500},
        ]
        result = json.loads(github_get_tree(repo="owner/repo", path="src"))
        self.assertEqual(result["count"], 1)
        mock_req.assert_called_with("GET", "/repos/owner/repo/contents/src?ref=main")

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_get_tree_single_file(self, mock_req):
        """If path points to a file, return file info."""
        mock_req.return_value = {
            "name": "README.md", "type": "file", "path": "README.md",
            "size": 1234, "sha": "abc123",
        }
        result = json.loads(github_get_tree(repo="owner/repo", path="README.md"))
        self.assertEqual(result["type"], "file")

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_get_tree_404(self, mock_req):
        """404 raises RuntimeError."""
        mock_req.side_effect = RuntimeError("GitHub API 404: Not Found")
        with self.assertRaises(RuntimeError):
            github_get_tree(repo="owner/nonexistent")


# ── github_list_pr_files ──────────────────────────────────────────


class TestGithubListPrFiles(unittest.TestCase):
    @patch("platform_agent.foundation.tools.github._github_request")
    def test_list_pr_files(self, mock_req):
        """List files changed in a PR."""
        mock_req.return_value = [
            {"filename": "src/main.py", "status": "modified", "additions": 10, "deletions": 3, "changes": 13},
            {"filename": "tests/test.py", "status": "added", "additions": 25, "deletions": 0, "changes": 25},
        ]
        result = json.loads(github_list_pr_files(repo="owner/repo", pr_number=42))
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["files"][0]["status"], "modified")
        mock_req.assert_called_with("GET", "/repos/owner/repo/pulls/42/files")

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_list_pr_files_404(self, mock_req):
        """404 for nonexistent PR."""
        mock_req.side_effect = RuntimeError("GitHub API 404: Not Found")
        with self.assertRaises(RuntimeError):
            github_list_pr_files(repo="owner/repo", pr_number=99999)


# ── github_get_pr_diff ───────────────────────────────────────────


class TestGithubGetPrDiff(unittest.TestCase):
    @patch("platform_agent.foundation.tools.github._get_token")
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_get_pr_diff(self, mock_urlopen, mock_token):
        """Get full PR diff."""
        mock_token.return_value = "ghp_test"
        diff_content = "diff --git a/file.py b/file.py\n--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n"
        mock_resp = MagicMock()
        mock_resp.read.return_value = diff_content.encode()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = github_get_pr_diff(repo="owner/repo", pr_number=42)
        self.assertIn("diff --git", result)
        self.assertIn("+new", result)

    @patch("platform_agent.foundation.tools.github._get_token")
    @patch("platform_agent.foundation.tools.github.urllib.request.urlopen")
    def test_get_pr_diff_filtered(self, mock_urlopen, mock_token):
        """Get diff filtered to a specific file."""
        mock_token.return_value = "ghp_test"
        diff_content = (
            "diff --git a/src/main.py b/src/main.py\n-old\n+new\n"
            "diff --git a/tests/test.py b/tests/test.py\n-test_old\n+test_new\n"
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = diff_content.encode()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = github_get_pr_diff(repo="owner/repo", pr_number=42, file_path="src/main.py")
        self.assertIn("src/main.py", result)
        self.assertNotIn("tests/test.py", result)


# ── Updated GITHUB_TOOLS list ────────────────────────────────────


class TestGithubToolsListUpdated(unittest.TestCase):
    def test_new_tools_in_list(self):
        """All tools including commit_files are in GITHUB_TOOLS."""
        tool_names = [t.tool_name if hasattr(t, "tool_name") else t.__name__ for t in GITHUB_TOOLS]
        for expected in ["github_get_tree", "github_list_pr_files", "github_get_pr_diff", "github_commit_files"]:
            self.assertIn(expected, tool_names, f"{expected} missing from GITHUB_TOOLS")

    def test_total_tool_count(self):
        """13 total GitHub tools (10 original + 3 Sprint 2 extensions)."""
        self.assertEqual(len(GITHUB_TOOLS), 13)


# ── github_create_branch ────────────────────────────────────────────


class TestGithubCreateBranch(unittest.TestCase):
    @patch("platform_agent.foundation.tools.github._github_request")
    def test_create_branch(self, mock_req):
        """Create a branch from main."""
        mock_req.side_effect = [
            {"object": {"sha": "abc123def456"}},  # GET ref
            {"ref": "refs/heads/feat/new-feature"},  # POST ref
        ]
        result = json.loads(github_create_branch(repo="owner/repo", branch_name="feat/new-feature"))
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["branch"], "feat/new-feature")
        self.assertEqual(result["sha"], "abc123def456")
        self.assertEqual(mock_req.call_count, 2)

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_create_branch_custom_base(self, mock_req):
        """Create a branch from a non-main branch."""
        mock_req.side_effect = [
            {"object": {"sha": "xyz789"}},
            {"ref": "refs/heads/fix/bug"},
        ]
        result = json.loads(github_create_branch(repo="owner/repo", branch_name="fix/bug", from_branch="develop"))
        mock_req.assert_any_call("GET", "/repos/owner/repo/git/ref/heads/develop")

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_create_branch_404(self, mock_req):
        """404 when source branch doesn't exist."""
        mock_req.side_effect = RuntimeError("GitHub API 404: Not Found")
        with self.assertRaises(RuntimeError):
            github_create_branch(repo="owner/repo", branch_name="feat/x", from_branch="nonexistent")

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_create_branch_422_already_exists(self, mock_req):
        """422 when branch already exists."""
        mock_req.side_effect = [
            {"object": {"sha": "abc123"}},
            RuntimeError("GitHub API 422: Reference already exists"),
        ]
        with self.assertRaises(RuntimeError):
            github_create_branch(repo="owner/repo", branch_name="main")


# ── github_create_pr ────────────────────────────────────────────────


class TestGithubCreatePr(unittest.TestCase):
    @patch("platform_agent.foundation.tools.github._github_request")
    def test_create_pr(self, mock_req):
        """Create a PR."""
        mock_req.return_value = {
            "number": 42,
            "html_url": "https://github.com/owner/repo/pull/42",
            "state": "open",
            "head": {"ref": "feat/new"},
            "base": {"ref": "main"},
        }
        result = json.loads(github_create_pr(
            repo="owner/repo", title="Add feature", head="feat/new", body="Description here"
        ))
        self.assertEqual(result["number"], 42)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["head"], "feat/new")

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_create_pr_draft(self, mock_req):
        """Create a draft PR."""
        mock_req.return_value = {
            "number": 43,
            "html_url": "https://github.com/owner/repo/pull/43",
            "state": "open",
            "head": {"ref": "wip/test"},
            "base": {"ref": "main"},
        }
        github_create_pr(repo="owner/repo", title="WIP", head="wip/test", draft=True)
        call_body = mock_req.call_args[0][2]
        self.assertTrue(call_body["draft"])

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_create_pr_422_no_commits(self, mock_req):
        """422 when branches have no diff."""
        mock_req.side_effect = RuntimeError("GitHub API 422: No commits between main and feat/empty")
        with self.assertRaises(RuntimeError):
            github_create_pr(repo="owner/repo", title="Empty", head="feat/empty")

    @patch("platform_agent.foundation.tools.github._github_request")
    def test_create_pr_403_forbidden(self, mock_req):
        """403 when user lacks push access."""
        mock_req.side_effect = RuntimeError("GitHub API 403: Must have push access")
        with self.assertRaises(RuntimeError):
            github_create_pr(repo="other/repo", title="PR", head="feat/x")


# ── github_commit_files ────────────────────────────────────────────


class TestGithubCommitFiles(unittest.TestCase):
    @patch("platform_agent.foundation.tools.github._get_token", return_value="ghp_test")
    @patch("platform_agent.foundation.tools.github._github_request")
    def test_commit_multiple_files(self, mock_req, mock_token):
        """Commit multiple files in a single atomic commit."""
        mock_req.side_effect = [
            # GET ref → current HEAD
            {"object": {"sha": "head123"}},
            # POST blob (file 1)
            {"sha": "blob_readme"},
            # POST blob (file 2)
            {"sha": "blob_claude"},
            # GET commit → base tree
            {"tree": {"sha": "base_tree_sha"}},
            # POST tree
            {"sha": "new_tree_sha"},
            # POST commit
            {"sha": "new_commit_sha", "html_url": "https://github.com/owner/repo/commit/new_commit_sha"},
            # PATCH ref
            {"ref": "refs/heads/main"},
        ]
        files = [
            {"path": "README.md", "content": "# Hello"},
            {"path": "CLAUDE.md", "content": "# Agent Config"},
        ]
        result = json.loads(github_commit_files(repo="owner/repo", files=files, message="init"))
        self.assertEqual(result["status"], "committed")
        self.assertEqual(result["commit_sha"], "new_commit_sha")
        self.assertEqual(result["file_count"], 2)
        self.assertIn("README.md", result["files"])
        self.assertIn("CLAUDE.md", result["files"])
        self.assertEqual(mock_req.call_count, 7)

    @patch("platform_agent.foundation.tools.github._get_token", return_value="ghp_test")
    @patch("platform_agent.foundation.tools.github._github_request")
    def test_commit_empty_repo(self, mock_req, mock_token):
        """Commit to an empty repo (no existing HEAD)."""
        mock_req.side_effect = [
            # GET ref → 404 (empty repo)
            RuntimeError("GitHub API 404: Not Found"),
            # POST blob
            {"sha": "blob_sha"},
            # POST tree (no base_tree)
            {"sha": "tree_sha"},
            # POST commit (no parents)
            {"sha": "first_commit_sha"},
            # POST ref (create, not patch)
            {"ref": "refs/heads/main"},
        ]
        files = [{"path": "README.md", "content": "# New Repo"}]
        result = json.loads(github_commit_files(repo="owner/empty-repo", files=files))
        self.assertEqual(result["status"], "committed")
        self.assertEqual(result["commit_sha"], "first_commit_sha")
        # Should use POST (create) not PATCH (update) for ref
        last_call = mock_req.call_args_list[-1]
        self.assertEqual(last_call[0][0], "POST")  # method
        self.assertIn("git/refs", last_call[0][1])  # path

    @patch("platform_agent.foundation.tools.github._get_token", return_value="ghp_test")
    @patch("platform_agent.foundation.tools.github._github_request")
    def test_commit_single_file(self, mock_req, mock_token):
        """Single file commit also works via batch API."""
        mock_req.side_effect = [
            {"object": {"sha": "head_sha"}},
            {"sha": "blob_sha"},
            {"tree": {"sha": "base_tree"}},
            {"sha": "new_tree"},
            {"sha": "commit_sha"},
            {"ref": "refs/heads/main"},
        ]
        files = [{"path": "test.py", "content": "print('hello')"}]
        result = json.loads(github_commit_files(repo="owner/repo", files=files))
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["files"], ["test.py"])

    @patch("platform_agent.foundation.tools.github._get_token", return_value="ghp_test")
    @patch("platform_agent.foundation.tools.github._github_request")
    def test_commit_repo_not_found(self, mock_req, mock_token):
        """404 when repo doesn't exist (blob creation also fails)."""
        mock_req.side_effect = [
            RuntimeError("GitHub API 404: Repository not found"),  # GET ref
            RuntimeError("GitHub API 404: Repository not found"),  # POST blob
        ]
        with self.assertRaises(RuntimeError):
            github_commit_files(repo="nonexistent/repo", files=[{"path": "x.md", "content": "x"}])

    @patch("platform_agent.foundation.tools.github._get_token", return_value="ghp_test")
    @patch("platform_agent.foundation.tools.github._github_request")
    def test_commit_custom_branch(self, mock_req, mock_token):
        """Commit to a non-main branch."""
        mock_req.side_effect = [
            {"object": {"sha": "dev_head"}},
            {"sha": "blob_sha"},
            {"tree": {"sha": "dev_base_tree"}},
            {"sha": "new_tree"},
            {"sha": "commit_sha"},
            {"ref": "refs/heads/develop"},
        ]
        files = [{"path": "feature.py", "content": "pass"}]
        result = json.loads(github_commit_files(
            repo="owner/repo", files=files, branch="develop"
        ))
        self.assertEqual(result["branch"], "develop")
        # Verify GET ref was for develop branch
        first_call = mock_req.call_args_list[0]
        self.assertIn("heads/develop", first_call[0][1])
