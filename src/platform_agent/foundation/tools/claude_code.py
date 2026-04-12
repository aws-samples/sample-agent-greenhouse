"""Claude Code CLI tool — wraps the CC CLI as a Strands tool function.

Runs Claude Code as a subprocess within the same container, using
--print and --permission-mode bypassPermissions flags.

Configured to use Amazon Bedrock via IAM for model inference.

Uses Strands @tool decorator for proper LLM tool schema registration.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

try:
    from strands import tool as strands_tool

    _HAS_STRANDS = True
except ImportError:
    _HAS_STRANDS = False
    import functools

    # Fallback: identity decorator that preserves function metadata
    def strands_tool(fn):  # type: ignore[misc]
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper


def _build_cc_command(task: str, workdir: str = ".") -> list[str]:
    """Build the command-line arguments for Claude Code CLI.

    Args:
        task: The task prompt to send to Claude Code.
        workdir: Working directory (used as cwd, not in args).

    Returns:
        List of command arguments.
    """
    cmd = [
        "claude",
        "--print",
        "--permission-mode", "bypassPermissions",
        "--bare",
    ]

    # Use Bedrock model if configured via env var
    model = os.environ.get("ANTHROPIC_MODEL")
    if model:
        cmd.extend(["--model", model])

    cmd.append(task)
    return cmd


def _build_cc_env() -> dict[str, str]:
    """Build environment variables for Claude Code subprocess.

    Ensures Bedrock-related env vars are passed through.

    Returns:
        Environment dict for subprocess.
    """
    env = os.environ.copy()
    # Ensure Bedrock mode is set
    env["CLAUDE_CODE_USE_BEDROCK"] = "1"
    # Disable telemetry and interactive features in container
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def _parse_cc_output(stdout: str, stderr: str, returncode: int) -> str:
    """Parse Claude Code CLI output into a result string.

    Args:
        stdout: Standard output from the process.
        stderr: Standard error from the process.
        returncode: Process return code.

    Returns:
        Parsed result string.
    """
    if returncode == 0:
        return stdout.strip() if stdout.strip() else stderr.strip()

    parts = []
    if stdout.strip():
        parts.append(stdout.strip())
    if stderr.strip():
        parts.append(f"Error (exit code {returncode}): {stderr.strip()}")
    elif not parts:
        parts.append(f"Command failed with exit code {returncode}")
    return "\n".join(parts)


@strands_tool
def claude_code(task: str, workdir: str = ".", timeout: int = 300) -> str:
    """Run a coding task using Claude Code CLI.

    Executes the Claude Code CLI as a subprocess with --print mode
    and bypassPermissions. Uses Amazon Bedrock for model inference
    via IAM credentials (no API key needed).

    Use this for complex coding tasks like refactoring, writing new
    features, fixing bugs, or code review.

    Args:
        task: The task description/prompt for Claude Code.
        workdir: Working directory for the subprocess.
        timeout: Maximum execution time in seconds (default: 300).

    Returns:
        The text output from Claude Code, or an error message.
    """
    cmd = _build_cc_command(task, workdir)
    env = _build_cc_env()

    logger.info("Executing Claude Code: %s", " ".join(cmd[:6]) + "...")

    try:
        result = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        output = _parse_cc_output(result.stdout, result.stderr, result.returncode)
        logger.info(
            "Claude Code completed (exit=%d, stdout=%d chars, stderr=%d chars)",
            result.returncode, len(result.stdout), len(result.stderr),
        )
        return output

    except subprocess.TimeoutExpired:
        return f"Claude Code timed out after {timeout} seconds."

    except FileNotFoundError:
        return (
            "Claude Code CLI not found. Ensure 'claude' is installed and "
            "available on PATH."
        )

    except Exception as exc:
        logger.error("Claude Code execution failed", exc_info=True)
        return f"Claude Code execution failed: {exc}"
