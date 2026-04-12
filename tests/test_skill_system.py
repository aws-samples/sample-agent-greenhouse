"""Tests for Skill System — discovery, lazy loading, prompt injection."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


from platform_agent.foundation.skills.registry import SkillRegistry, SkillMetadata


# ---------------------------------------------------------------------------
# Skill Discovery
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    """Test skill discovery from workspace skills/ directory."""

    def test_discover_skills_in_directory(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skill1_dir = skills_dir / "code_review"
        skill1_dir.mkdir(parents=True)
        (skill1_dir / "SKILL.md").write_text(
            "---\nname: code_review\ndescription: Reviews code quality\n---\n"
            "Full instructions for code review."
        )
        skill2_dir = skills_dir / "deployment"
        skill2_dir.mkdir(parents=True)
        (skill2_dir / "SKILL.md").write_text(
            "---\nname: deployment\ndescription: Handles deployments\n---\n"
            "Full deployment instructions."
        )
        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        skills = registry.list_skills()
        assert len(skills) == 2
        names = [s.name for s in skills]
        assert "code_review" in names
        assert "deployment" in names

    def test_discover_empty_directory(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        assert registry.list_skills() == []

    def test_discover_no_skills_directory(self, tmp_path):
        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        assert registry.list_skills() == []

    def test_discover_skips_dirs_without_skill_md(self, tmp_path):
        skills_dir = tmp_path / "skills"
        valid = skills_dir / "valid_skill"
        valid.mkdir(parents=True)
        (valid / "SKILL.md").write_text(
            "---\nname: valid_skill\ndescription: Valid\n---\nInstructions."
        )
        invalid = skills_dir / "no_skill_file"
        invalid.mkdir(parents=True)
        (invalid / "README.md").write_text("Not a skill.")

        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        skills = registry.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "valid_skill"

    def test_discover_no_workspace(self):
        registry = SkillRegistry(workspace_dir=None)
        registry.discover()
        assert registry.list_skills() == []


# ---------------------------------------------------------------------------
# Skill Metadata Parsing
# ---------------------------------------------------------------------------


class TestSkillMetadata:
    """Test parsing SKILL.md frontmatter for metadata."""

    def test_parse_basic_metadata(self):
        content = "---\nname: my_skill\ndescription: Does things\n---\nFull content."
        meta = SkillMetadata.from_skill_md(content)
        assert meta.name == "my_skill"
        assert meta.description == "Does things"

    def test_parse_without_frontmatter(self):
        content = "Just instructions, no frontmatter."
        meta = SkillMetadata.from_skill_md(content)
        assert meta.name == ""
        assert meta.description == ""
        assert meta.full_content == "Just instructions, no frontmatter."

    def test_parse_with_extra_fields(self):
        content = "---\nname: skill\ndescription: Desc\nversion: 1.0\n---\nBody."
        meta = SkillMetadata.from_skill_md(content)
        assert meta.name == "skill"
        assert meta.description == "Desc"

    def test_full_content_excludes_frontmatter(self):
        content = "---\nname: skill\ndescription: Desc\n---\nThe actual instructions."
        meta = SkillMetadata.from_skill_md(content)
        assert "The actual instructions" in meta.full_content
        assert "---" not in meta.full_content.strip()


# ---------------------------------------------------------------------------
# Lazy Loading
# ---------------------------------------------------------------------------


class TestSkillLazyLoading:
    """Test that full skill content is loaded on demand."""

    def test_list_shows_name_and_description_only(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: Short desc\n---\n"
            "Very long detailed instructions that should not be loaded initially."
        )
        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        skills = registry.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "my_skill"
        assert skills[0].description == "Short desc"
        # Full content should NOT be loaded yet
        assert skills[0].full_content is None or skills[0]._loaded is False

    def test_get_skill_loads_full_content(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: Short desc\n---\n"
            "Full instructions here."
        )
        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        skill = registry.get_skill("my_skill")
        assert skill is not None
        assert "Full instructions here" in skill.full_content

    def test_get_nonexistent_skill_returns_none(self, tmp_path):
        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        assert registry.get_skill("nonexistent") is None


# ---------------------------------------------------------------------------
# Prompt Injection
# ---------------------------------------------------------------------------


class TestSkillPromptInjection:
    """Test that skills are listed in system prompt."""

    def test_skill_summary_for_prompt(self, tmp_path):
        skills_dir = tmp_path / "skills" / "reviewer"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: reviewer\ndescription: Reviews code for quality\n---\n"
            "Detailed review instructions."
        )
        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        summary = registry.get_prompt_summary()
        assert "reviewer" in summary
        assert "Reviews code for quality" in summary
        # Should NOT include full instructions
        assert "Detailed review instructions" not in summary

    def test_empty_skills_summary(self, tmp_path):
        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        summary = registry.get_prompt_summary()
        assert isinstance(summary, str)

    def test_multiple_skills_in_summary(self, tmp_path):
        for name, desc in [("skill_a", "Does A"), ("skill_b", "Does B")]:
            skill_dir = tmp_path / "skills" / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {desc}\n---\nInstructions for {name}."
            )
        registry = SkillRegistry(workspace_dir=str(tmp_path))
        registry.discover()
        summary = registry.get_prompt_summary()
        assert "skill_a" in summary
        assert "skill_b" in summary
        assert "Does A" in summary
        assert "Does B" in summary
