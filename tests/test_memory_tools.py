"""Tests for tools/memory_tools.py — save_memory and recall_memory tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from platform_agent.memory import LocalMemory, MemoryRecord
from platform_agent.foundation.tools.memory_tools import (
    _CATEGORY_TO_STRATEGY,
    _VALID_CATEGORIES,
    create_memory_tools,
)


@pytest.fixture
def memory_backend():
    """Create a LocalMemory backend for testing."""
    return LocalMemory()


@pytest.fixture
def tools(memory_backend):
    """Create bound save_memory and recall_memory tools."""
    return create_memory_tools(
        memory_backend=memory_backend,
        actor_id="U123",
        session_id="test-session-id-padded-to-33chars",
    )


@pytest.fixture
def save_memory(tools):
    """Get the save_memory tool."""
    return tools[0]


@pytest.fixture
def recall_memory(tools):
    """Get the recall_memory tool."""
    return tools[1]


class TestSaveMemory:
    def test_save_fact(self, save_memory, memory_backend):
        """Saving a fact should create a structured event."""
        result = save_memory(content="Python 3.12 is required", category="fact")
        assert "saved" in result.lower()
        assert "fact" in result.lower()

        # Verify the event was created
        turns = memory_backend.get_conversation_history(
            "U123", "test-session-id-padded-to-33chars"
        )
        assert len(turns) == 1
        assert "[MEMORY:fact]" in turns[0].text
        assert "Python 3.12 is required" in turns[0].text

    def test_save_preference(self, save_memory, memory_backend):
        """Saving a preference should use the preference category."""
        result = save_memory(content="User prefers serverless", category="preference")
        assert "saved" in result.lower()

        turns = memory_backend.get_conversation_history(
            "U123", "test-session-id-padded-to-33chars"
        )
        assert "[MEMORY:preference]" in turns[0].text

    def test_save_default_category(self, save_memory, memory_backend):
        """Default category should be 'fact'."""
        result = save_memory(content="Some knowledge")
        assert "fact" in result.lower()

        turns = memory_backend.get_conversation_history(
            "U123", "test-session-id-padded-to-33chars"
        )
        assert "[MEMORY:fact]" in turns[0].text

    def test_save_invalid_category(self, save_memory):
        """Invalid category should return an error message."""
        result = save_memory(content="test", category="invalid_cat")
        assert "Invalid category" in result
        assert "invalid_cat" in result

    def test_save_all_valid_categories(self, memory_backend):
        """All valid categories should be accepted."""
        for category in _VALID_CATEGORIES:
            tools = create_memory_tools(memory_backend, "U123", "test-session-id-padded-to-33chars")
            save = tools[0]
            result = save(content=f"Test {category}", category=category)
            assert "saved" in result.lower(), f"Category '{category}' should be valid"

    def test_save_handles_backend_error(self):
        """Should handle backend errors gracefully."""
        mock_backend = MagicMock()
        mock_backend.add_assistant_message.side_effect = RuntimeError("Connection lost")

        tools = create_memory_tools(mock_backend, "U123", "test-session-id-padded-to-33chars")
        save = tools[0]
        result = save(content="test", category="fact")
        assert "Failed" in result


class TestRecallMemory:
    def test_recall_finds_results(self, save_memory, recall_memory, memory_backend):
        """recall_memory should find previously saved memories."""
        save_memory(content="Python 3.12 is required for this project", category="fact")
        result = recall_memory(query="Python")
        assert "Python" in result
        assert "1" in result  # At least 1 record found

    def test_recall_no_results(self, recall_memory):
        """recall_memory should report when no results found."""
        result = recall_memory(query="nonexistent topic xyz")
        assert "No memories found" in result

    def test_recall_with_category_filter(self):
        """recall_memory with category should map to strategy_id."""
        mock_backend = MagicMock()
        mock_backend.search_long_term.return_value = [
            MemoryRecord(
                record_id="r1",
                text="User prefers serverless",
                score=0.95,
                strategy_id="userPreferences",
            )
        ]

        tools = create_memory_tools(mock_backend, "U123", "test-session-id-padded-to-33chars")
        recall = tools[1]
        result = recall(query="architecture preference", category="preference")

        # Verify strategy_id was passed
        mock_backend.search_long_term.assert_called_once()
        call_kwargs = mock_backend.search_long_term.call_args[1]
        assert call_kwargs["strategy_id"] == "userPreferences"
        assert "serverless" in result

    def test_recall_formats_results(self):
        """recall_memory should format multiple results with scores."""
        mock_backend = MagicMock()
        mock_backend.search_long_term.return_value = [
            MemoryRecord(record_id="r1", text="Fact one", score=0.95, strategy_id="semantic"),
            MemoryRecord(record_id="r2", text="Fact two", score=0.80, strategy_id="semantic"),
        ]

        tools = create_memory_tools(mock_backend, "U123", "test-session-id-padded-to-33chars")
        recall = tools[1]
        result = recall(query="facts")

        assert "2 memory record(s)" in result
        assert "1." in result
        assert "2." in result
        assert "Fact one" in result
        assert "Fact two" in result

    def test_recall_handles_backend_error(self):
        """Should handle backend errors gracefully."""
        mock_backend = MagicMock()
        mock_backend.search_long_term.side_effect = RuntimeError("Service unavailable")

        tools = create_memory_tools(mock_backend, "U123", "test-session-id-padded-to-33chars")
        recall = tools[1]
        result = recall(query="test")
        assert "Failed" in result


class TestCategoryStrategyMapping:
    def test_all_categories_have_mappings(self):
        """All valid categories should have a strategy mapping."""
        for category in _VALID_CATEGORIES:
            assert category in _CATEGORY_TO_STRATEGY, (
                f"Category '{category}' has no strategy mapping"
            )

    def test_create_memory_tools_returns_two(self, memory_backend):
        """create_memory_tools should return exactly 2 tools."""
        tools = create_memory_tools(memory_backend, "U123", "test-session-id-padded-to-33chars")
        assert len(tools) == 2
