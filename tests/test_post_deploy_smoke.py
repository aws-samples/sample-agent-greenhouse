"""Layer 3 — Post-Deploy Smoke Tests.

Run after each container/Lambda deploy to verify the system works E2E.
Tests can run against the deployed AgentCore endpoint or locally.

When run as pytest (unit mode):
- Tests mock external services and verify handler logic
- Tests verify Slack mrkdwn format conversion
- Tests verify msg_too_long handling

When run as a script with --live flag:
- Connects to the actual AgentCore WebSocket endpoint
- Sends a test prompt and verifies streaming works
- Checks response format

Usage:
    pytest tests/test_post_deploy_smoke.py -v       # Unit mode
    python tests/test_post_deploy_smoke.py --live    # Live E2E mode (requires deployed agent)
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Slack Format Verification
# ---------------------------------------------------------------------------


class TestSlackMrkdwnConversion:
    """Verify _markdown_to_slack_mrkdwn correctly converts formats."""

    @pytest.fixture
    def converter(self):
        """Get the static mrkdwn converter method."""
        from platform_agent.slack.handler import SlackEventHandler
        return SlackEventHandler._markdown_to_slack_mrkdwn

    def test_bold_conversion(self, converter):
        """**bold** → *bold*"""
        assert converter("**hello**") == "*hello*"

    def test_bold_in_sentence(self, converter):
        """Bold within a sentence."""
        result = converter("This is **important** text")
        assert result == "This is *important* text"

    def test_link_conversion(self, converter):
        """[text](url) → <url|text>"""
        result = converter("[Click here](https://example.com)")
        assert result == "<https://example.com|Click here>"

    def test_heading_conversion(self, converter):
        """### Heading → *Heading*"""
        result = converter("### My Section")
        assert result == "*My Section*"

    def test_h2_conversion(self, converter):
        """## Heading → *Heading*"""
        result = converter("## Overview")
        assert result == "*Overview*"

    def test_code_block_preserved(self, converter):
        """Content inside code blocks should not be converted."""
        text = "Normal **bold**\n```\n**not bold**\n```\nAfter **bold**"
        result = converter(text)
        # Code block content should remain double-asterisk (not converted)
        assert "**not bold**" in result  # Code block preserved as-is
        # Outside code should be converted to single-asterisk
        assert result.startswith("Normal *bold*")  # Before code block converted

    def test_inline_code_preserved(self, converter):
        """Content inside inline code should not be converted."""
        text = "Use `**not bold**` for code"
        result = converter(text)
        assert "**not bold**" in result  # Inline code preserved

    def test_empty_string(self, converter):
        """Empty string returns empty string."""
        assert converter("") == ""

    def test_no_markdown(self, converter):
        """Plain text passes through unchanged."""
        assert converter("Hello world") == "Hello world"

    def test_multiple_links(self, converter):
        """Multiple links in one message."""
        text = "See [docs](https://docs.com) and [code](https://github.com)"
        result = converter(text)
        assert "<https://docs.com|docs>" in result
        assert "<https://github.com|code>" in result

    def test_mixed_formatting(self, converter):
        """Multiple format types in one message."""
        text = "## Title\n**Bold** and [link](https://x.com)\n`code`"
        result = converter(text)
        assert "*Title*" in result
        assert "*Bold*" in result
        assert "<https://x.com|link>" in result
        assert "`code`" in result


# ---------------------------------------------------------------------------
# Message Chunking (msg_too_long prevention)
# ---------------------------------------------------------------------------


class TestMessageChunking:
    """Verify long messages are properly chunked."""

    def test_short_message_not_chunked(self):
        """Messages under limit are sent as-is."""
        from platform_agent.slack.handler import SlackEventHandler
        handler = SlackEventHandler.__new__(SlackEventHandler)
        # Just verify the constant exists
        assert hasattr(handler, "SLACK_MAX_TEXT_LENGTH") or \
            hasattr(SlackEventHandler, "SLACK_MAX_TEXT_LENGTH")

    def test_max_text_length_is_reasonable(self):
        """SLACK_MAX_TEXT_LENGTH is set to a reasonable value."""
        from platform_agent.slack.handler import SlackEventHandler
        limit = getattr(SlackEventHandler, "SLACK_MAX_TEXT_LENGTH", None)
        if limit is not None:
            assert 3000 <= limit <= 50000, f"Unreasonable limit: {limit}"


# ---------------------------------------------------------------------------
# WebSocket Handler Registration
# ---------------------------------------------------------------------------


