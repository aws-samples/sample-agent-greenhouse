"""Bedrock runtime — direct Claude invocation via boto3.

Provides a drop-in replacement for claude_agent_sdk when the SDK is not
available. Uses Bedrock's converse API with tool definitions for file
operations (Read, Glob, Grep) so the agent can actually inspect codebases.

Environment:
    PLATO_MODEL: Model ID (default: global.anthropic.claude-sonnet-4-6)
    PLATO_REGION: AWS region (default: AWS_REGION env or us-west-2)
    PLATO_MAX_TOKENS: Max response tokens (default: 4096)
    AWS_PROFILE / AWS_ACCESS_KEY_ID: Standard AWS auth
"""

from __future__ import annotations

import glob as glob_mod
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "global.anthropic.claude-sonnet-4-6"
DEFAULT_REGION = os.environ.get("AWS_REGION", "us-west-2")
DEFAULT_MAX_TOKENS = 4096
MAX_TOOL_ROUNDS = 20


@dataclass
class BedrockMessage:
    """Simple message container matching claude_agent_sdk interface."""

    type: str  # "text", "tool_use", "result"
    content: str = ""
    result: str = ""


def _get_client():
    """Create a boto3 Bedrock Runtime client."""
    import boto3

    region = os.environ.get("PLATO_REGION", DEFAULT_REGION)
    return boto3.client("bedrock-runtime", region_name=region)


def _build_tool_definitions(tool_names: list[str]) -> list[dict]:
    """Build Bedrock-compatible tool definitions for requested tools."""
    tool_defs = {
        "Read": {
            "name": "Read",
            "description": "Read the contents of a file. Returns the full text content.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the file to read (relative to working directory)",
                        }
                    },
                    "required": ["file_path"],
                }
            },
        },
        "Glob": {
            "name": "Glob",
            "description": "Find files matching a glob pattern. Returns list of matching paths.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.py')",
                        }
                    },
                    "required": ["pattern"],
                }
            },
        },
        "Grep": {
            "name": "Grep",
            "description": "Search for a pattern in files. Returns matching lines with file paths and line numbers.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Regex pattern to search for",
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory or file to search in (default: '.')",
                        },
                        "include": {
                            "type": "string",
                            "description": "File pattern to include (e.g., '*.py')",
                        },
                    },
                    "required": ["pattern"],
                }
            },
        },
        "Bash": {
            "name": "Bash",
            "description": "Run a shell command and return stdout+stderr. Use for inspecting project structure, running tests, etc.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute",
                        }
                    },
                    "required": ["command"],
                }
            },
        },
        "Write": {
            "name": "Write",
            "description": "Write content to a file. Creates parent directories if needed.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to write to",
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write",
                        },
                    },
                    "required": ["file_path", "content"],
                }
            },
        },
        "Edit": {
            "name": "Edit",
            "description": "Edit a file by replacing exact text.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the file",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Exact text to find",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text",
                        },
                    },
                    "required": ["file_path", "old_text", "new_text"],
                }
            },
        },
    }

    return [
        {"toolSpec": tool_defs[name]}
        for name in tool_names
        if name in tool_defs
    ]


