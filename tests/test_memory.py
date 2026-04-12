"""Tests for the event-based memory layer."""

from __future__ import annotations

import pytest

from platform_agent.memory import (
    ConversationTurn,
    InMemoryStore,
    LocalMemory,
    MemoryRecord,
    AgentCoreMemory,
    create_memory_backend,
    create_memory_store,
    turns_to_bedrock_messages,
)


# ---------------------------------------------------------------------------
# LocalMemory tests (new event-based API)
# ---------------------------------------------------------------------------


class TestLocalMemory:
    @pytest.fixture
    def memory(self) -> LocalMemory:
        return LocalMemory()

    def test_add_user_message(self, memory: LocalMemory) -> None:
        event_id = memory.add_user_message("actor1", "session1", "Hello")
        assert event_id is not None
        assert event_id.startswith("local-evt-")

    def test_add_assistant_message(self, memory: LocalMemory) -> None:
        event_id = memory.add_assistant_message("actor1", "session1", "Hi there!")
        assert event_id is not None

    def test_conversation_history(self, memory: LocalMemory) -> None:
        memory.add_user_message("actor1", "session1", "Hello")
        memory.add_assistant_message("actor1", "session1", "Hi!")
        memory.add_user_message("actor1", "session1", "How are you?")

        turns = memory.get_conversation_history("actor1", "session1")
        assert len(turns) == 3
        assert turns[0].role == "user"
        assert turns[0].text == "Hello"
        assert turns[1].role == "assistant"
        assert turns[1].text == "Hi!"
        assert turns[2].role == "user"
        assert turns[2].text == "How are you?"

    def test_conversation_history_max_turns(self, memory: LocalMemory) -> None:
        for i in range(10):
            memory.add_user_message("actor1", "session1", f"msg {i}")
            memory.add_assistant_message("actor1", "session1", f"reply {i}")

        turns = memory.get_conversation_history("actor1", "session1", max_turns=4)
        assert len(turns) == 4
        # Should be the last 4 turns
        assert turns[0].text == "msg 8"
        assert turns[1].text == "reply 8"
        assert turns[2].text == "msg 9"
        assert turns[3].text == "reply 9"

    def test_session_isolation(self, memory: LocalMemory) -> None:
        memory.add_user_message("actor1", "session1", "Hello session 1")
        memory.add_user_message("actor1", "session2", "Hello session 2")

        turns1 = memory.get_conversation_history("actor1", "session1")
        turns2 = memory.get_conversation_history("actor1", "session2")

        assert len(turns1) == 1
        assert turns1[0].text == "Hello session 1"
        assert len(turns2) == 1
        assert turns2[0].text == "Hello session 2"

    def test_actor_isolation(self, memory: LocalMemory) -> None:
        memory.add_user_message("actor1", "session1", "I am actor 1")
        memory.add_user_message("actor2", "session1", "I am actor 2")

        turns1 = memory.get_conversation_history("actor1", "session1")
        turns2 = memory.get_conversation_history("actor2", "session1")

        assert len(turns1) == 1
        assert turns1[0].text == "I am actor 1"
        assert len(turns2) == 1
        assert turns2[0].text == "I am actor 2"

    def test_empty_history(self, memory: LocalMemory) -> None:
        turns = memory.get_conversation_history("actor1", "nonexistent")
        assert turns == []

    def test_metadata_stored(self, memory: LocalMemory) -> None:
        memory.add_user_message(
            "actor1", "session1", "Hello",
            metadata={"channel_id": "C123", "ts": "1234.5678"},
        )
        turns = memory.get_conversation_history("actor1", "session1")
        assert turns[0].metadata == {"channel_id": "C123", "ts": "1234.5678"}

    def test_search_long_term(self, memory: LocalMemory) -> None:
        memory.add_user_message("actor1", "session1", "I prefer serverless architecture")
        memory.add_assistant_message("actor1", "session1", "Great choice!")
        memory.add_user_message("actor1", "session1", "Deploy to ECS Fargate")

        results = memory.search_long_term("serverless")
        assert len(results) == 1
        assert "serverless" in results[0].text.lower()

    def test_search_long_term_empty(self, memory: LocalMemory) -> None:
        results = memory.search_long_term("anything")
        assert results == []

    def test_search_long_term_limit(self, memory: LocalMemory) -> None:
        for i in range(10):
            memory.add_user_message("actor1", "session1", f"test item {i}")

        results = memory.search_long_term("test", top_k=3)
        assert len(results) == 3

    def test_search_long_term_actor_isolation(self, memory: LocalMemory) -> None:
        """search_long_term with actor_id should only return that actor's data."""
        memory.add_user_message("alice", "session1", "I prefer serverless architecture")
        memory.add_user_message("bob", "session2", "I prefer serverless containers")

        # Without actor_id — returns both
        results = memory.search_long_term("serverless")
        assert len(results) == 2

        # With actor_id — only returns alice's
        results = memory.search_long_term("serverless", actor_id="alice")
        assert len(results) == 1
        assert "architecture" in results[0].text

        # With actor_id — only returns bob's
        results = memory.search_long_term("serverless", actor_id="bob")
        assert len(results) == 1
        assert "containers" in results[0].text

        # Unknown actor — returns nothing
        results = memory.search_long_term("serverless", actor_id="charlie")
        assert len(results) == 0

    def test_timestamps_set(self, memory: LocalMemory) -> None:
        memory.add_user_message("actor1", "session1", "Hello")
        turns = memory.get_conversation_history("actor1", "session1")
        assert turns[0].timestamp is not None

    def test_search_long_term_with_project_param(self, memory: LocalMemory) -> None:
        """LocalMemory.search_long_term accepts project param (interface compat)."""
        memory.add_user_message("alice", "s1", "deploy weather-agent")
        # project param is accepted but ignored in LocalMemory
        results = memory.search_long_term(
            "weather", actor_id="alice", project="weather-agent"
        )
        assert len(results) == 1
        assert "weather" in results[0].text.lower()