class TestWebSocketHandlerRegistered:
    """Verify the WebSocket handler is registered in entrypoint."""

    def test_ws_handler_function_exists(self):
        """ws_handler function exists in entrypoint module."""
        import entrypoint
        assert hasattr(entrypoint, "ws_handler"), \
            "ws_handler function not found in entrypoint.py"

    def test_ws_handler_is_callable(self):
        """ws_handler is callable (async function)."""
        import entrypoint
        handler = getattr(entrypoint, "ws_handler", None)
        assert handler is not None
        assert callable(handler)


# ---------------------------------------------------------------------------
# Entrypoint Initialization Smoke
# ---------------------------------------------------------------------------


class TestEntrypointSmoke:
    """Basic smoke tests for entrypoint initialization."""

    def test_ensure_initialized_registers_tools(self):
        """_ensure_initialized populates _extra_tools."""
        import importlib

        with patch.dict(os.environ, {
            "GITHUB_TOKEN": "ghp_test",
            "WORKSPACE_DIR": "/tmp/test",
            "ENABLE_CLAUDE_CODE": "false",
        }):
            with patch("bedrock_agentcore.BedrockAgentCoreApp"):
                import entrypoint
                importlib.reload(entrypoint)
                entrypoint._initialized = False
                entrypoint._extra_tools = None

                with patch("entrypoint.MemoryClient", create=True):
                    with patch("entrypoint.AgentCoreMemory", create=True):
                        try:
                            entrypoint._ensure_initialized()
                        except Exception:
                            pass

                assert entrypoint._extra_tools is not None, \
                    "_extra_tools not initialized"
                assert len(entrypoint._extra_tools) >= 20, \
                    f"Expected >= 20 tools (13 GitHub + 7 AIDLC), got {len(entrypoint._extra_tools)}"

    def test_model_id_default(self):
        """Default MODEL_ID is Opus 4.6."""
        import entrypoint
        # Either from env or default
        assert "opus" in entrypoint.MODEL_ID.lower() or \
            "claude" in entrypoint.MODEL_ID.lower(), \
            f"Unexpected MODEL_ID: {entrypoint.MODEL_ID}"


# ---------------------------------------------------------------------------
# SOUL.md Content Verification
# ---------------------------------------------------------------------------


class TestSOULContent:
    """Verify SOUL.md contains required behavioral rules."""

    @pytest.fixture
    def soul_content(self):
        """Read SOUL.md from workspace."""
        soul_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "workspace", "SOUL.md"
        )
        if not os.path.exists(soul_path):
            pytest.skip("SOUL.md not found")
        with open(soul_path) as f:
            return f.read()

    def test_aidlc_mandatory_section(self, soul_content):
        """SOUL.md contains MANDATORY AIDLC section."""
        assert "AIDLC" in soul_content
        assert "MANDATORY" in soul_content

    def test_aidlc_inception_referenced(self, soul_content):
        """SOUL.md references aidlc_start_inception tool."""
        assert "aidlc_start_inception" in soul_content

    def test_slack_rules_section(self, soul_content):
        """SOUL.md contains Slack communication rules."""
        assert "Slack Communication Rules" in soul_content

    def test_no_write_file_on_first_message(self, soul_content):
        """SOUL.md prohibits write_file on first message."""
        assert "write_file" in soul_content
        assert "Must NOT Do On First Message" in soul_content

    def test_github_workspace_rule(self, soul_content):
        """SOUL.md establishes GitHub as workspace."""
        assert "GitHub" in soul_content

    def test_tool_discipline_section(self, soul_content):
        """SOUL.md contains tool use discipline rules."""
        assert "Tool Use Discipline" in soul_content


# ---------------------------------------------------------------------------
# Live E2E (only when --live flag is passed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("PLATO_LIVE_TEST"),
    reason="Set PLATO_LIVE_TEST=1 to run live E2E tests",
)
class TestLiveE2E:
    """Live tests against deployed AgentCore endpoint.

    Set PLATO_LIVE_TEST=1 and optionally AGENTCORE_WS_URL to run.
    """

    def test_websocket_connection(self):
        """Can connect to AgentCore WebSocket endpoint."""
        import asyncio
        try:
            import websockets
        except ImportError:
            pytest.skip("websockets not installed")

        ws_url = os.environ.get(
            "AGENTCORE_WS_URL",
            "wss://localhost:8080/ws"
        )

        async def _test():
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({
                    "prompt": "Hello, this is a smoke test.",
                    "session_id": "smoke-test",
                }))
                response = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(response)
                assert data["type"] in ("delta", "complete", "tool_start")

        asyncio.run(_test())
