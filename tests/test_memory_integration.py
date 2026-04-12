"""Tests for memory integration with FoundationAgent, handler, and CLI."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from platform_agent.cli import cli
from platform_agent._legacy_foundation import FoundationAgent
from platform_agent.memory import (
    InMemoryStore,
    LocalMemory,
    create_memory_backend,
    create_memory_store,
)
from platform_agent.slack.handler import SlackMessage


# ---------------------------------------------------------------------------
# FoundationAgent memory integration tests (legacy KV API)
# ---------------------------------------------------------------------------


class TestFoundationAgentMemory:
    def test_agent_with_no_memory(self):
        """Agent without memory store should work normally."""
        agent = FoundationAgent()
        assert agent.memory_store is None

    def test_agent_with_memory_store(self):
        """Agent can be initialized with a memory store."""
        store = InMemoryStore()
        agent = FoundationAgent(memory_store=store)
        assert agent.memory_store is store

    def test_system_prompt_includes_memory_section(self):
        """When memory is attached, system prompt should mention it."""
        store = InMemoryStore()
        agent = FoundationAgent(memory_store=store)
        prompt = agent._build_system_prompt()
        assert "Memory" in prompt
        assert "persistent memory store" in prompt

    def test_system_prompt_without_memory(self):
        """Without memory, system prompt should not mention memory."""
        agent = FoundationAgent()
        prompt = agent._build_system_prompt()
        assert "persistent memory store" not in prompt

    @pytest.mark.asyncio
    async def test_enrich_with_memory_no_store(self):
        agent = FoundationAgent()
        result = await agent._enrich_with_memory("test prompt")
        assert result == "test prompt"

    @pytest.mark.asyncio
    async def test_enrich_with_memory_no_results(self):
        store = InMemoryStore()
        agent = FoundationAgent(memory_store=store)
        result = await agent._enrich_with_memory("test prompt")
        assert result == "test prompt"

    @pytest.mark.asyncio
    async def test_enrich_with_memory_has_results(self):
        store = InMemoryStore()
        await store.put("interactions", "key1", {
            "summary": "Previously discussed agent architecture",
        })
        agent = FoundationAgent(memory_store=store)
        result = await agent._enrich_with_memory("agent architecture")
        assert "<memory_context>" in result
        assert "Previously discussed agent architecture" in result

    @pytest.mark.asyncio
    async def test_store_to_memory_no_store(self):
        agent = FoundationAgent()
        await agent._store_to_memory("prompt", "result")

    @pytest.mark.asyncio
    async def test_store_to_memory_saves(self):
        store = InMemoryStore()
        agent = FoundationAgent(memory_store=store)
        await agent._store_to_memory("test prompt", "test result")
        keys = await store.list("interactions")
        assert len(keys) == 1
        entry = await store.get("interactions", keys[0])
        assert entry["prompt"] == "test prompt"
        assert entry["summary"] == "test result"


# ---------------------------------------------------------------------------
# SlackMessage memory properties tests
# ---------------------------------------------------------------------------


class TestSlackMessageMemoryProps:
    def test_memory_session_id_with_thread(self):
        msg = SlackMessage(
            text="hi", user_id="U123", channel_id="C456",
            thread_ts="1234567890.123456", ts="1234567891.000000",
        )
        sid = msg.memory_session_id
        assert sid.startswith("plato-thread-1234567890-123456")
        assert len(sid) >= 33

    def test_memory_session_id_no_thread_channel(self):
        msg = SlackMessage(
            text="hi", user_id="U123", channel_id="C456",
            ts="1234567891.000000", is_dm=False,
        )
        session_id = msg.memory_session_id
        assert session_id.startswith("plato-chan-C456-U123")
        # Session IDs no longer include a date suffix — persistent across days
        # AgentCore requires min 33 chars
        assert len(session_id) >= 33

    def test_memory_session_id_dm(self):
        msg = SlackMessage(
            text="hi", user_id="U123", channel_id="D789",
            ts="1234567891.000000", is_dm=True,
        )
        session_id = msg.memory_session_id
        assert session_id.startswith("plato-dm-U123")

    def test_memory_actor_id(self):
        msg = SlackMessage(
            text="hi", user_id="U123", channel_id="C456",
        )
        assert msg.memory_actor_id == "U123"

    def test_same_thread_same_session(self):
        """Two messages in the same thread should have the same session_id."""
        msg1 = SlackMessage(
            text="first", user_id="U111", channel_id="C456",
            thread_ts="1234.5678", ts="1234.5679",
        )
        msg2 = SlackMessage(
            text="second", user_id="U222", channel_id="C456",
            thread_ts="1234.5678", ts="1234.5680",
        )
        assert msg1.memory_session_id == msg2.memory_session_id

    def test_session_id_min_length(self):
        """All session ID formats should meet AgentCore 33-char minimum."""
        thread_msg = SlackMessage(
            text="hi", user_id="U123", channel_id="C456",
            thread_ts="1234567890.123456", ts="1234567891.000000",
        )
        chan_msg = SlackMessage(
            text="hi", user_id="U123", channel_id="C456",
            ts="1234567891.000000", is_dm=False,
        )
        dm_msg = SlackMessage(
            text="hi", user_id="U123", channel_id="D789",
            ts="1234567891.000000", is_dm=True,
        )
        for msg in [thread_msg, chan_msg, dm_msg]:
            assert len(msg.memory_session_id) >= 33, (
                f"Session ID too short ({len(msg.memory_session_id)}): "
                f"{msg.memory_session_id}"
            )


# ---------------------------------------------------------------------------
# Memory CLI tests (legacy)
# ---------------------------------------------------------------------------


class TestMemoryCLI:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_memory_help(self, runner):
        result = runner.invoke(cli, ["memory", "--help"])
        assert result.exit_code == 0
        assert "memory store" in result.output.lower() or "memory" in result.output.lower()

    def test_memory_status(self, runner):
        result = runner.invoke(cli, ["memory", "status"])
        assert result.exit_code == 0

    def test_memory_list_empty(self, runner):
        result = runner.invoke(cli, ["memory", "list"])
        assert result.exit_code == 0

    def test_memory_search_empty(self, runner):
        result = runner.invoke(cli, ["memory", "search", "ns", "test"])
        assert result.exit_code == 0
