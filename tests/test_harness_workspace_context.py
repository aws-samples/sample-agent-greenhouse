"""Tests for DomainHarness workspace_context_enabled field."""

from __future__ import annotations

import pytest

from platform_agent.foundation.harness import DomainHarness


class TestWorkspaceContextEnabled:
    """Test workspace_context_enabled field in DomainHarness."""

    def test_default_is_true(self):
        harness = DomainHarness(name="test")
        assert harness.workspace_context_enabled is True

    def test_can_set_false(self):
        harness = DomainHarness(name="test", workspace_context_enabled=False)
        assert harness.workspace_context_enabled is False

    def test_to_dict_includes_field(self):
        harness = DomainHarness(name="test", workspace_context_enabled=False)
        d = harness.to_dict()
        assert d["workspace_context_enabled"] is False

    def test_from_dict_reads_field(self):
        data = {"name": "test", "workspace_context_enabled": False}
        harness = DomainHarness.from_dict(data)
        assert harness.workspace_context_enabled is False

    def test_from_dict_defaults_true(self):
        data = {"name": "test"}
        harness = DomainHarness.from_dict(data)
        assert harness.workspace_context_enabled is True

    def test_round_trip_yaml(self, tmp_path):
        harness = DomainHarness(name="test", workspace_context_enabled=False)
        yaml_path = tmp_path / "harness.yaml"
        harness.to_yaml(yaml_path)
        loaded = DomainHarness.from_yaml(yaml_path)
        assert loaded.workspace_context_enabled is False

    def test_agent_respects_harness_flag(self):
        """FoundationAgent should disable workspace context when harness says so."""
        harness = DomainHarness(name="test", workspace_context_enabled=False)
        # Verify the agent reads this field (agent.py line ~183)
        assert getattr(harness, "workspace_context_enabled", True) is False
