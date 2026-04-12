"""GitHub integration tool — read/write GitHub repos, PRs, issues, reviews.

Uses GitHub REST API via the requests library. Requires GITHUB_TOKEN
environment variable with appropriate permissions.

Operations:
  - Read: list PRs, get PR diff, list files, list issues, get repo info
  - Write: create repo, create issue, post review, approve/merge PR,
           set branch protection, create/update files
  - Webhook: (future) parse GitHub webhook events

Uses Strands @tool decorator for proper LLM tool schema registration.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

try:
    from strands import tool as strands_tool

    _HAS_STRANDS = True
except ImportError:
    _HAS_STRANDS = False
    import functools

    def strands_tool(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_GITHUB_API = "https://api.github.com"


def _headers() -> dict[str, str]:
    """Build authorization headers from GITHUB_TOKEN env var."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN environment variable is not set")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(path: str, params: dict | None = None) -> dict | list:
    """GET request to GitHub API."""
    url = f"{_GITHUB_API}{path}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict | None = None) -> dict:
    """POST request to GitHub API."""
    url = f"{_GITHUB_API}{path}"
    resp = requests.post(url, headers=_headers(), json=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _put(path: str, data: dict | None = None) -> dict:
    """PUT request to GitHub API."""
    url = f"{_GITHUB_API}{path}"
    resp = requests.put(url, headers=_headers(), json=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _patch(path: str, data: dict | None = None) -> dict:
    """PATCH request to GitHub API."""
    url = f"{_GITHUB_API}{path}"
    resp = requests.patch(url, headers=_headers(), json=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _delete(path: str) -> bool:
    """DELETE request to GitHub API."""
    url = f"{_GITHUB_API}{path}"
    resp = requests.delete(url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    return True


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

@strands_tool
def github_get_repo(owner: str, repo: str) -> str:
    """Get repository information.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.

    Returns:
        JSON string with repo details (name, description, default branch,
        visibility, topics).
    """
    try:
        data = _get(f"/repos/{owner}/{repo}")
        return json.dumps({
            "name": data["full_name"],
            "description": data.get("description", ""),
            "default_branch": data["default_branch"],
            "visibility": "private" if data["private"] else "public",
            "topics": data.get("topics", []),
            "open_issues": data.get("open_issues_count", 0),
            "url": data["html_url"],
        }, indent=2)
    except Exception as e:
        return f"Error getting repo: {e}"


@strands_tool
def github_list_prs(
    owner: str, repo: str, state: str = "open", limit: int = 10
) -> str:
    """List pull requests for a repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        state: Filter by state: open, closed, or all.
        limit: Maximum number of PRs to return (default 10).

    Returns:
        JSON string with list of PRs (number, title, state, author, branch).
    """
    try:
        data = _get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": limit},
        )
        prs = [
            {
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "author": pr["user"]["login"],
                "head": pr["head"]["ref"],
                "base": pr["base"]["ref"],
                "url": pr["html_url"],
                "created_at": pr["created_at"],
            }
            for pr in data[:limit]
        ]
        return json.dumps(prs, indent=2)
    except Exception as e:
        return f"Error listing PRs: {e}"


@strands_tool
def github_get_pr_diff(owner: str, repo: str, pr_number: int) -> str:
    """Get the diff for a pull request.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.

    Returns:
        The unified diff text for the PR, truncated to 50000 chars if needed.
    """
    try:
        url = f"{_GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"
        headers = _headers()
        headers["Accept"] = "application/vnd.github.v3.diff"
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        diff = resp.text
        if len(diff) > 50000:
            diff = diff[:50000] + "\n\n... [truncated, diff too large]"
        return diff
    except Exception as e:
        return f"Error getting PR diff: {e}"


@strands_tool
def github_list_pr_files(owner: str, repo: str, pr_number: int) -> str:
    """List files changed in a pull request.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.

    Returns:
        JSON string with list of changed files (filename, status,
        additions, deletions, patch preview).
    """
    try:
        data = _get(f"/repos/{owner}/{repo}/pulls/{pr_number}/files")
        files = [
            {
                "filename": f["filename"],
                "status": f["status"],
                "additions": f["additions"],
                "deletions": f["deletions"],
                "changes": f["changes"],
                "patch": (f.get("patch", ""))[:500],
            }
            for f in data
        ]
        return json.dumps(files, indent=2)
    except Exception as e:
        return f"Error listing PR files: {e}"


@strands_tool
def github_list_issues(
    owner: str, repo: str, state: str = "open", labels: str = "",
    limit: int = 10,
) -> str:
    """List issues for a repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        state: Filter by state: open, closed, or all.
        labels: Comma-separated label names to filter by.
        limit: Maximum number of issues to return.

    Returns:
        JSON string with list of issues (number, title, state, labels, assignee).
    """
    try:
        params = {"state": state, "per_page": limit}
        if labels:
            params["labels"] = labels
        data = _get(f"/repos/{owner}/{repo}/issues", params=params)
        # Filter out PRs (GitHub API returns PRs as issues too)
        issues = [
            {
                "number": i["number"],
                "title": i["title"],
                "state": i["state"],
                "labels": [l["name"] for l in i.get("labels", [])],
                "assignee": i["assignee"]["login"] if i.get("assignee") else None,
                "url": i["html_url"],
                "created_at": i["created_at"],
            }
            for i in data[:limit]
            if "pull_request" not in i
        ]
        return json.dumps(issues, indent=2)
    except Exception as e:
        return f"Error listing issues: {e}"


@strands_tool
def github_get_file(owner: str, repo: str, path: str, ref: str = "") -> str:
    """Get the contents of a file from a repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        path: File path within the repository.
        ref: Branch, tag, or commit SHA (default: repo default branch).

    Returns:
        The decoded file content (UTF-8 text), truncated to 50000 chars.
    """
    try:
        import base64

        params = {}
        if ref:
            params["ref"] = ref
        data = _get(f"/repos/{owner}/{repo}/contents/{path}", params=params)
        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        else:
            content = data.get("content", "")
        if len(content) > 50000:
            content = content[:50000] + "\n\n... [truncated]"
        return content
    except Exception as e:
        return f"Error getting file: {e}"


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

@strands_tool
def github_create_issue(
    owner: str, repo: str, title: str, body: str,
    labels: Optional[str] = None, assignee: Optional[str] = None,
) -> str:
    """Create a new issue in a repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        title: Issue title.
        body: Issue body (Markdown supported).
        labels: Comma-separated label names to add.
        assignee: GitHub username to assign.

    Returns:
        JSON string with the created issue details (number, url).
    """
    try:
        data: dict = {"title": title, "body": body}
        if labels:
            data["labels"] = [l.strip() for l in labels.split(",")]
        if assignee:
            data["assignees"] = [assignee]
        result = _post(f"/repos/{owner}/{repo}/issues", data)
        return json.dumps({
            "number": result["number"],
            "title": result["title"],
            "url": result["html_url"],
            "state": result["state"],
        }, indent=2)
    except Exception as e:
        return f"Error creating issue: {e}"


@strands_tool
def github_create_pr_review(
    owner: str, repo: str, pr_number: int,
    body: str, event: str = "COMMENT",
    comments: Optional[str] = None,
) -> str:
    """Create a review on a pull request.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.
        body: Overall review body text.
        event: Review action: APPROVE, REQUEST_CHANGES, or COMMENT.
        comments: JSON string of line-level comments. Each comment is an
                  object with keys: path, line (or position), body.
                  Example: [{"path":"src/main.py","line":42,"body":"Fix this"}]

    Returns:
        JSON string with the review details (id, state, url).
    """
    try:
        data: dict = {"body": body, "event": event}
        if comments:
            parsed = json.loads(comments)
            data["comments"] = parsed
        result = _post(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews", data
        )
        return json.dumps({
            "id": result["id"],
            "state": result["state"],
            "url": result["html_url"],
        }, indent=2)
    except Exception as e:
        return f"Error creating review: {e}"


@strands_tool
def github_merge_pr(
    owner: str, repo: str, pr_number: int,
    merge_method: str = "squash",
    commit_title: Optional[str] = None,
) -> str:
    """Merge a pull request.

    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.
        merge_method: Merge method: merge, squash, or rebase.
        commit_title: Custom commit title for squash/merge.

    Returns:
        JSON string with merge result (sha, merged, message).
    """
    try:
        data: dict = {"merge_method": merge_method}
        if commit_title:
            data["commit_title"] = commit_title
        result = _put(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/merge", data
        )
        return json.dumps({
            "sha": result.get("sha", ""),
            "merged": result.get("merged", False),
            "message": result.get("message", ""),
        }, indent=2)
    except Exception as e:
        return f"Error merging PR: {e}"


@strands_tool
def github_create_repo(
    name: str, description: str = "", private: bool = True,
    auto_init: bool = True,
) -> str:
    """Create a new GitHub repository.

    Args:
        name: Repository name.
        description: Repository description.
        private: Whether the repo should be private (default True).
        auto_init: Initialize with a README (default True).

    Returns:
        JSON string with the created repo details (full_name, url, default_branch).
    """
    try:
        data = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": auto_init,
        }
        result = _post("/user/repos", data)
        return json.dumps({
            "full_name": result["full_name"],
            "url": result["html_url"],
            "default_branch": result["default_branch"],
            "private": result["private"],
        }, indent=2)
    except Exception as e:
        return f"Error creating repo: {e}"


@strands_tool
def github_create_or_update_file(
    owner: str, repo: str, path: str, content: str,
    message: str, branch: str = "",
) -> str:
    """Create or update a file in a repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        path: File path within the repository.
        content: File content (plain text, will be base64-encoded).
        message: Commit message.
        branch: Target branch (default: repo default branch).

    Returns:
        JSON string with commit details (sha, url).
    """
    try:
        import base64

        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        data: dict = {
            "message": message,
            "content": encoded,
        }
        if branch:
            data["branch"] = branch

        # Check if file exists (to get SHA for update)
        try:
            params = {}
            if branch:
                params["ref"] = branch
            existing = _get(
                f"/repos/{owner}/{repo}/contents/{path}", params=params
            )
            data["sha"] = existing["sha"]
        except requests.HTTPError:
            pass  # File doesn't exist, will create

        result = _put(f"/repos/{owner}/{repo}/contents/{path}", data)
        return json.dumps({
            "sha": result["commit"]["sha"],
            "url": result["content"]["html_url"],
            "path": path,
        }, indent=2)
    except Exception as e:
        return f"Error creating/updating file: {e}"


@strands_tool
def github_set_branch_protection(
    owner: str, repo: str, branch: str = "main",
    required_reviews: int = 1, dismiss_stale: bool = True,
    enforce_admins: bool = False,
) -> str:
    """Set branch protection rules on a repository branch.

    Args:
        owner: Repository owner.
        repo: Repository name.
        branch: Branch name to protect (default: main).
        required_reviews: Number of required approving reviews.
        dismiss_stale: Dismiss stale reviews when new commits are pushed.
        enforce_admins: Enforce rules for administrators too.

    Returns:
        Confirmation message with the protection settings applied.
    """
    try:
        data = {
            "required_status_checks": None,
            "enforce_admins": enforce_admins,
            "required_pull_request_reviews": {
                "required_approving_review_count": required_reviews,
                "dismiss_stale_reviews": dismiss_stale,
            },
            "restrictions": None,
        }
        _put(f"/repos/{owner}/{repo}/branches/{branch}/protection", data)
        return (
            f"Branch protection set on {owner}/{repo}:{branch} — "
            f"{required_reviews} review(s) required, "
            f"dismiss stale={dismiss_stale}, enforce admins={enforce_admins}"
        )
    except Exception as e:
        return f"Error setting branch protection: {e}"


@strands_tool
def github_add_labels(owner: str, repo: str, labels: str) -> str:
    """Create labels in a repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        labels: JSON string of labels to create. Each label is an object
                with keys: name, color (hex without #), description.
                Example: [{"name":"bug","color":"d73a4a","description":"Bug report"}]

    Returns:
        Summary of labels created.
    """
    try:
        parsed = json.loads(labels)
        created = []
        for label in parsed:
            try:
                _post(f"/repos/{owner}/{repo}/labels", label)
                created.append(label["name"])
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 422:
                    created.append(f"{label['name']} (already exists)")
                else:
                    created.append(f"{label['name']} (error: {e})")
        return f"Labels: {', '.join(created)}"
    except Exception as e:
        return f"Error adding labels: {e}"
