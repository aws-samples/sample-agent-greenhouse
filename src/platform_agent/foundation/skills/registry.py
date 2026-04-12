"""Skill System — discovery, lazy loading, and prompt injection.

Skills are loaded from the workspace skills/ directory. Each skill has a
SKILL.md file with YAML frontmatter (name, description) and full instructions.

Skills are listed in the system prompt by name + description only.
Full content is loaded on demand when the agent needs it.
"""

from __future__ import annotations

import logging
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillMetadata:
    """Metadata and content for a workspace skill.

    Parsed from SKILL.md frontmatter and body.
    """

    name: str = ""
    description: str = ""
    full_content: str = ""
    skill_dir: str = ""
    _loaded: bool = False

    @classmethod
    def from_skill_md(cls, content: str, skill_dir: str = "") -> SkillMetadata:
        """Parse a SKILL.md file into metadata.

        Expects optional YAML frontmatter delimited by --- lines,
        followed by the full body content.
        """
        name = ""
        description = ""
        body = content

        # Parse frontmatter
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
        if match:
            frontmatter = match.group(1)
            body = match.group(2).strip()

            for line in frontmatter.split("\n"):
                line = line.strip()
                if line.startswith("name:"):
                    name = line[len("name:"):].strip()
                elif line.startswith("description:"):
                    description = line[len("description:"):].strip()

        return cls(
            name=name,
            description=description,
            full_content=body,
            skill_dir=skill_dir,
            _loaded=True,
        )

    @classmethod
    def from_discovery(cls, name: str, description: str, skill_dir: str) -> SkillMetadata:
        """Create metadata from discovery (lazy — full content not loaded)."""
        return cls(
            name=name,
            description=description,
            full_content=None,  # type: ignore[arg-type]
            skill_dir=skill_dir,
            _loaded=False,
        )


class SkillRegistry:
    """Registry for workspace skills with lazy loading.

    Discovers skills from the workspace skills/ directory. Each skill
    directory must contain a SKILL.md file.

    Args:
        workspace_dir: Path to the workspace root directory.
    """

    def __init__(self, workspace_dir: str | None = None) -> None:
        self.workspace_dir = workspace_dir
        self._skills: dict[str, SkillMetadata] = {}

    def discover(self) -> None:
        """Scan the workspace skills/ directory for available skills.

        Only reads frontmatter (name + description) — full content is lazy loaded.
        """
        warnings.warn(
            "SkillRegistry.discover() is deprecated, use strands.AgentSkills plugin instead",
            DeprecationWarning,
            stacklevel=2,
        )
        self._skills.clear()

        if not self.workspace_dir:
            return

        skills_dir = Path(self.workspace_dir) / "skills"
        if not skills_dir.is_dir():
            return

        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue

            try:
                content = skill_md.read_text(encoding="utf-8")
                # Parse just the frontmatter for discovery
                name, description = self._parse_frontmatter(content)
                if not name:
                    name = entry.name
                self._skills[name] = SkillMetadata.from_discovery(
                    name=name,
                    description=description,
                    skill_dir=str(entry),
                )
            except Exception:
                logger.debug("Failed to discover skill in %s", entry, exc_info=True)

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[str, str]:
        """Extract name and description from YAML frontmatter."""
        name = ""
        description = ""
        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if match:
            for line in match.group(1).split("\n"):
                line = line.strip()
                if line.startswith("name:"):
                    name = line[len("name:"):].strip()
                elif line.startswith("description:"):
                    description = line[len("description:"):].strip()
        return name, description

    def list_skills(self) -> list[SkillMetadata]:
        """List all discovered skills (metadata only, not full content)."""
        return list(self._skills.values())

    def get_skill(self, name: str) -> SkillMetadata | None:
        """Get a skill by name, loading its full content if needed.

        Returns:
            SkillMetadata with full_content populated, or None if not found.
        """
        meta = self._skills.get(name)
        if meta is None:
            return None

        if not meta._loaded:
            # Lazy load full content
            skill_md = Path(meta.skill_dir) / "SKILL.md"
            try:
                content = skill_md.read_text(encoding="utf-8")
                full = SkillMetadata.from_skill_md(content, skill_dir=meta.skill_dir)
                meta.full_content = full.full_content
                meta._loaded = True
            except Exception:
                logger.debug("Failed to load skill %s", name, exc_info=True)
                return None

        return meta

    def get_prompt_summary(self) -> str:
        """Generate a skills summary for system prompt injection.

        Lists each skill with name and description only.
        Full instructions are NOT included (lazy loaded on demand).
        """
        warnings.warn(
            "SkillRegistry.get_prompt_summary() is deprecated, use strands.AgentSkills plugin instead",
            DeprecationWarning,
            stacklevel=2,
        )
        skills = self.list_skills()
        if not skills:
            return ""

        lines = ["## Available Skills", ""]
        for skill in skills:
            lines.append(f"- **{skill.name}**: {skill.description}")
        lines.append("")
        lines.append(
            "To use a skill, read its full instructions from the workspace "
            "skills/<name>/SKILL.md file."
        )
        return "\n".join(lines)
