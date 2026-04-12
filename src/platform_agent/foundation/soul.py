"""Soul System — workspace bootstrap that loads personality files into system prompt.

The soul system reads optional workspace files and assembles them into a coherent
system prompt for the agent:

- IDENTITY.md — Agent name, emoji, vibe
- SOUL.md — Agent personality, values, tone
- AGENTS.md — Operating instructions, rules
- USER.md — User profile
- MEMORY.md — Long-term curated memory (only in private sessions)

Each file is optional. The system prompt is assembled from:
  base foundation prompt + loaded workspace files + loaded skills.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# The workspace personality files in order of prompt assembly.
_SOUL_FILES = {
    "identity": "IDENTITY.md",
    "soul": "SOUL.md",
    "agents": "AGENTS.md",
    "user": "USER.md",
    "memory": "MEMORY.md",
}


class SoulSystem:
    """Loads and manages workspace personality files for system prompt assembly.

    Args:
        workspace_dir: Path to the workspace directory. If None, all fields
            are empty and assemble_prompt returns an empty string.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self.workspace_dir = workspace_dir
        self.identity: str = ""
        self.soul: str = ""
        self.agents: str = ""
        self.user: str = ""
        self.memory: str = ""

        if workspace_dir:
            self._load_all()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        """Load all soul files from the workspace directory."""
        if not self.workspace_dir:
            return
        ws = Path(self.workspace_dir)
        for attr, filename in _SOUL_FILES.items():
            filepath = ws / filename
            if filepath.is_file():
                try:
                    setattr(self, attr, filepath.read_text(encoding="utf-8").strip())
                except Exception:
                    logger.debug("Failed to read %s", filepath, exc_info=True)
                    setattr(self, attr, "")
            else:
                setattr(self, attr, "")

    def reload(self) -> None:
        """Re-read all soul files from disk (picks up changes)."""
        self._load_all()

    # ------------------------------------------------------------------
    # Memory files (memory/*.md)
    # ------------------------------------------------------------------

    def load_memory_files(self) -> dict[str, str]:
        """Load all .md files from workspace memory/ directory.

        Returns:
            Dict mapping filename -> content for each .md file found.
        """
        if not self.workspace_dir:
            return {}
        mem_dir = Path(self.workspace_dir) / "memory"
        if not mem_dir.is_dir():
            return {}

        result: dict[str, str] = {}
        for f in sorted(mem_dir.iterdir()):
            if f.is_file() and f.suffix == ".md":
                try:
                    result[f.name] = f.read_text(encoding="utf-8").strip()
                except Exception:
                    logger.debug("Failed to read memory file %s", f, exc_info=True)
        return result

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    def assemble_prompt(self, include_memory: bool = True) -> str:
        """Assemble the system prompt from loaded soul files.

        Args:
            include_memory: If False, exclude MEMORY.md content (for public
                sessions where memory should not leak).

        Returns:
            Assembled prompt string. Empty string if no workspace is configured.
        """
        if not self.workspace_dir:
            return ""

        sections: list[str] = []

        if self.identity:
            sections.append(f"## Identity\n{self.identity}")

        if self.soul:
            sections.append(f"## Personality\n{self.soul}")

        if self.agents:
            sections.append(f"## Operating Rules\n{self.agents}")

        if self.user:
            sections.append(f"## User Context\n{self.user}")

        if include_memory and self.memory:
            sections.append(f"## Memory\n{self.memory}")

        return "\n\n".join(sections)