# ---------------------------------------------------------------------------
# Namespace isolation tests (AgentCoreMemory static methods)
# ---------------------------------------------------------------------------


class TestNamespaceIsolation:
    def test_actor_namespace(self) -> None:
        ns = AgentCoreMemory._actor_namespace("U123")
        assert ns == "/actors/U123/"

    def test_actor_namespace_special_chars(self) -> None:
        ns = AgentCoreMemory._actor_namespace("user-with-dashes")
        assert ns == "/actors/user-with-dashes/"

    def test_project_namespace(self) -> None:
        ns = AgentCoreMemory._project_namespace("U123", "weather-agent")
        assert ns == "/actors/U123/projects/weather-agent/"

    def test_project_namespace_nested(self) -> None:
        """Project namespace is always under actor namespace."""
        actor_ns = AgentCoreMemory._actor_namespace("U123")
        project_ns = AgentCoreMemory._project_namespace("U123", "my-project")
        assert project_ns.startswith(actor_ns)


# ---------------------------------------------------------------------------
# turns_to_bedrock_messages tests
# ---------------------------------------------------------------------------


class TestTurnsToBedrockMessages:
    def test_empty(self) -> None:
        assert turns_to_bedrock_messages([]) == []

    def test_basic_conversation(self) -> None:
        turns = [
            ConversationTurn(role="user", text="Hello"),
            ConversationTurn(role="assistant", text="Hi!"),
            ConversationTurn(role="user", text="How are you?"),
        ]
        messages = turns_to_bedrock_messages(turns)
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == [{"text": "Hello"}]
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"

    def test_skips_empty_turns(self) -> None:
        turns = [
            ConversationTurn(role="user", text="Hello"),
            ConversationTurn(role="assistant", text=""),
            ConversationTurn(role="user", text="Again"),
        ]
        messages = turns_to_bedrock_messages(turns)
        # Empty assistant message is skipped, consecutive user messages merged
        assert len(messages) >= 1
        assert messages[0]["role"] == "user"

    def test_merges_consecutive_same_role(self) -> None:
        turns = [
            ConversationTurn(role="user", text="Part 1"),
            ConversationTurn(role="user", text="Part 2"),
            ConversationTurn(role="assistant", text="Reply"),
        ]
        messages = turns_to_bedrock_messages(turns)
        assert messages[0]["role"] == "user"
        assert "Part 1" in messages[0]["content"][0]["text"]
        assert "Part 2" in messages[0]["content"][0]["text"]

    def test_starts_with_user(self) -> None:
        turns = [
            ConversationTurn(role="assistant", text="I started first"),
            ConversationTurn(role="user", text="Hello"),
            ConversationTurn(role="assistant", text="Hi!"),
        ]
        messages = turns_to_bedrock_messages(turns)
        assert messages[0]["role"] == "user"
        # Should have a synthetic user context marker
        assert "Previous conversation context" in messages[0]["content"][0]["text"]
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"
        assert messages[3]["role"] == "assistant"

    def test_all_assistant_gets_synthetic_user(self) -> None:
        turns = [
            ConversationTurn(role="assistant", text="A1"),
            ConversationTurn(role="assistant", text="A2"),
        ]
        messages = turns_to_bedrock_messages(turns)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert "Previous conversation context" in messages[0]["content"][0]["text"]
        assert messages[1]["role"] == "assistant"
        # Consecutive assistant messages should be merged
        assert "A1" in messages[1]["content"][0]["text"]
        assert "A2" in messages[1]["content"][0]["text"]

    def test_alternation_enforced(self) -> None:
        """Consecutive same-role messages should be merged to maintain alternation."""
        turns = [
            ConversationTurn(role="user", text="msg1"),
            ConversationTurn(role="user", text="msg2"),
            ConversationTurn(role="assistant", text="reply1"),
            ConversationTurn(role="assistant", text="reply2"),
            ConversationTurn(role="user", text="msg3"),
        ]
        messages = turns_to_bedrock_messages(turns)
        # Check strict alternation
        for i in range(1, len(messages)):
            assert messages[i]["role"] != messages[i - 1]["role"]


