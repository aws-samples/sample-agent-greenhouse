"""Tests for WorkspaceContextLoader — workspace context auto-injection."""

from __future__ import annotations

import os

import pytest

from platform_agent.foundation.workspace_context import (
    WorkspaceContextLoader,
    _MAX_CHARS_PER_FILE,
)


class TestLoadsAgentsMd:
    """Test loading AGENTS.md when present."""

    def test_loads_agents_md(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# My Agent Rules\nDo X.")
        loader = WorkspaceContextLoader(str(tmp_path))
        context = loader.load_context()
        assert "## Project Context (from AGENTS.md)" in context
        assert "# My Agent Rules" in context
        assert "Do X." in context

    def test_get_loaded_files_includes_agents(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("rules")
        loader = WorkspaceContextLoader(str(tmp_path))
        assert "AGENTS.md" in loader.get_loaded_files()


class TestLoadsMultipleFiles:
    """Test loading multiple instruction files."""

    def test_loads_multiple_known_files(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("agents content")
        (tmp_path / "CLAUDE.md").write_text("claude content")
        (tmp_path / ".cursorrules").write_text("cursor content")
        loader = WorkspaceContextLoader(str(tmp_path))
        context = loader.load_context()
        assert "## Project Context (from AGENTS.md)" in context
        assert "## Project Context (from CLAUDE.md)" in context
        assert "## Project Context (from .cursorrules)" in context
        assert "agents content" in context
        assert "claude content" in context
        assert "cursor content" in context

    def test_loads_github_copilot_instructions(self, tmp_path):
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        (gh_dir / "copilot-instructions.md").write_text("copilot rules")
        loader = WorkspaceContextLoader(str(tmp_path))
        context = loader.load_context()
        assert "## Project Context (from .github/copilot-instructions.md)" in context
        assert "copilot rules" in context

    def test_get_loaded_files_lists_all_found(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("a")
        (tmp_path / "CLAUDE.md").write_text("b")
        loader = WorkspaceContextLoader(str(tmp_path))
        files = loader.get_loaded_files()
        assert "AGENTS.md" in files
        assert "CLAUDE.md" in files
        assert len(files) == 2


class TestMaxCharLimit:
    """Test that files are truncated to max char limit."""

    def test_truncates_large_file(self, tmp_path):
        large_content = "x" * (_MAX_CHARS_PER_FILE + 1000)
        (tmp_path / "CLAUDE.md").write_text(large_content)
        loader = WorkspaceContextLoader(str(tmp_path))
        context = loader.load_context()
        # Content in the output should be at most _MAX_CHARS_PER_FILE chars
        # (plus the header line)
        header = "## Project Context (from CLAUDE.md)\n"
        body = context.replace(header, "")
        assert len(body) <= _MAX_CHARS_PER_FILE

    def test_does_not_truncate_small_file(self, tmp_path):
        content = "short content"
        (tmp_path / "AGENTS.md").write_text(content)
        loader = WorkspaceContextLoader(str(tmp_path))
        context = loader.load_context()
        assert content in context


class TestNoFilesFound:
    """Test returns empty when no known files exist."""

    def test_empty_workspace(self, tmp_path):
        loader = WorkspaceContextLoader(str(tmp_path))
        assert loader.load_context() == ""
        assert loader.get_loaded_files() == []

    def test_unknown_files_ignored(self, tmp_path):
        (tmp_path / "README.md").write_text("readme")
        (tmp_path / "setup.py").write_text("setup")
        loader = WorkspaceContextLoader(str(tmp_path))
        assert loader.load_context() == ""

    def test_nonexistent_directory(self):
        loader = WorkspaceContextLoader("/nonexistent/path/xyz")
        assert loader.load_context() == ""
        assert loader.get_loaded_files() == []


class TestDisabled:
    """Test that disabled loader returns empty."""

    def test_disabled_returns_empty_context(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("should not load")
        loader = WorkspaceContextLoader(str(tmp_path), enabled=False)
        assert loader.load_context() == ""

    def test_disabled_returns_empty_file_list(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("should not load")
        loader = WorkspaceContextLoader(str(tmp_path), enabled=False)
        assert loader.get_loaded_files() == []
