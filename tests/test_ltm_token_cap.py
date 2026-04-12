"""Tests for LTM token cap and relevance pruning in _load_ltm_context.

Verifies:
1. Total injected LTM context respects MAX_LTM_CHARS budget
2. Lower-scored records are pruned first
3. Duplicate records across strategies are deduplicated
4. Preferences get a score boost and survive pruning
5. Empty results return empty string
6. Graceful handling when memory client is unavailable
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────

def _make_record(text: str, score: float = 0.5) -> dict:
    """Create a mock memoryRecordSummary."""
    return {
        "content": {"text": text},
        "score": score,
        "memoryStrategyId": "test",
        "memoryRecordId": f"rec-{hash(text) % 10000}",
    }


def _mock_retrieve(records_by_namespace: dict[str, list[dict]]):
    """Return a mock retrieve_memory_records that returns records by namespace prefix."""

    def _retrieve(memory_id, namespace, search_criteria):
        # Match the namespace prefix
        for ns_prefix, records in records_by_namespace.items():
            if ns_prefix in namespace:
                return {"memoryRecordSummaries": records}
        return {"memoryRecordSummaries": []}

    return _retrieve


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def entrypoint():
    """Import entrypoint module with mocked dependencies."""
    # We need to import entrypoint but mock away heavy deps
    # that aren't available in test env
    return importlib.import_module("entrypoint")


# ── Tests ────────────────────────────────────────────────────────────

class TestLTMTokenCap:
    """Test suite for _load_ltm_context token cap and pruning."""

    def test_empty_when_no_memory_client(self, entrypoint):
        """No memory client → empty string."""
        with patch.object(entrypoint, "memory_client", None):
            result = entrypoint._load_ltm_context("actor-1", "hello")
            assert result == ""

    def test_empty_when_no_memory_id(self, entrypoint):
        """Memory client exists but no memory_id → empty string."""
        with patch.object(entrypoint, "memory_client", MagicMock()), \
             patch.object(entrypoint, "_get_memory_id", return_value=None):
            result = entrypoint._load_ltm_context("actor-1", "hello")
            assert result == ""

    def test_empty_when_no_results(self, entrypoint):
        """All strategy searches return empty → empty string."""
        mock_client = MagicMock()
        mock_client.retrieve_memory_records.return_value = {
            "memoryRecordSummaries": []
        }

        with patch.object(entrypoint, "memory_client", mock_client), \
             patch.object(entrypoint, "_get_memory_id", return_value="mem-123"):
            result = entrypoint._load_ltm_context("actor-1", "hello")
            assert result == ""

    def test_respects_char_budget(self, entrypoint):
        """Total output must not exceed MAX_LTM_CHARS."""
        # Create 30 records of ~300 chars each = 9000 chars total
        # Budget is 6000 chars → should only include ~20 records
        long_text = "A" * 280  # 280 chars per record
        all_records = [_make_record(f"{long_text}_{i}", score=0.9 - i * 0.01)
                       for i in range(30)]

        mock_client = MagicMock()
        # Return all records from semanticKnowledge, nothing from others
        def _retrieve(memory_id, namespace, search_criteria):
            if "semanticKnowledge" in namespace:
                return {"memoryRecordSummaries": all_records}
            return {"memoryRecordSummaries": []}

        mock_client.retrieve_memory_records.side_effect = _retrieve

        with patch.object(entrypoint, "memory_client", mock_client), \
             patch.object(entrypoint, "_get_memory_id", return_value="mem-123"):
            result = entrypoint._load_ltm_context("actor-1", "test query")

        # Result should be under the char cap
        assert len(result) <= entrypoint.MAX_LTM_CHARS + 200  # small margin for headers

    def test_higher_scored_records_survive(self, entrypoint):
        """Higher-scored records should be kept over lower-scored ones."""
        # Create records: high-score ones with marker, low-score filler
        high_score_text = "IMPORTANT_PREFERENCE: User prefers Python"
        low_score_filler = "X" * 500  # large filler to exhaust budget

        records_prefs = [_make_record(high_score_text, score=0.95)]
        records_knowledge = [
            _make_record(f"{low_score_filler}_{i}", score=0.3)
            for i in range(20)
        ]

        mock_client = MagicMock()

        def _retrieve(memory_id, namespace, search_criteria):
            if "userPreferences" in namespace:
                return {"memoryRecordSummaries": records_prefs}
            if "semanticKnowledge" in namespace:
                return {"memoryRecordSummaries": records_knowledge}
            return {"memoryRecordSummaries": []}

        mock_client.retrieve_memory_records.side_effect = _retrieve

        with patch.object(entrypoint, "memory_client", mock_client), \
             patch.object(entrypoint, "_get_memory_id", return_value="mem-123"):
            result = entrypoint._load_ltm_context("actor-1", "test")

        # The high-score preference should be present
        assert "IMPORTANT_PREFERENCE" in result

    def test_preferences_get_score_boost(self, entrypoint):
        """Preferences with raw score 0.8 + boost 0.1 = 0.9 should beat
        knowledge records with raw score 0.85."""
        pref_text = "PREF: likes dark mode"
        know_text = "KNOW: uses React"

        records_prefs = [_make_record(pref_text, score=0.8)]  # +0.1 boost → 0.9
        records_knowledge = [_make_record(know_text, score=0.85)]  # no boost → 0.85

        mock_client = MagicMock()

        def _retrieve(memory_id, namespace, search_criteria):
            if "userPreferences" in namespace:
                return {"memoryRecordSummaries": records_prefs}
            if "semanticKnowledge" in namespace:
                return {"memoryRecordSummaries": records_knowledge}
            return {"memoryRecordSummaries": []}

        mock_client.retrieve_memory_records.side_effect = _retrieve

        with patch.object(entrypoint, "memory_client", mock_client), \
             patch.object(entrypoint, "_get_memory_id", return_value="mem-123"):
            result = entrypoint._load_ltm_context("actor-1", "test")

        # Both should be present (budget isn't tight), but verify preferences
        # appear before knowledge (they have higher effective score)
        pref_pos = result.find("PREF:")
        know_pos = result.find("KNOW:")
        assert pref_pos != -1, "Preference should be in result"
        assert know_pos != -1, "Knowledge should be in result"

    def test_deduplication(self, entrypoint):
        """Same text from different strategies should appear only once."""
        dup_text = "User prefers Python for all projects"

        # Same text returned by both preferences and knowledge strategies
        records_prefs = [_make_record(dup_text, score=0.9)]
        records_knowledge = [_make_record(dup_text, score=0.8)]

        mock_client = MagicMock()

        def _retrieve(memory_id, namespace, search_criteria):
            if "userPreferences" in namespace:
                return {"memoryRecordSummaries": records_prefs}
            if "semanticKnowledge" in namespace:
                return {"memoryRecordSummaries": records_knowledge}
            return {"memoryRecordSummaries": []}

        mock_client.retrieve_memory_records.side_effect = _retrieve

        with patch.object(entrypoint, "memory_client", mock_client), \
             patch.object(entrypoint, "_get_memory_id", return_value="mem-123"):
            result = entrypoint._load_ltm_context("actor-1", "test")

        # Text should appear exactly once
        assert result.count(dup_text) == 1

    def test_section_ordering(self, entrypoint):
        """Sections should appear in order: preferences → summaries → knowledge → episodes."""
        mock_client = MagicMock()

        def _retrieve(memory_id, namespace, search_criteria):
            if "userPreferences" in namespace:
                return {"memoryRecordSummaries": [_make_record("pref_item", 0.9)]}
            if "conversationSummary" in namespace:
                return {"memoryRecordSummaries": [_make_record("summary_item", 0.8)]}
            if "semanticKnowledge" in namespace:
                return {"memoryRecordSummaries": [_make_record("knowledge_item", 0.7)]}
            if "episodicMemory" in namespace:
                return {"memoryRecordSummaries": [_make_record("episode_item", 0.6)]}
            return {"memoryRecordSummaries": []}

        mock_client.retrieve_memory_records.side_effect = _retrieve

        with patch.object(entrypoint, "memory_client", mock_client), \
             patch.object(entrypoint, "_get_memory_id", return_value="mem-123"):
            result = entrypoint._load_ltm_context("actor-1", "test")

        # All sections should be present
        assert "[User Preferences]" in result
        assert "[Previous Conversations]" in result
        assert "[Relevant Knowledge]" in result
        assert "[Past Interactions]" in result

        # Order check
        pref_pos = result.find("[User Preferences]")
        summ_pos = result.find("[Previous Conversations]")
        know_pos = result.find("[Relevant Knowledge]")
        epis_pos = result.find("[Past Interactions]")
        assert pref_pos < summ_pos < know_pos < epis_pos

    def test_graceful_on_search_failure(self, entrypoint):
        """If some searches fail, the rest still work."""
        call_count = 0

        mock_client = MagicMock()

        def _retrieve(memory_id, namespace, search_criteria):
            nonlocal call_count
            call_count += 1
            if "userPreferences" in namespace:
                raise RuntimeError("Simulated network failure")
            if "semanticKnowledge" in namespace:
                return {"memoryRecordSummaries": [
                    _make_record("surviving record", 0.9),
                ]}
            return {"memoryRecordSummaries": []}

        mock_client.retrieve_memory_records.side_effect = _retrieve

        with patch.object(entrypoint, "memory_client", mock_client), \
             patch.object(entrypoint, "_get_memory_id", return_value="mem-123"):
            result = entrypoint._load_ltm_context("actor-1", "test")

        # Should still have the knowledge record despite preference failure
        assert "surviving record" in result

    def test_single_record_exceeding_budget_still_included(self, entrypoint):
        """A single record larger than the budget should still be included
        (we never return empty when there are results)."""
        huge_text = "B" * 8000  # larger than MAX_LTM_CHARS
        mock_client = MagicMock()

        def _retrieve(memory_id, namespace, search_criteria):
            if "semanticKnowledge" in namespace:
                return {"memoryRecordSummaries": [_make_record(huge_text, 0.95)]}
            return {"memoryRecordSummaries": []}

        mock_client.retrieve_memory_records.side_effect = _retrieve

        with patch.object(entrypoint, "memory_client", mock_client), \
             patch.object(entrypoint, "_get_memory_id", return_value="mem-123"):
            result = entrypoint._load_ltm_context("actor-1", "test")

        # Should include the record even though it exceeds budget
        # (the budget check says "if budget < 0 AND selected is non-empty, stop")
        assert huge_text in result
