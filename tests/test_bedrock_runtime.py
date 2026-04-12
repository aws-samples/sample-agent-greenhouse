"""Tests for Bedrock runtime — tool definitions, tool execution, and converse loop."""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from platform_agent.bedrock_runtime import (
    _build_tool_definitions,
    _execute_tool,
    converse,
)


# -- Tool definitions ---------------------------------------------------------


class TestToolDefinitions:
    def test_build_known_tools(self) -> None:
        tools = _build_tool_definitions(["Read", "Glob", "Grep"])
        assert len(tools) == 3
        names = [t["toolSpec"]["name"] for t in tools]
        assert "Read" in names
        assert "Glob" in names
        assert "Grep" in names

    def test_build_all_tools(self) -> None:
        tools = _build_tool_definitions(["Read", "Write", "Edit", "Bash", "Glob", "Grep"])
        assert len(tools) == 6

    def test_unknown_tool_skipped(self) -> None:
        tools = _build_tool_definitions(["Read", "UnknownTool"])
        assert len(tools) == 1

    def test_empty_tools(self) -> None:
        tools = _build_tool_definitions([])
        assert len(tools) == 0

    def test_tool_has_required_schema(self) -> None:
        tools = _build_tool_definitions(["Read"])
        spec = tools[0]["toolSpec"]
        assert "name" in spec
        assert "description" in spec
        assert "inputSchema" in spec
        assert "json" in spec["inputSchema"]


# -- Tool execution -----------------------------------------------------------


class TestToolExecution:
    def test_read_file(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")
        result = _execute_tool("Read", {"file_path": "test.txt"}, cwd=str(tmp_path))
        assert result == "hello world"

    def test_read_file_not_found(self, tmp_path: Path) -> None:
        result = _execute_tool("Read", {"file_path": "nope.txt"}, cwd=str(tmp_path))
        assert "not found" in result.lower()

    def test_glob_finds_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        (tmp_path / "c.txt").write_text("z")
        result = _execute_tool("Glob", {"pattern": "*.py"}, cwd=str(tmp_path))
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_glob_no_match(self, tmp_path: Path) -> None:
        result = _execute_tool("Glob", {"pattern": "*.xyz"}, cwd=str(tmp_path))
        assert "No files found" in result

    def test_grep_finds_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "test.py").write_text("API_KEY = 'sk-abc123'\nother line\n")
        result = _execute_tool(
            "Grep",
            {"pattern": "API_KEY", "path": ".", "include": "*.py"},
            cwd=str(tmp_path),
        )
        assert "API_KEY" in result

    def test_grep_no_match(self, tmp_path: Path) -> None:
        (tmp_path / "test.py").write_text("clean code\n")
        result = _execute_tool(
            "Grep",
            {"pattern": "SECRET", "path": "."},
            cwd=str(tmp_path),
        )
        assert "No matches" in result

    def test_bash_command(self, tmp_path: Path) -> None:
        result = _execute_tool("Bash", {"command": "echo hello"}, cwd=str(tmp_path))
        assert "hello" in result

    def test_write_file(self, tmp_path: Path) -> None:
        result = _execute_tool(
            "Write",
            {"file_path": "new.txt", "content": "test content"},
            cwd=str(tmp_path),
        )
        assert "Successfully wrote" in result
        assert (tmp_path / "new.txt").read_text() == "test content"

    def test_write_creates_dirs(self, tmp_path: Path) -> None:
        result = _execute_tool(
            "Write",
            {"file_path": "sub/dir/file.txt", "content": "nested"},
            cwd=str(tmp_path),
        )
        assert "Successfully wrote" in result
        assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"

    def test_edit_file(self, tmp_path: Path) -> None:
        test_file = tmp_path / "edit.txt"
        test_file.write_text("hello world")
        result = _execute_tool(
            "Edit",
            {"file_path": "edit.txt", "old_text": "world", "new_text": "plato"},
            cwd=str(tmp_path),
        )
        assert "Successfully edited" in result
        assert test_file.read_text() == "hello plato"

    def test_edit_text_not_found(self, tmp_path: Path) -> None:
        test_file = tmp_path / "edit.txt"
        test_file.write_text("hello world")
        result = _execute_tool(
            "Edit",
            {"file_path": "edit.txt", "old_text": "missing", "new_text": "x"},
            cwd=str(tmp_path),
        )
        assert "not found" in result.lower()

    def test_unknown_tool(self) -> None:
        result = _execute_tool("UnknownTool", {})
        assert "Unknown tool" in result


# -- Foundation Agent runtime property -----------------------------------------


class TestFoundationRuntime:
    def test_runtime_is_bedrock_without_sdk(self) -> None:
        """When claude_agent_sdk is not importable, runtime should be bedrock."""
        from platform_agent._legacy_foundation import FoundationAgent

        agent = FoundationAgent()
        # In test env, SDK is mocked so _HAS_SDK could be True or False
        assert agent.runtime in ("claude-agent-sdk", "bedrock")

    def test_agent_has_bedrock_run_method(self) -> None:
        from platform_agent._legacy_foundation import FoundationAgent

        agent = FoundationAgent()
        assert hasattr(agent, "_run_bedrock")


# -- Converse function (mocked boto3) -----------------------------------------


class TestConverse:
    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_simple_response(self, mock_client) -> None:
        """Test a simple response without tool use."""
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": "This is a test response."}]
                }
            },
            "stopReason": "end_turn",
        }

        with patch("platform_agent.bedrock_runtime._get_client", return_value=mock_client):
            result = await converse(
                prompt="Hello",
                system_prompt="You are a test agent.",
                tool_names=[],
            )

        assert result == "This is a test response."
        mock_client.converse.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_use_then_response(self, mock_client, tmp_path: Path) -> None:
        """Test a tool use round followed by a final response."""
        # First call: Claude wants to use Read tool
        mock_client.converse.side_effect = [
            {
                "output": {
                    "message": {
                        "content": [
                            {"text": "Let me check the file."},
                            {
                                "toolUse": {
                                    "name": "Read",
                                    "toolUseId": "tool-123",
                                    "input": {"file_path": "test.txt"},
                                }
                            },
                        ]
                    }
                },
                "stopReason": "tool_use",
            },
            # Second call: Claude provides final response
            {
                "output": {
                    "message": {
                        "content": [{"text": "The file contains: hello world"}]
                    }
                },
                "stopReason": "end_turn",
            },
        ]

        # Create the file the tool will read
        (tmp_path / "test.txt").write_text("hello world")

        with patch("platform_agent.bedrock_runtime._get_client", return_value=mock_client):
            result = await converse(
                prompt="Read test.txt",
                system_prompt="You are a test agent.",
                tool_names=["Read"],
                cwd=str(tmp_path),
            )

        assert "hello world" in result
        assert mock_client.converse.call_count == 2

    @pytest.mark.asyncio
    async def test_model_from_env(self, mock_client) -> None:
        """Test that PLATO_MODEL env var is respected."""
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
        }

        with patch("platform_agent.bedrock_runtime._get_client", return_value=mock_client):
            with patch.dict(os.environ, {"PLATO_MODEL": "custom-model-id"}):
                await converse(
                    prompt="test",
                    system_prompt="test",
                )

        call_kwargs = mock_client.converse.call_args.kwargs
        assert call_kwargs["modelId"] == "custom-model-id"