# ---------------------------------------------------------------------------
# Legacy InMemoryStore tests (backward compatibility)
# ---------------------------------------------------------------------------


class TestInMemoryStoreLegacy:
    @pytest.fixture
    def store(self) -> InMemoryStore:
        return InMemoryStore()

    @pytest.mark.asyncio
    async def test_put_and_get(self, store: InMemoryStore) -> None:
        await store.put("ns1", "key1", {"summary": "hello"})
        result = await store.get("ns1", "key1")
        assert result == {"summary": "hello"}

    @pytest.mark.asyncio
    async def test_get_missing_key(self, store: InMemoryStore) -> None:
        result = await store.get("ns1", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_put_overwrites(self, store: InMemoryStore) -> None:
        await store.put("ns1", "key1", {"v": 1})
        await store.put("ns1", "key1", {"v": 2})
        result = await store.get("ns1", "key1")
        assert result == {"v": 2}

    @pytest.mark.asyncio
    async def test_list_keys(self, store: InMemoryStore) -> None:
        await store.put("ns1", "a", {"x": 1})
        await store.put("ns1", "b", {"x": 2})
        keys = await store.list("ns1")
        assert sorted(keys) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_delete_existing(self, store: InMemoryStore) -> None:
        await store.put("ns1", "key1", {"v": 1})
        deleted = await store.delete("ns1", "key1")
        assert deleted is True
        assert await store.get("ns1", "key1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store: InMemoryStore) -> None:
        deleted = await store.delete("ns1", "nope")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_search_by_value(self, store: InMemoryStore) -> None:
        await store.put("ns1", "note1", {"summary": "Agent architecture review"})
        await store.put("ns1", "note2", {"summary": "Deployment configuration"})
        results = await store.search("ns1", "architecture")
        assert len(results) == 1
        assert results[0]["key"] == "note1"


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestCreateMemoryBackend:
    def test_defaults_to_local(self) -> None:
        backend = create_memory_backend()
        assert isinstance(backend, LocalMemory)

    def test_explicit_local(self) -> None:
        backend = create_memory_backend(backend="local")
        assert isinstance(backend, LocalMemory)

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown memory backend"):
            create_memory_backend(backend="redis")

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLATO_MEMORY_BACKEND", "local")
        backend = create_memory_backend()
        assert isinstance(backend, LocalMemory)


class TestCreateMemoryStoreLegacy:
    def test_factory_defaults_to_local(self) -> None:
        store = create_memory_store()
        assert isinstance(store, InMemoryStore)

    def test_factory_explicit_local(self) -> None:
        store = create_memory_store(backend="local")
        assert isinstance(store, InMemoryStore)

    def test_factory_unknown_backend_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown memory backend"):
            create_memory_store(backend="redis")

    def test_factory_agentcore_redirects_to_new_api(self) -> None:
        with pytest.raises(ValueError, match="event-based API"):
            create_memory_store(backend="agentcore")
