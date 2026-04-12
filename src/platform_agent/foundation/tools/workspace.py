"""Workspace file tools — read/write memory and skill files.

These are @tool functions that the Strands agent can call to interact
with the workspace file system for memory persistence and skill reading.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def read_workspace_file(filepath: str, workspace_dir: str) -> str:
    """Read a file from the workspace directory.

    Args:
        filepath: Relative path within the workspace.
        workspace_dir: Root workspace directory.

    Returns:
        File contents as string, or error message.
    """
    try:
        full_path = Path(workspace_dir) / filepath
        if not full_path.is_file():
            return f"File not found: {filepath}"
        return full_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error reading {filepath}: {exc}"


def write_workspace_file(filepath: str, content: str, workspace_dir: str) -> str:
    """Write a file to the workspace directory.

    Args:
        filepath: Relative path within the workspace.
        content: Content to write.
        workspace_dir: Root workspace directory.

    Returns:
        Success or error message.
    """
    try:
        full_path = Path(workspace_dir) / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return f"Written: {filepath}"
    except Exception as exc:
        return f"Error writing {filepath}: {exc}"


def list_workspace_files(directory: str, workspace_dir: str) -> str:
    """List files in a workspace subdirectory.

    Args:
        directory: Relative subdirectory path.
        workspace_dir: Root workspace directory.

    Returns:
        Newline-separated list of filenames, or error message.
    """
    try:
        full_path = Path(workspace_dir) / directory
        if not full_path.is_dir():
            return f"Directory not found: {directory}"
        files = sorted(f.name for f in full_path.iterdir() if f.is_file())
        return "\n".join(files) if files else "(empty directory)"
    except Exception as exc:
        return f"Error listing {directory}: {exc}"
