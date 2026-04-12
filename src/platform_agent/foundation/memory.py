"""Memory architecture for the Strands Foundation Agent.

Two layers:
1. SessionMemory — In-memory conversation history for the current session.
2. WorkspaceMemory — File-based memory (MEMORY.md + memory/*.md) that the agent
   can read and write to persist context across sessions.

Optional AgentCore Memory integration is handled separately via hooks.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Rough token estimate: ~4 chars per token for English text.
_CHARS_PER_TOKEN = 4


class SessionMemory:
    """In-memory conversation history for the current agent session.

    Stores messages as dicts with role and content fields.
    Used for context window management and compaction decisions.
    """

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def add_message(self, role: str, content: str) -> None:
        """Add a message to session history."""
        self.messages.append({"role": role, "content": content})

    def get_history(self, limit: int | None = None) -> list[dict[str, str]]:
        """Get conversation history, optionally limited to most recent N messages."""
        if limit is None:
            return list(self.messages)
        return list(self.messages[-limit:])

    def clear(self) -> None:
        """Clear all session history."""
        self.messages.clear()

    def estimate_tokens(self) -> int:
        """Rough estimate of total tokens in session history."""
        total_chars = sum(len(m["content"]) for m in self.messages)
        return total_chars // _CHARS_PER_TOKEN


class WorkspaceMemory:
    """File-based workspace memory that persists across sessions.

    Reads and writes MEMORY.md and memory/*.md files in the workspace directory.
    The agent can use these files to maintain long-term context.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self.workspace_dir = workspace_dir

    @property
    def _ws(self) -> Path | None:
        if self.workspace_dir:
            return Path(self.workspace_dir)
        return None

    @property
    def _memory_dir(self) -> Path | None:
        if self._ws:
            return self._ws / "memory"
        return None

    # ------------------------------------------------------------------
    # Main MEMORY.md
    # ------------------------------------------------------------------

    def read_memory(self) -> str:
        """Read the main MEMORY.md file."""
        if not self._ws:
            return ""
        path = self._ws / "MEMORY.md"
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            logger.debug("Failed to read MEMORY.md", exc_info=True)
            return ""

    def write_memory(self, content: str) -> None:
        """Write/overwrite the main MEMORY.md file."""
        if not self._ws:
            return
        path = self._ws / "MEMORY.md"
        path.write_text(content, encoding="utf-8")

    def append_memory(self, content: str) -> None:
        """Append to the main MEMORY.md file."""
        if not self._ws:
            return
        path = self._ws / "MEMORY.md"
        existing = ""
        if path.is_file():
            existing = path.read_text(encoding="utf-8")
        path.write_text(existing + content + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Memory sub-files (memory/*.md)
    # ------------------------------------------------------------------

    def read_memory_file(self, filename: str) -> str:
        """Read a specific file from memory/ directory."""
        if not self._memory_dir:
            return ""
        path = self._memory_dir / filename
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            logger.debug("Failed to read memory file %s", filename, exc_info=True)
            return ""

    def write_memory_file(self, filename: str, content: str) -> None:
        """Write a file to the memory/ directory."""
        if not self._memory_dir:
            return
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        path = self._memory_dir / filename
        path.write_text(content, encoding="utf-8")

    def list_memory_files(self) -> list[str]:
        """List all .md files in the memory/ directory."""
        if not self._memory_dir or not self._memory_dir.is_dir():
            return []
        return sorted(f.name for f in self._memory_dir.iterdir()
                       if f.is_file() and f.suffix == ".md")
