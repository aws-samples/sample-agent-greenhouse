"""Tests for multi-strategy LTM context loading.

Verifies:
- _load_ltm_context queries all 4 memory strategies
- Results are formatted with section labels
- current_message is used for semantic matching
- Graceful fallback when memory_client is None or strategies fail
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# We need to import _load_ltm_context from entrypoint.
# Since entrypoint has heavy imports, we mock the dependencies.
@pytest.fixture(autouse=True)
def _mock_entrypoint_deps(monkeypatch):
    """Mock heavy entrypoint dependencies so we can import the function."""
    import sys

    # Pre-mock modules that entrypoint imports at module level
    mock_modules = {
        "strands": MagicMock(),
        "strands.session": MagicMock(),
        "strands.models.bedrock": MagicMock(),
        "mangum": MagicMock(),
        "starlette": MagicMock(),
        "starlette.applications": MagicMock(),
        "starlette.routing": MagicMock(),
        "starlette.responses": MagicMock(),
        "starlette.websockets": MagicMock(),
    }
    for mod_name, mock_mod in mock_modules.items():
        if mod_name not in sys.modules:
            monkeypatch.setitem(sys.modules, mod_name, mock_mod)


def _make_retrieve_response(texts: list[str]) -> dict:
    """Build a mock retrieve_memory_records response."""
    return {
        "memoryRecordSummaries": [
            {"content": {"text": t}} for t in texts
        ]
    }


class TestLoadLtmContextMultiStrategy:
    """Test that _load_ltm_context queries all 4 strategies."""

    def test_returns_empty_when_no_memory_client(self):
        """No memory client → empty string."""
        import entrypoint

        with patch.object(entrypoint, "memory_client", None):
            result = entrypoint._load_ltm_context("user1", "hello")
        assert result == ""

    def test_returns_empty_when_no_memory_id(self):
        """Memory client exists but no memory_id → empty string."""
        import entrypoint

        mock_client = MagicMock()
        with (
            patch.object(entrypoint, "memory_client", mock_client),
            patch.object(entrypoint, "_get_memory_id", return_value=None),
        ):
            result = entrypoint._load_ltm_context("user1", "hello")
        assert result == ""

    def test_queries_all_four_strategies(self):
        """Should query preferences, summaries, knowledge, and episodes."""
        import entrypoint

        call_namespaces = []
        call_strategy_ids = []

        def mock_retrieve(memory_id, namespace, search_criteria):
            call_namespaces.append(namespace)
            call_strategy_ids.append(search_criteria.get("memoryStrategyId", ""))
            return _make_retrieve_response([])

        mock_client = MagicMock()
        mock_client.retrieve_memory_records = mock_retrieve

        with (
            patch.object(entrypoint, "memory_client", mock_client),
            patch.object(entrypoint, "_get_memory_id", return_value="mem-123"),
        ):
            entrypoint._load_ltm_context("user1", "help me with deployment")

        assert len(call_namespaces) == 4
        assert "/strategies/userPreferences/actors/user1/" in call_namespaces
        assert "/strategies/conversationSummary/actors/user1/" in call_namespaces
        assert "/strategies/semanticKnowledge/actors/user1/" in call_namespaces
        assert "/strategies/episodicMemory/actors/user1/" in call_namespaces

        # Verify strategy_id filters are passed
        assert "userPreferences" in call_strategy_ids
        assert "conversationSummary" in call_strategy_ids
        assert "semanticKnowledge" in call_strategy_ids
        assert "episodicMemory" in call_strategy_ids

    def test_uses_current_message_for_semantic_search(self):
        """Semantic and summary queries should use the current message."""
        import entrypoint

        search_queries = {}

        def mock_retrieve(memory_id, namespace, search_criteria):
            search_queries[namespace] = search_criteria["search_query"]
            return _make_retrieve_response([])

        mock_client = MagicMock()
        mock_client.retrieve_memory_records = mock_retrieve

        with (
            patch.object(entrypoint, "memory_client", mock_client),
            patch.object(entrypoint, "_get_memory_id", return_value="mem-123"),
        ):
            entrypoint._load_ltm_context("user1", "how do I deploy to AgentCore?")

        # Semantic and summary should use the actual user message
        sem_ns = "/strategies/semanticKnowledge/actors/user1/"
        sum_ns = "/strategies/conversationSummary/actors/user1/"
        assert search_queries[sem_ns] == "how do I deploy to AgentCore?"
        assert search_queries[sum_ns] == "how do I deploy to AgentCore?"

        # Preferences always use a fixed query
        pref_ns = "/strategies/userPreferences/actors/user1/"
        assert "preferences" in search_queries[pref_ns].lower()

    def test_formats_output_with_section_labels(self):
        """Results should be formatted with section labels."""
        import entrypoint

        call_count = 0

        def mock_retrieve(memory_id, namespace, search_criteria):
            nonlocal call_count
            call_count += 1
            if "userPreferences" in namespace:
                return _make_retrieve_response(["prefers serverless"])
            if "conversationSummary" in namespace:
                return _make_retrieve_response(["discussed deployment options"])
            if "semanticKnowledge" in namespace:
                return _make_retrieve_response(["AgentCore uses containers"])
            if "episodicMemory" in namespace:
                return _make_retrieve_response(["last session: reviewed code"])
            return _make_retrieve_response([])

        mock_client = MagicMock()
        mock_client.retrieve_memory_records = mock_retrieve

        with (
            patch.object(entrypoint, "memory_client", mock_client),
            patch.object(entrypoint, "_get_memory_id", return_value="mem-123"),
        ):
            result = entrypoint._load_ltm_context("user1", "help")

        assert "[User Preferences]" in result
        assert "prefers serverless" in result
        assert "[Previous Conversations]" in result
        assert "discussed deployment options" in result
        assert "[Relevant Knowledge]" in result
        assert "AgentCore uses containers" in result
        assert "[Past Interactions]" in result
        assert "last session: reviewed code" in result

    def test_graceful_on_partial_failure(self):
        """If one strategy fails, others should still return."""
        import entrypoint

        def mock_retrieve(memory_id, namespace, search_criteria):
            if "userPreferences" in namespace:
                raise Exception("connection timeout")
            if "semanticKnowledge" in namespace:
                return _make_retrieve_response(["important fact"])
            return _make_retrieve_response([])

        mock_client = MagicMock()
        mock_client.retrieve_memory_records = mock_retrieve

        with (
            patch.object(entrypoint, "memory_client", mock_client),
            patch.object(entrypoint, "_get_memory_id", return_value="mem-123"),
        ):
            result = entrypoint._load_ltm_context("user1", "hello")

        # Should still have knowledge despite preferences failing
        assert "[Relevant Knowledge]" in result
        assert "important fact" in result
        # Preferences section should not appear (failed)
        assert "[User Preferences]" not in result

    def test_fallback_query_when_no_current_message(self):
        """Without current_message, should use fallback queries."""
        import entrypoint

        search_queries = {}

        def mock_retrieve(memory_id, namespace, search_criteria):
            search_queries[namespace] = search_criteria["search_query"]
            return _make_retrieve_response([])

        mock_client = MagicMock()
        mock_client.retrieve_memory_records = mock_retrieve

        with (
            patch.object(entrypoint, "memory_client", mock_client),
            patch.object(entrypoint, "_get_memory_id", return_value="mem-123"),
        ):
            entrypoint._load_ltm_context("user1", "")

        # All queries should use fallback strings
        for ns, query in search_queries.items():
            assert len(query) > 0, f"Empty query for {ns}"
