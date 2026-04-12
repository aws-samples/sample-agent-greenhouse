"""Tests for Claude Code CLI tool wrapping."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, AsyncMock
import subprocess

import pytest


from platform_agent.foundation.tools.claude_code import (
    claude_code,
    _build_cc_command,
    _parse_cc_output,
)


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------


class TestBuildCommand:
    """Test CC CLI command construction."""

    def test_basic_command(self):
        cmd = _build_cc_command("Write a hello world script")
        assert "claude" in cmd
        assert "--print" in cmd

    def test_includes_permission_bypass(self):
        cmd = _build_cc_command("Do something")
        assert "--permission-mode" in cmd
        assert "bypassPermissions" in cmd

    def test_custom_workdir(self):
        cmd = _build_cc_command("task", workdir="/tmp/myproject")
        # workdir should be handled via cwd, not in command args typically
        # but if passed as arg, check it's there
        assert isinstance(cmd, list)

    def test_task_in_command(self):
        cmd = _build_cc_command("Fix the bug in main.py")
        # The task prompt should be in the command
        assert any("Fix the bug" in str(arg) for arg in cmd)


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


class TestParseOutput:
    """Test parsing CC CLI output."""

    def test_parse_stdout(self):
        result = _parse_cc_output(stdout="Hello world", stderr="", returncode=0)
        assert "Hello world" in result

    def test_parse_with_stderr(self):
        result = _parse_cc_output(stdout="", stderr="Warning: something", returncode=0)
        # Should include stderr info when stdout is empty
        assert "Warning" in result or result == ""

    def test_parse_error_returncode(self):
        result = _parse_cc_output(stdout="", stderr="Error occurred", returncode=1)
        assert "Error" in result or "error" in result.lower() or "failed" in result.lower()

    def test_parse_empty_output(self):
        result = _parse_cc_output(stdout="", stderr="", returncode=0)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tool function (subprocess execution)
# ---------------------------------------------------------------------------


class TestClaudeCodeTool:
    """Test the claude_code tool function."""

    @patch("subprocess.run")
    def test_successful_execution(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout="Task completed successfully.",
            stderr="",
        )
        result = claude_code(task="Write hello world")
        assert "Task completed" in result
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_custom_workdir(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout="Done.",
            stderr="",
        )
        claude_code(task="Build project", workdir="/tmp/project")
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("cwd") == "/tmp/project" or \
            call_kwargs[1].get("cwd") == "/tmp/project"

    @patch("subprocess.run")
    def test_timeout_handling(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=300)
        result = claude_code(task="Long task", timeout=300)
        assert "timeout" in result.lower() or "timed out" in result.lower()

    @patch("subprocess.run")
    def test_custom_timeout(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout="Done.",
            stderr="",
        )
        claude_code(task="Quick task", timeout=60)
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("timeout") == 60 or \
            call_kwargs[1].get("timeout") == 60

    @patch("subprocess.run")
    def test_process_error(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"],
            returncode=1,
            stdout="",
            stderr="Fatal error: something went wrong",
        )
        result = claude_code(task="Bad task")
        # Should return error info, not raise
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("subprocess.run")
    def test_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("claude not found")
        result = claude_code(task="Something")
        assert "not found" in result.lower() or "not installed" in result.lower()

    @patch("subprocess.run")
    def test_default_timeout_is_300(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout="Done.",
            stderr="",
        )
        claude_code(task="Task")
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("timeout") == 300 or \
            call_kwargs[1].get("timeout") == 300

    @patch("subprocess.run")
    def test_returns_combined_output_on_error(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["claude"],
            returncode=2,
            stdout="partial output",
            stderr="error details",
        )
        result = claude_code(task="Failing task")
        # Should contain both stdout and stderr info
        assert "partial output" in result or "error details" in result
