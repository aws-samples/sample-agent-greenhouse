"""Tests for scripts/setup_memory.py — IaC strategy setup."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.setup_memory import (
    STRATEGIES,
    create_strategies,
    verify_strategies,
)


@pytest.fixture
def mock_boto3_client():
    """Create a mock boto3 bedrock-agentcore-control client."""
    client = MagicMock()
    client.update_memory.return_value = {}
    client.get_memory.return_value = {
        "memoryStrategies": [
            {"name": "semanticKnowledge", "type": "Semantic", "memoryStrategyId": "s-1"},
            {"name": "conversationSummary", "type": "Summary", "memoryStrategyId": "s-2"},
            {"name": "userPreferences", "type": "UserPreference", "memoryStrategyId": "s-3"},
            {"name": "episodicMemory", "type": "Episodic", "memoryStrategyId": "s-4"},
        ]
    }
    # Must be a real exception class so `except client.exceptions.ValidationException` works
    client.exceptions.ValidationException = type(
        "ValidationException", (Exception,), {}
    )
    return client


@pytest.fixture
def mock_boto3(mock_boto3_client):
    """Mock boto3 module so that boto3.client() returns our mock client."""
    mock_module = MagicMock()
    mock_module.client.return_value = mock_boto3_client
    with patch.dict(sys.modules, {"boto3": mock_module}):
        yield mock_module


class TestCreateStrategies:
    def test_creates_all_four_strategies(self, mock_boto3, mock_boto3_client):
        """All 4 strategies should be created via update_memory."""
        results = create_strategies("mem-test", "us-west-2")

        assert len(results) == 4
        assert results["Semantic"] == "created"
        assert results["Summary"] == "created"
        assert results["UserPreference"] == "created"
        assert results["Episodic"] == "created"
        assert mock_boto3_client.update_memory.call_count == 4

    def test_idempotent_existing_strategy(self, mock_boto3, mock_boto3_client):
        """If a strategy already exists, it should be marked as 'exists' not fail."""
        mock_boto3_client.update_memory.side_effect = [
            {},  # Semantic succeeds
            mock_boto3_client.exceptions.ValidationException("Strategy already exists"),
            {},  # UserPreference succeeds
            {},  # Episodic succeeds
        ]

        results = create_strategies("mem-test", "us-west-2")

        assert results["Semantic"] == "created"
        assert results["Summary"] == "exists"
        assert results["UserPreference"] == "created"
        assert results["Episodic"] == "created"

    def test_dry_run_no_api_calls(self, mock_boto3, mock_boto3_client):
        """Dry run should not make any API calls."""
        results = create_strategies("mem-test", "us-west-2", dry_run=True)

        mock_boto3_client.update_memory.assert_not_called()
        assert all(v == "dry_run" for v in results.values())

    def test_handles_generic_failure(self, mock_boto3, mock_boto3_client):
        """Generic exceptions should be caught and reported as failed."""
        mock_boto3_client.update_memory.side_effect = RuntimeError("Network error")

        results = create_strategies("mem-test", "us-west-2")

        for label in ["Semantic", "Summary", "UserPreference", "Episodic"]:
            assert results[label].startswith("failed:")

    def test_strategies_have_correct_namespaces(self):
        """Verify strategies use correct namespace patterns."""
        for label, strategy_config in STRATEGIES:
            strategy_key = list(strategy_config.keys())[0]
            strategy_body = strategy_config[strategy_key]
            namespaces = strategy_body["namespaces"]
            assert len(namespaces) >= 1

            ns = namespaces[0]
            assert "{memoryStrategyId}" in ns
            assert "{actorId}" in ns

            if label == "Summary":
                assert "{sessionId}" in ns


class TestVerifyStrategies:
    def test_verify_returns_strategy_info(self, mock_boto3, mock_boto3_client):
        """verify_strategies should return strategy info from get_memory."""
        info = verify_strategies("mem-test", "us-west-2")

        assert len(info) == 4
        assert info[0]["name"] == "semanticKnowledge"
        assert info[0]["type"] == "Semantic"
        assert info[0]["id"] == "s-1"

    def test_verify_handles_error(self, mock_boto3, mock_boto3_client):
        """verify_strategies should handle errors gracefully."""
        mock_boto3_client.get_memory.side_effect = RuntimeError("Not found")

        info = verify_strategies("mem-test", "us-west-2")

        assert info == []
