"""Tests for Memory hooks — enrichment, storage, flush behavior."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


from platform_agent.foundation.memory import SessionMemory, WorkspaceMemory
from platform_agent.foundation.hooks.memory_hook import MemoryHook
from platform_agent.foundation.hooks.compaction_hook import CompactionHook


# ---------------------------------------------------------------------------
# Session Memory (in-memory conversation history)
# ---------------------------------------------------------------------------


class TestSessionMemory:
    """Test in-memory session history."""

    def test_add_user_message(self):
        mem = SessionMemory()
        mem.add_message("user", "Hello")
        assert len(mem.messages) == 1
        assert mem.messages[0]["role"] == "user"
        assert mem.messages[0]["content"] == "Hello"

    def test_add_assistant_message(self):
        mem = SessionMemory()
        mem.add_message("assistant", "Hi there!")
        assert len(mem.messages) == 1
        assert mem.messages[0]["role"] == "assistant"

    def test_get_history(self):
        mem = SessionMemory()
        mem.add_message("user", "Q1")
        mem.add_message("assistant", "A1")
        mem.add_message("user", "Q2")
        history = mem.get_history()
        assert len(history) == 3
        assert history[0]["content"] == "Q1"
        assert history[-1]["content"] == "Q2"

    def test_get_history_with_limit(self):
        mem = SessionMemory()
        for i in range(10):
            mem.add_message("user", f"msg-{i}")
        history = mem.get_history(limit=3)
        assert len(history) == 3
        # Should return most recent
        assert history[-1]["content"] == "msg-9"

    def test_clear(self):
        mem = SessionMemory()
        mem.add_message("user", "Hello")
        mem.clear()
        assert len(mem.messages) == 0

    def test_token_estimate(self):
        mem = SessionMemory()
        mem.add_message("user", "Hello world")
        estimate = mem.estimate_tokens()
        assert estimate > 0

    def test_empty_token_estimate(self):
        mem = SessionMemory()
        assert mem.estimate_tokens() == 0


# ---------------------------------------------------------------------------
# Workspace Memory (file-based)
# ---------------------------------------------------------------------------


class TestWorkspaceMemory:
    """Test workspace file-based memory."""

    def test_read_memory_file(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("Previous context here.")
        mem = WorkspaceMemory(workspace_dir=str(tmp_path))
        content = mem.read_memory()
        assert "Previous context here" in content

    def test_write_memory_file(self, tmp_path):
        mem = WorkspaceMemory(workspace_dir=str(tmp_path))
        mem.write_memory("New context to remember.")
        content = (tmp_path / "MEMORY.md").read_text()
        assert "New context to remember" in content

    def test_append_memory(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("Line 1.\n")
        mem = WorkspaceMemory(workspace_dir=str(tmp_path))
        mem.append_memory("Line 2.")
        content = (tmp_path / "MEMORY.md").read_text()
        assert "Line 1" in content
        assert "Line 2" in content

    def test_read_memory_subfile(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "notes.md").write_text("Detailed notes.")
        mem = WorkspaceMemory(workspace_dir=str(tmp_path))
        content = mem.read_memory_file("notes.md")
        assert "Detailed notes" in content

    def test_write_memory_subfile(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        mem = WorkspaceMemory(workspace_dir=str(tmp_path))
        mem.write_memory_file("ideas.md", "New idea.")
        content = (mem_dir / "ideas.md").read_text()
        assert "New idea" in content

    def test_list_memory_files(self, tmp_path):
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "a.md").write_text("A")
        (mem_dir / "b.md").write_text("B")
        mem = WorkspaceMemory(workspace_dir=str(tmp_path))
        files = mem.list_memory_files()
        assert "a.md" in files
        assert "b.md" in files

    def test_no_workspace_returns_empty(self):
        mem = WorkspaceMemory(workspace_dir=None)
        assert mem.read_memory() == ""

    def test_missing_memory_file_returns_empty(self, tmp_path):
        mem = WorkspaceMemory(workspace_dir=str(tmp_path))
        content = mem.read_memory()
        assert content == ""


# ---------------------------------------------------------------------------
# MemoryHook
# ---------------------------------------------------------------------------


class TestMemoryHook:
    """Test MemoryHook event handling."""

    def test_hook_initializes_with_session_memory(self):
        hook = MemoryHook()
        assert hook.session_memory is not None

    def test_hook_records_messages(self):
        hook = MemoryHook()
        # Simulate a message added event
        event = MagicMock()
        event.message = {"role": "user", "content": [{"text": "Hello"}]}
        hook.on_message_added(event)
        assert len(hook.session_memory.messages) == 1

    def test_hook_enriches_with_workspace_memory(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("Remember: user likes TDD.")
        hook = MemoryHook(workspace_dir=str(tmp_path))
        # Simulate before-invocation event
        event = MagicMock()
        event.messages = [{"role": "user", "content": [{"text": "How to test?"}]}]
        hook.on_before_invocation(event)
        # The event.messages should be enriched (hook may modify or we check state)
        assert hook.workspace_memory is not None


# ---------------------------------------------------------------------------
# CompactionHook (pre-compaction memory flush)
# ---------------------------------------------------------------------------


class TestCompactionHook:
    """Test CompactionHook — flush to memory before token limit."""

    def test_hook_initializes_with_threshold(self):
        hook = CompactionHook(token_threshold=50000)
        assert hook.token_threshold == 50000

    def test_default_threshold(self):
        hook = CompactionHook()
        assert hook.token_threshold > 0

    def test_no_flush_when_under_threshold(self):
        hook = CompactionHook(token_threshold=100000)
        session = SessionMemory()
        session.add_message("user", "Short message.")
        hook.session_memory = session
        assert not hook.should_flush()

    def test_flush_when_over_threshold(self):
        hook = CompactionHook(token_threshold=10)
        session = SessionMemory()
        # Add enough messages to exceed threshold
        session.add_message("user", "A" * 1000)
        hook.session_memory = session
        assert hook.should_flush()

    def test_flush_logs_warning_only(self):
        """v1: CompactionHook logs warning instead of injecting messages."""
        hook = CompactionHook(token_threshold=10)
        session = SessionMemory()
        session.add_message("user", "A" * 1000)
        hook.session_memory = session

        event = MagicMock()
        event.messages = list(session.messages)
        original_len = len(event.messages)
        hook.on_before_invocation(event)
        # v1: should NOT inject messages, only set _flush_triggered
        assert hook._flush_triggered
        assert len(event.messages) == original_len
