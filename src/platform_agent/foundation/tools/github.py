"""GitHub tools — Strands @tool wrappers for GitHub API operations.

Provides create_repo, push_file, get_file, list_repos as Strands tools
that the foundation agent can call via LLM tool_use.

Authentication (in priority order):
    1. AgentCore Identity — @requires_api_key decorator (preferred in Runtime)
    2. GITHUB_TOKEN environment variable (fallback for local dev)

Environment:
    GITHUB_ORG: Default GitHub organization (optional)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

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

# AgentCore Identity credential provider name for GitHub PAT
GITHUB_CREDENTIAL_PROVIDER = os.environ.get(
    "GITHUB_CREDENTIAL_PROVIDER", "github-pat"
)

GITHUB_API = "https://api.github.com"

# Cache the token with TTL to pick up rotations without container restart
_cached_identity_token: str | None = None
_cached_identity_token_ts: float = 0
TOKEN_CACHE_TTL = 300  # 5 minutes


def _get_token_via_requires_api_key() -> str | None:
    """Get GitHub token via @requires_api_key decorator.

    Uses the official AgentCore SDK decorator pattern. The decorator
    automatically handles workload access token retrieval (from runtime
    context vars) and API key fetching. It also handles sync vs async
    environments (uses ThreadPoolExecutor + context var copy when a loop
    is running).

    Pattern matches official samples: awslabs/amazon-bedrock-agentcore-samples
    03-integrations/strands_openai_identity.py
    """
    global _cached_identity_token, _cached_identity_token_ts

    # Return cached token if still valid
    if _cached_identity_token and (time.time() - _cached_identity_token_ts) < TOKEN_CACHE_TTL:
        return _cached_identity_token

    try:
        from bedrock_agentcore.identity.auth import requires_api_key
        import asyncio

        @requires_api_key(provider_name=GITHUB_CREDENTIAL_PROVIDER)
        def _fetch_github_pat(*, api_key: str = "") -> str:
            return api_key

        result = _fetch_github_pat()
        # Safety: if decorator returns a coroutine (future SDK change), resolve it
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        token = result
        if token:
            _cached_identity_token = token
            _cached_identity_token_ts = time.time()
            logger.info("GitHub token retrieved via Identity (provider: %s)", GITHUB_CREDENTIAL_PROVIDER)
            return token
        return None

    except ImportError:
        logger.debug("bedrock_agentcore SDK not available — skipping Identity")
        return None
    except Exception as e:
        logger.warning("Identity token retrieval failed: %s — falling back to env var", e)
        return None


def _get_token() -> str:
    """Get GitHub token — tries AgentCore Identity first, falls back to env var.

    Priority:
        1. AgentCore Identity @requires_api_key (in AgentCore Runtime)
        2. GITHUB_TOKEN environment variable (local dev / fallback)
    """
    # Try AgentCore Identity first
    token = _get_token_via_requires_api_key()
    if token:
        return token

    # Fallback to environment variable
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise ValueError(
            "GitHub authentication not configured. Either:\n"
            "  1. Set up AgentCore Identity with a 'github-pat' credential provider, or\n"
            "  2. Set the GITHUB_TOKEN environment variable."
        )
    logger.debug("Using GITHUB_TOKEN from environment variable")
    return token


def _github_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
    _retries: int = 3,
) -> dict[str, Any] | list[Any]:
    """Make an authenticated GitHub API request.

    Automatically retries on 429 (rate limit) responses up to *_retries* times,
    respecting the ``Retry-After`` header when present.
    """
    tok = token or _get_token()
    url = f"{GITHUB_API}{path}" if path.startswith("/") else path

    data = json.dumps(body).encode() if body else None

    for attempt in range(_retries + 1):
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {tok}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )

        t0 = time.time()
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read().decode())
                logger.info(
                    "GitHub API %s %s → %d (%dms)",
                    method, path, resp.status, int((time.time() - t0) * 1000),
                )
                return result
        except urllib.error.HTTPError as e:
            retry_after = e.headers.get("Retry-After") if e.headers else None
            ratelimit_remaining = e.headers.get("x-ratelimit-remaining") if e.headers else None

            # Retry on 429 always; 403 only if it's a secondary rate limit
            is_rate_limit = (
                e.code == 429
                or (e.code == 403 and (retry_after or ratelimit_remaining == "0"))
            )

            if is_rate_limit and attempt < _retries:
                # Consume the error body to avoid connection leaks
                try:
                    e.read()
                except Exception:
                    pass

                try:
                    wait = int(float(retry_after)) if retry_after else (2 ** attempt)
                except (ValueError, TypeError):
                    wait = 2 ** attempt

                logger.warning(
                    "GitHub API %d, retry %d/%d after %ds",
                    e.code, attempt + 1, _retries, wait,
                )
                time.sleep(wait)
                continue

            error_body = e.read().decode() if e.fp else ""
            logger.error("GitHub API error %d: %s", e.code, error_body)
            raise RuntimeError(f"GitHub API {e.code}: {error_body}") from e

    # Should not be reached, but just in case
    raise RuntimeError("GitHub API request failed after retries")


@strands_tool
def github_create_repo(
    name: str,
    description: str = "",
    org: str = "",
    private: bool = True,
) -> str:
    """Create a new GitHub repository.

    Creates a repo under the specified org or the authenticated user's account.
    Use this when a team needs a new project repository.

    Args:
        name: Repository name (kebab-case, e.g. 'customer-support-agent').
        description: Short description of the repository.
        org: GitHub organization. Uses GITHUB_ORG env var if empty.
        private: Whether the repo should be private. Default true.

    Returns:
        JSON string with repo URL, clone URL, full name, and visibility.
    """
    target_org = org or os.environ.get("GITHUB_ORG", "")

    body: dict[str, Any] = {
        "name": name,
        "description": description,
        "private": private,
        "auto_init": True,  # Initialize with README to avoid empty repo race condition
    }

    path = f"/orgs/{target_org}/repos" if target_org else "/user/repos"
    result = _github_request("POST", path, body)

    return json.dumps({
        "status": "created",
        "repo_url": result["html_url"],
        "clone_url": result["clone_url"],
        "full_name": result["full_name"],
        "private": result["private"],
    })


@strands_tool
def github_push_file(
    repo: str,
    path: str,
    content: str,
    message: str = "Add file via Plato agent",
    branch: str = "main",
) -> str:
    """Push a file to a GitHub repository.

    Creates the file if it doesn't exist, updates it if it does.
    Uses the GitHub Contents API for single-file operations.

    Args:
        repo: Full repo name (e.g. 'org/customer-support-agent').
        path: File path in the repo (e.g. 'CLAUDE.md').
        content: File content as text.
        message: Commit message.
        branch: Target branch. Default 'main'.

    Returns:
        JSON string with status, path, SHA, and commit URL.
    """
    # Check if file exists (to get SHA for updates)
    sha = None
    encoded_path = urllib.parse.quote(path, safe="/")
    try:
        existing = _github_request(
            "GET", f"/repos/{repo}/contents/{encoded_path}?ref={branch}"
        )
        if isinstance(existing, dict):
            sha = existing.get("sha")
    except RuntimeError:
        pass  # File doesn't exist yet

    body: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha

    # Retry on 409 "Git Repository is empty" — happens when pushing to a
    # newly created repo before GitHub finishes async init
    for push_attempt in range(3):
        try:
            result = _github_request("PUT", f"/repos/{repo}/contents/{encoded_path}", body)
            break
        except RuntimeError as e:
            if ("409" in str(e) or "empty" in str(e).lower()) and push_attempt < 2:
                logger.warning("Push got 409 (repo may still be initializing), retry %d/3", push_attempt + 1)
                time.sleep(2)
                continue
            raise

    return json.dumps({
        "status": "updated" if sha else "created",
        "path": path,
        "sha": result["content"]["sha"],
        "commit_url": result["commit"]["html_url"],
    })


@strands_tool
def github_get_file(
    repo: str,
    path: str,
    branch: str = "main",
) -> str:
    """Read a file from a GitHub repository.

    Retrieves and decodes a single file's contents from the specified branch.

    Args:
        repo: Full repo name (e.g. 'org/customer-support-agent').
        path: File path in the repo.
        branch: Branch to read from. Default 'main'.

    Returns:
        The file content as a string.
    """
    result = _github_request(
        "GET", f"/repos/{repo}/contents/{urllib.parse.quote(path, safe='/')}?ref={branch}"
    )
    content_b64 = result.get("content", "")
    # GitHub API returns base64 with newlines every 60 chars; strip them
    return base64.b64decode(content_b64.replace("\n", "")).decode()


@strands_tool
def github_list_repos(
    org: str = "",
    sort: str = "updated",
    per_page: int = 10,
) -> str:
    """List GitHub repositories for the authenticated user or organization.

    Args:
        org: GitHub organization. Lists user repos if empty.
        sort: Sort by 'created', 'updated', 'pushed', or 'full_name'.
        per_page: Number of results to return. Default 10.

    Returns:
        JSON string with repo list including name, description, URL, and update time.
    """
    target_org = org or os.environ.get("GITHUB_ORG", "")

    if target_org:
        path = f"/orgs/{target_org}/repos?sort={sort}&per_page={per_page}"
    else:
        path = f"/user/repos?sort={sort}&per_page={per_page}"

    results = _github_request("GET", path)

    repos = [
        {
            "name": r["full_name"],
            "description": r.get("description", ""),
            "private": r["private"],
            "url": r["html_url"],
            "updated": r["updated_at"],
        }
        for r in results
    ]

    return json.dumps({"repos": repos, "count": len(repos)})


@strands_tool
def github_get_tree(
    repo: str,
    path: str = "",
    branch: str = "main",
) -> str:
    """Get the directory tree of a GitHub repository.

    Lists files and directories at the specified path. Use to browse
    a repo's structure before reading specific files.

    Args:
        repo: Full repo name (e.g. 'aws-samples/sample-agent-greenhouse').
        path: Directory path in the repo. Empty string for root.
        branch: Branch to browse. Default 'main'.

    Returns:
        JSON string with list of entries (name, type, path, size).
    """
    encoded_path = urllib.parse.quote(path, safe="/")
    api_path = f"/repos/{repo}/contents/{encoded_path}?ref={branch}"
    result = _github_request("GET", api_path)

    # If result is a dict, it's a single file (not a directory)
    if isinstance(result, dict):
        return json.dumps({
            "type": "file",
            "path": result.get("path", path),
            "size": result.get("size", 0),
            "sha": result.get("sha", ""),
        })

    entries = [
        {
            "name": item["name"],
            "type": item["type"],  # "file" or "dir"
            "path": item["path"],
            "size": item.get("size", 0),
        }
        for item in result
    ]

    return json.dumps({"entries": entries, "count": len(entries)})


@strands_tool
def github_list_pr_files(
    repo: str,
    pr_number: int,
) -> str:
    """List files changed in a pull request.

    Shows which files were added, modified, or removed in a PR,
    along with line change counts. Use before get_pr_diff to decide
    which files to review in detail.

    Args:
        repo: Full repo name (e.g. 'aws-samples/sample-agent-greenhouse').
        pr_number: The pull request number.

    Returns:
        JSON string with list of changed files (filename, status, additions, deletions).
    """
    result = _github_request("GET", f"/repos/{repo}/pulls/{pr_number}/files")

    files = [
        {
            "filename": f["filename"],
            "status": f["status"],  # added, modified, removed, renamed
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
            "changes": f.get("changes", 0),
        }
        for f in result
    ]

    return json.dumps({"files": files, "count": len(files)})


@strands_tool
def github_get_pr_diff(
    repo: str,
    pr_number: int,
    file_path: str = "",
) -> str:
    """Get the diff of a pull request.

    Retrieves the unified diff for a PR. Optionally filter to a single file.
    Use for code review — understand exactly what changed.

    Args:
        repo: Full repo name (e.g. 'aws-samples/sample-agent-greenhouse').
        pr_number: The pull request number.
        file_path: Optional file path to get diff for only one file.

    Returns:
        The diff as a string (unified diff format).
    """
    # Get the full diff via the Accept header
    tok = _get_token()
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"

    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github.diff",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    t0 = time.time()
    with urllib.request.urlopen(req) as resp:
        diff_text = resp.read().decode()
        logger.info(
            "GitHub API GET %s → %d (%dms)",
            f"/repos/{repo}/pulls/{pr_number} (diff)",
            resp.status, int((time.time() - t0) * 1000),
        )

    if file_path and diff_text:
        # Filter to specific file
        lines = diff_text.split("\n")
        filtered = []
        in_target = False
        for line in lines:
            if line.startswith("diff --git"):
                in_target = file_path in line
            if in_target:
                filtered.append(line)
        if filtered:
            return "\n".join(filtered)

    # Truncate very large diffs
    max_chars = 50000
    if len(diff_text) > max_chars:
        diff_text = diff_text[:max_chars] + f"\n\n... [truncated, {len(diff_text)} total chars]"

    return diff_text


@strands_tool
def github_create_branch(
    repo: str,
    branch_name: str,
    from_branch: str = "main",
) -> str:
    """Create a new branch in a GitHub repository.

    Creates a branch from an existing branch's HEAD commit.
    Use before pushing changes to keep main branch clean.

    Args:
        repo: Full repo name (e.g. 'aws-samples/sample-agent-greenhouse').
        branch_name: Name for the new branch (e.g. 'feat/new-feature').
        from_branch: Source branch to branch from. Default 'main'.

    Returns:
        JSON string with branch name, SHA, and ref.
    """
    # Get the SHA of the source branch
    ref_result = _github_request("GET", f"/repos/{repo}/git/ref/heads/{from_branch}")
    sha = ref_result["object"]["sha"]

    # Create the new branch
    result = _github_request("POST", f"/repos/{repo}/git/refs", {
        "ref": f"refs/heads/{branch_name}",
        "sha": sha,
    })

    return json.dumps({
        "status": "created",
        "branch": branch_name,
        "sha": sha,
        "ref": result["ref"],
    })


@strands_tool
def github_create_pr(
    repo: str,
    title: str,
    head: str,
    base: str = "main",
    body: str = "",
    draft: bool = False,
) -> str:
    """Create a pull request in a GitHub repository.

    Opens a PR to merge changes from head branch into base branch.
    The head branch must already exist and have commits ahead of base.

    Args:
        repo: Full repo name (e.g. 'aws-samples/sample-agent-greenhouse').
        title: PR title.
        head: Source branch with changes.
        base: Target branch to merge into. Default 'main'.
        body: PR description (markdown supported).
        draft: Create as draft PR. Default false.

    Returns:
        JSON string with PR number, URL, state, and branch info.
    """
    result = _github_request("POST", f"/repos/{repo}/pulls", {
        "title": title,
        "head": head,
        "base": base,
        "body": body,
        "draft": draft,
    })

    return json.dumps({
        "status": "created",
        "number": result["number"],
        "url": result["html_url"],
        "state": result["state"],
        "head": result["head"]["ref"],
        "base": result["base"]["ref"],
    })


@strands_tool
def github_commit_files(
    repo: str,
    files: list[dict[str, str]],
    message: str = "Add files via Plato agent",
    branch: str = "main",
) -> str:
    """Commit multiple files to a GitHub repository in a single atomic commit.

    Uses the Git Data API (blob → tree → commit → update ref) to avoid
    SHA conflicts when creating or updating multiple files at once.
    This is the preferred method when pushing more than one file.

    For single file operations, use github_push_file instead.

    Args:
        files: List of file objects, each with 'path' and 'content' keys.
               Example: [{"path": "README.md", "content": "# Hello"}, ...]
        repo: Full repo name (e.g. 'aws-samples/sample-agent-greenhouse').
        message: Commit message.
        branch: Target branch. Default 'main'.

    Returns:
        JSON string with status, commit SHA, commit URL, and list of files committed.
    """
    token = _get_token()

    # Step 1: Get the current HEAD SHA of the branch
    try:
        ref_result = _github_request(
            "GET", f"/repos/{repo}/git/ref/heads/{branch}", token=token
        )
        base_sha = ref_result["object"]["sha"]
    except RuntimeError as e:
        # Branch might not exist yet (empty repo) — create initial commit
        if "404" in str(e) or "409" in str(e):
            base_sha = None
        else:
            raise

    # Step 2: Create blobs for each file (retry on 409 for newly created repos)
    tree_items = []
    for f in files:
        for blob_attempt in range(5):
            try:
                blob_result = _github_request(
                    "POST",
                    f"/repos/{repo}/git/blobs",
                    {"content": f["content"], "encoding": "utf-8"},
                    token=token,
                )
                break
            except RuntimeError as e:
                if ("409" in str(e) or "empty" in str(e).lower()) and blob_attempt < 4:
                    logger.warning("Blob creation got 409 (repo may still be initializing), retry %d/5", blob_attempt + 1)
                    time.sleep(3)
                    continue
                raise
        tree_items.append({
            "path": f["path"],
            "mode": "100644",  # regular file
            "type": "blob",
            "sha": blob_result["sha"],
        })

    # Step 3: Create a tree
    tree_body: dict[str, Any] = {"tree": tree_items}
    if base_sha:
        # Get the base tree to layer our changes on top
        commit_result = _github_request(
            "GET", f"/repos/{repo}/git/commits/{base_sha}", token=token
        )
        tree_body["base_tree"] = commit_result["tree"]["sha"]

    tree_result = _github_request(
        "POST", f"/repos/{repo}/git/trees", tree_body, token=token
    )

    # Step 4: Create a commit
    commit_body: dict[str, Any] = {
        "message": message,
        "tree": tree_result["sha"],
    }
    if base_sha:
        commit_body["parents"] = [base_sha]

    new_commit = _github_request(
        "POST", f"/repos/{repo}/git/commits", commit_body, token=token
    )

    # Step 5: Update the branch ref to point to the new commit
    if base_sha:
        _github_request(
            "PATCH",
            f"/repos/{repo}/git/refs/heads/{branch}",
            {"sha": new_commit["sha"]},
            token=token,
        )
    else:
        # Create the branch ref (first commit in empty repo)
        _github_request(
            "POST",
            f"/repos/{repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]},
            token=token,
        )

    return json.dumps({
        "status": "committed",
        "commit_sha": new_commit["sha"],
        "commit_url": new_commit.get("html_url", f"https://github.com/{repo}/commit/{new_commit['sha']}"),
        "files": [f["path"] for f in files],
        "file_count": len(files),
        "branch": branch,
    })


@strands_tool
def github_create_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> str:
    """Create a GitHub issue.

    Args:
        repo: Repository in 'owner/repo' format.
        title: Issue title.
        body: Issue body (markdown supported).
        labels: Optional list of label names to apply.

    Returns:
        JSON string with issue number, URL, and status.
    """
    token = _get_token()
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
    }
    if labels:
        payload["labels"] = labels

    result = _github_request("POST", f"/repos/{repo}/issues", payload, token=token)

    return json.dumps({
        "status": "created",
        "number": result["number"],
        "url": result["html_url"],
        "title": result["title"],
    })


@strands_tool
def github_create_review(
    repo: str,
    pr_number: int,
    body: str,
    event: str = "COMMENT",
    comments: list[dict] | None = None,
) -> str:
    """Post a PR review.

    Posts a review on a pull request with an optional event type and
    inline comments.

    Args:
        repo: Repository in 'owner/repo' format.
        pr_number: Pull request number.
        body: Review body text.
        event: Review event type: APPROVE, REQUEST_CHANGES, or COMMENT.
        comments: Optional list of inline comment dicts, each with keys
                  'path', 'position' (or 'line'), and 'body'.

    Returns:
        JSON string with review ID, state, and status.
    """
    valid_events = {"APPROVE", "REQUEST_CHANGES", "COMMENT"}
    event_upper = event.upper()
    if event_upper not in valid_events:
        return json.dumps({
            "status": "error",
            "message": f"Invalid event '{event}'. Must be one of: {sorted(valid_events)}",
        })

    token = _get_token()
    payload: dict[str, Any] = {
        "body": body,
        "event": event_upper,
    }
    if comments:
        payload["comments"] = comments

    result = _github_request(
        "POST",
        f"/repos/{repo}/pulls/{pr_number}/reviews",
        payload,
        token=token,
    )

    return json.dumps({
        "status": "created",
        "review_id": result["id"],
        "state": result.get("state", event_upper),
        "html_url": result.get("html_url", ""),
    })


@strands_tool
def github_list_prs(
    repo: str,
    state: str = "open",
    per_page: int = 10,
) -> str:
    """List pull requests for a repository.

    Args:
        repo: Repository in 'owner/repo' format.
        state: Filter by state: 'open', 'closed', or 'all'.
        per_page: Number of results per page (max 100).

    Returns:
        JSON string with list of PRs and count.
    """
    valid_states = {"open", "closed", "all"}
    if state not in valid_states:
        return json.dumps({
            "status": "error",
            "message": f"Invalid state '{state}'. Must be one of: {sorted(valid_states)}",
        })

    token = _get_token()
    params = urllib.parse.urlencode({"state": state, "per_page": min(per_page, 100)})
    result = _github_request(
        "GET",
        f"/repos/{repo}/pulls?{params}",
        token=token,
    )

    prs = []
    if isinstance(result, list):
        for pr in result:
            prs.append({
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "url": pr["html_url"],
                "head": pr.get("head", {}).get("ref", ""),
                "base": pr.get("base", {}).get("ref", ""),
                "user": pr.get("user", {}).get("login", ""),
                "updated": pr.get("updated_at", ""),
            })

    return json.dumps({
        "prs": prs,
        "count": len(prs),
    })


# All GitHub tools for easy import
GITHUB_TOOLS = [
    github_create_repo,
    github_push_file,
    github_get_file,
    github_list_repos,
    github_get_tree,
    github_list_pr_files,
    github_get_pr_diff,
    github_create_branch,
    github_create_pr,
    github_commit_files,
    github_create_issue,
    github_create_review,
    github_list_prs,
]
