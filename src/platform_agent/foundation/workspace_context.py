"""Workspace Context Auto-Injection — loads project instruction files.

Scans the workspace for well-known instruction files (AGENTS.md, CLAUDE.md,
.cursorrules, etc.) and combines their content for injection into the
system prompt.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum characters to read from each file to avoid context bloat.
_MAX_CHARS_PER_FILE = 4000


class WorkspaceContextLoader:
    """Loads project-level instruction files for system prompt injection.

    Scans the workspace for known instruction files and returns their
    combined content with section headers.

    Args:
        workspace_dir: Path to the workspace root directory.
        enabled: If False, load_context returns an empty string.
    """

    KNOWN_FILES: list[str] = [
        "AGENTS.md",
        "CLAUDE.md",
        ".cursorrules",
        ".github/copilot-instructions.md",
    ]

    def __init__(self, workspace_dir: str, enabled: bool = True) -> None:
        self.workspace_dir = workspace_dir
        self.enabled = enabled

    def load_context(self) -> str:
        """Scan workspace for known instruction files and return combined content.

        Each found file is included with a section header like:
            ## Project Context (from AGENTS.md)

        Files are truncated to _MAX_CHARS_PER_FILE characters each.

        Returns:
            Combined content string, or empty string if disabled or no files found.
        """
        if not self.enabled:
            return ""

        ws = Path(self.workspace_dir)
        if not ws.is_dir():
            return ""

        sections: list[str] = []
        for filename in self.KNOWN_FILES:
            filepath = ws / filename
            if filepath.is_file():
                try:
                    content = filepath.read_text(encoding="utf-8")
                    if len(content) > _MAX_CHARS_PER_FILE:
                        content = content[:_MAX_CHARS_PER_FILE]
                    content = content.strip()
                    if content:
                        sections.append(
                            f"## Project Context (from {filename})\n{content}"
                        )
                except Exception:
                    logger.debug(
                        "Failed to read workspace context file %s",
                        filepath,
                        exc_info=True,
                    )

        return "\n\n".join(sections)

    def get_loaded_files(self) -> list[str]:
        """Return list of known instruction files that exist in the workspace.

        Returns:
            List of relative file paths that were found.
        """
        if not self.enabled:
            return []

        ws = Path(self.workspace_dir)
        if not ws.is_dir():
            return []

        found: list[str] = []
        for filename in self.KNOWN_FILES:
            filepath = ws / filename
            if filepath.is_file():
                found.append(filename)
        return found
