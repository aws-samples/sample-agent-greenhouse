"""Tests for Soul System — workspace file loading and prompt injection."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


from platform_agent.foundation.soul import SoulSystem


# ---------------------------------------------------------------------------
# Loading individual soul files
# ---------------------------------------------------------------------------


class TestSoulFileLoading:
    """Test loading of individual workspace personality files."""

    def test_load_soul_md(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("I am creative and curious.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.soul == "I am creative and curious."

    def test_load_agents_md(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("Follow TDD strictly.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.agents == "Follow TDD strictly."

    def test_load_user_md(self, tmp_path):
        (tmp_path / "USER.md").write_text("User is an ML engineer.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.user == "User is an ML engineer."

    def test_load_memory_md(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("Last session: discussed deployment.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.memory == "Last session: discussed deployment."

    def test_load_identity_md(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("Name: Nova\nEmoji: 🌟")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert "Nova" in soul.identity

    def test_missing_soul_file_returns_empty(self, tmp_path):
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.soul == ""

    def test_missing_agents_file_returns_empty(self, tmp_path):
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.agents == ""

    def test_missing_user_file_returns_empty(self, tmp_path):
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.user == ""

    def test_missing_memory_file_returns_empty(self, tmp_path):
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.memory == ""

    def test_missing_identity_file_returns_empty(self, tmp_path):
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.identity == ""

    def test_all_files_optional(self, tmp_path):
        """Empty workspace should not raise."""
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.soul == ""
        assert soul.agents == ""
        assert soul.user == ""
        assert soul.memory == ""
        assert soul.identity == ""


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------


class TestSoulPromptAssembly:
    """Test system prompt assembly from soul files."""

    def test_assemble_with_all_files(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("Name: Nova")
        (tmp_path / "SOUL.md").write_text("Kind and helpful.")
        (tmp_path / "AGENTS.md").write_text("Always test first.")
        (tmp_path / "USER.md").write_text("User likes Python.")
        (tmp_path / "MEMORY.md").write_text("Previously discussed AWS.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        prompt = soul.assemble_prompt()

        assert "Nova" in prompt
        assert "Kind and helpful" in prompt
        assert "Always test first" in prompt
        assert "User likes Python" in prompt
        assert "Previously discussed AWS" in prompt

    def test_assemble_with_partial_files(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("Creative soul.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        prompt = soul.assemble_prompt()
        assert "Creative soul" in prompt
        # Should not contain empty sections
        assert "User Context" not in prompt or "User likes" not in prompt

    def test_assemble_empty_workspace(self, tmp_path):
        soul = SoulSystem(workspace_dir=str(tmp_path))
        prompt = soul.assemble_prompt()
        # Should still return a valid base prompt
        assert isinstance(prompt, str)

    def test_assemble_no_workspace(self):
        soul = SoulSystem(workspace_dir=None)
        prompt = soul.assemble_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) == 0 or "You are" in prompt

    def test_memory_excluded_in_public_mode(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("Secret memory content.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        prompt = soul.assemble_prompt(include_memory=False)
        assert "Secret memory content" not in prompt

    def test_memory_included_in_private_mode(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("Secret memory content.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        prompt = soul.assemble_prompt(include_memory=True)
        assert "Secret memory content" in prompt


# ---------------------------------------------------------------------------
# Workspace memory files (memory/*.md)
# ---------------------------------------------------------------------------


class TestWorkspaceMemoryFiles:
    """Test loading memory files from workspace memory/ directory."""

    def test_load_memory_dir_files(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "project_context.md").write_text("Project uses React.")
        (mem_dir / "decisions.md").write_text("Chose PostgreSQL for DB.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        memory_files = soul.load_memory_files()
        assert len(memory_files) == 2
        contents = " ".join(memory_files.values())
        assert "React" in contents
        assert "PostgreSQL" in contents

    def test_empty_memory_dir(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        soul = SoulSystem(workspace_dir=str(tmp_path))
        memory_files = soul.load_memory_files()
        assert memory_files == {}

    def test_no_memory_dir(self, tmp_path):
        soul = SoulSystem(workspace_dir=str(tmp_path))
        memory_files = soul.load_memory_files()
        assert memory_files == {}

    def test_memory_files_only_md(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "notes.md").write_text("Some notes.")
        (mem_dir / "data.json").write_text('{"key": "value"}')
        soul = SoulSystem(workspace_dir=str(tmp_path))
        memory_files = soul.load_memory_files()
        assert len(memory_files) == 1
        assert "notes.md" in memory_files


# ---------------------------------------------------------------------------
# File reload / refresh
# ---------------------------------------------------------------------------


class TestSoulReload:
    """Test refreshing soul files after changes."""

    def test_reload_picks_up_changes(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("Version 1.")
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.soul == "Version 1."

        # Modify file
        (tmp_path / "SOUL.md").write_text("Version 2.")
        soul.reload()
        assert soul.soul == "Version 2."

    def test_reload_picks_up_new_files(self, tmp_path):
        soul = SoulSystem(workspace_dir=str(tmp_path))
        assert soul.identity == ""

        (tmp_path / "IDENTITY.md").write_text("Name: Updated")
        soul.reload()
        assert soul.identity == "Name: Updated"