def _execute_tool(name: str, inputs: dict, cwd: str | None = None) -> str:
    """Execute a tool and return the result as a string."""
    work_dir = cwd or "."

    if name == "Read":
        file_path = inputs.get("file_path", "")
        full_path = Path(work_dir) / file_path
        try:
            content = full_path.read_text(encoding="utf-8")
            # Truncate large files — sufficient for demo; add pagination for production
            return content[:10000] if len(content) > 10000 else content
        except FileNotFoundError:
            return f"Error: File not found: {file_path}"
        except Exception as e:
            return f"Error reading {file_path}: {e}"

    elif name == "Glob":
        pattern = inputs.get("pattern", "")
        matches = sorted(glob_mod.glob(str(Path(work_dir) / pattern), recursive=True))
        # Make paths relative to work_dir
        rel_matches = []
        for m in matches:
            try:
                rel_matches.append(str(Path(m).relative_to(work_dir)))
            except ValueError:
                rel_matches.append(m)
        return "\n".join(rel_matches) if rel_matches else "No files found"

    elif name == "Grep":
        pattern = inputs.get("pattern", "")
        search_path = inputs.get("path", ".")
        include = inputs.get("include", "")
        full_path = Path(work_dir) / search_path

        cmd = ["grep", "-rn", pattern, str(full_path)]
        if include:
            cmd = ["grep", "-rn", f"--include={include}", pattern, str(full_path)]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout[:5000]  # Limit output size
            return output if output else "No matches found"
        except subprocess.TimeoutExpired:
            return "Error: grep timed out"
        except Exception as e:
            return f"Error: {e}"

    elif name == "Bash":
        # ⚠️ Demo only — shell=True with unsanitized input is not production-safe.
        # For production, add command allowlisting or sandboxed execution.
        command = inputs.get("command", "")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=work_dir,
            )
            output = result.stdout + result.stderr
            return output[:5000] if output else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: command timed out (30s)"
        except Exception as e:
            return f"Error: {e}"

    elif name == "Write":
        file_path = inputs.get("file_path", "")
        content = inputs.get("content", "")
        full_path = Path(work_dir) / file_path
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {file_path}"
        except Exception as e:
            return f"Error writing {file_path}: {e}"

    elif name == "Edit":
        file_path = inputs.get("file_path", "")
        old_text = inputs.get("old_text", "")
        new_text = inputs.get("new_text", "")
        full_path = Path(work_dir) / file_path
        try:
            content = full_path.read_text(encoding="utf-8")
            if old_text not in content:
                return f"Error: old_text not found in {file_path}"
            content = content.replace(old_text, new_text, 1)
            full_path.write_text(content, encoding="utf-8")
            return f"Successfully edited {file_path}"
        except Exception as e:
            return f"Error editing {file_path}: {e}"

    return f"Unknown tool: {name}"


async def converse(
    prompt: str,
    system_prompt: str,
    tool_names: list[str] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    cwd: str | None = None,
) -> str:
    """Run a multi-turn conversation with Bedrock Claude, handling tool use.

    Args:
        prompt: User's task prompt.
        system_prompt: System prompt (foundation + skill extensions).
        tool_names: List of tool names to make available.
        model: Bedrock model ID override.
        max_tokens: Max response tokens override.
        cwd: Working directory for tool execution.

    Returns:
        The final text response from Claude.
    """
    client = _get_client()
    model_id = model or os.environ.get("PLATO_MODEL", DEFAULT_MODEL)
    max_tok = max_tokens or int(os.environ.get("PLATO_MAX_TOKENS", DEFAULT_MAX_TOKENS))

    # Build tool config
    tools = _build_tool_definitions(tool_names or [])
    tool_config = {"tools": tools} if tools else {}

    # Initial messages
    messages = [{"role": "user", "content": [{"text": prompt}]}]

    system = [{"text": system_prompt}]

    for _round in range(MAX_TOOL_ROUNDS):
        # Call Bedrock
        kwargs: dict[str, Any] = {
            "modelId": model_id,
            "messages": messages,
            "system": system,
            "inferenceConfig": {"maxTokens": max_tok},
        }
        if tool_config:
            kwargs["toolConfig"] = tool_config

        logger.info(f"Bedrock call #{_round + 1} (model={model_id})")
        response = client.converse(**kwargs)

        output = response.get("output", {})
        stop_reason = response.get("stopReason", "end_turn")
        content_blocks = output.get("message", {}).get("content", [])

        # Add assistant response to messages
        messages.append({"role": "assistant", "content": content_blocks})

        # Check if we need to handle tool use
        if stop_reason == "tool_use":
            tool_results = []
            for block in content_blocks:
                if "toolUse" in block:
                    tool_use = block["toolUse"]
                    tool_name = tool_use["name"]
                    tool_id = tool_use["toolUseId"]
                    tool_input = tool_use.get("input", {})

                    logger.info(f"  Tool: {tool_name}({tool_input})")
                    result = _execute_tool(tool_name, tool_input, cwd=cwd)

                    tool_results.append(
                        {
                            "toolResult": {
                                "toolUseId": tool_id,
                                "content": [{"text": result}],
                            }
                        }
                    )

            # Send tool results back
            messages.append({"role": "user", "content": tool_results})
            continue

        # No more tool use — extract final text
        final_text = ""
        for block in content_blocks:
            if "text" in block:
                final_text += block["text"]

        return final_text

    return "Error: exceeded maximum tool rounds"
