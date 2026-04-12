"""Tests for Phase 5 — MemoryConfig wired from DomainHarness into memory hooks."""
from __future__ import annotations

import os
import tempfile

import pytest

from platform_agent.foundation.harness import DomainHarness, HookConfig, MemoryConfig
from platform_agent.foundation.hooks.memory_hook import MemoryHook
from platform_agent.foundation.hooks.memory_extraction_hook import MemoryExtractionHook
from platform_agent.foundation.hooks.consolidation_hook import ConsolidationHook
from platform_agent.foundation.agent import FoundationAgent


# ---------------------------------------------------------------------------
# Hook-level unit tests
# ---------------------------------------------------------------------------

class TestMemoryHookNamespace:
    def test_no_namespace_template_uses_workspace_dir_directly(self, tmp_path):
        """Default (empty namespace_template) leaves workspace_dir unchanged."""
        hook = MemoryHook(workspace_dir=str(tmp_path))
        assert hook.namespace == ""
        assert hook.workspace_memory.workspace_dir == str(tmp_path)

    def test_namespace_template_resolved_with_vars(self, tmp_path):
        """namespace_template is resolved with namespace_vars."""
        hook = MemoryHook(
            workspace_dir=str(tmp_path),
            namespace_template="{domain}/mem",
            namespace_vars={"domain": "billing"},
        )
        assert hook.namespace == "billing/mem"
        expected = os.path.join(str(tmp_path), "billing/mem")
        assert hook.workspace_memory.workspace_dir == expected

    def test_different_namespace_vars_produce_different_namespaces(self, tmp_path):
        """Two hooks with the same template but different vars get different paths."""
        hook_a = MemoryHook(
            workspace_dir=str(tmp_path),
            namespace_template="{domain}",
            namespace_vars={"domain": "alpha"},
        )
        hook_b = MemoryHook(
            workspace_dir=str(tmp_path),
            namespace_template="{domain}",
            namespace_vars={"domain": "beta"},
        )
        assert hook_a.namespace != hook_b.namespace
        assert hook_a.workspace_memory.workspace_dir != hook_b.workspace_memory.workspace_dir

    def test_ttl_days_stored(self):
        hook = MemoryHook(ttl_days=30)
        assert hook.ttl_days == 30

    def test_ttl_days_default_none(self):
        hook = MemoryHook()
        assert hook.ttl_days is None

    def test_missing_var_falls_back_to_template_literal(self, tmp_path):
        """If a placeholder var is missing, keep template as-is (no crash)."""
        hook = MemoryHook(
            workspace_dir=str(tmp_path),
            namespace_template="{agent_id}/mem",
            namespace_vars={},  # agent_id not supplied
        )
        # Should not crash; namespace retains the template string
        assert hook.namespace == "{agent_id}/mem"


class TestMemoryExtractionHookNamespace:
    def test_no_namespace_unchanged(self, tmp_path):
        hook = MemoryExtractionHook(workspace_dir=str(tmp_path))
        assert hook.namespace == ""
        assert hook.workspace_memory.workspace_dir == str(tmp_path)

    def test_namespace_template_applied(self, tmp_path):
        hook = MemoryExtractionHook(
            workspace_dir=str(tmp_path),
            namespace_template="agent/{agent_id}",
            namespace_vars={"agent_id": "bot-42"},
        )
        assert hook.namespace == "agent/bot-42"
        expected = os.path.join(str(tmp_path), "agent/bot-42")
        assert hook.workspace_memory.workspace_dir == expected

    def test_ttl_days_stored(self):
        hook = MemoryExtractionHook(ttl_days=7)
        assert hook.ttl_days == 7


class TestConsolidationHookNamespace:
    def test_no_namespace_unchanged(self, tmp_path):
        hook = ConsolidationHook(workspace_dir=str(tmp_path))
        assert hook.namespace == ""
        assert hook._workspace_dir == str(tmp_path)

    def test_namespace_template_applied(self, tmp_path):
        hook = ConsolidationHook(
            workspace_dir=str(tmp_path),
            namespace_template="{domain}/consolidation",
            namespace_vars={"domain": "payments"},
        )
        assert hook.namespace == "payments/consolidation"
        expected = os.path.join(str(tmp_path), "payments/consolidation")
        assert hook._workspace_dir == expected

    def test_ttl_days_stored(self):
        hook = ConsolidationHook(ttl_days=14)
        assert hook.ttl_days == 14


# ---------------------------------------------------------------------------
# FoundationAgent integration tests
# ---------------------------------------------------------------------------

class TestFoundationAgentHarnessNamespace:
    """FoundationAgent correctly wires harness.memory_config into hooks."""

    def _make_harness(self, domain: str, namespace_template: str, **mem_kwargs) -> DomainHarness:
        return DomainHarness(
            name=domain,
            memory_config=MemoryConfig(
                namespace_template=namespace_template,
                **mem_kwargs,
            ),
            hooks=[
                HookConfig(hook="MemoryHook", category="domain"),
                HookConfig(hook="MemoryExtractionHook", category="domain"),
                HookConfig(hook="ConsolidationHook", category="domain"),
            ],
        )

    def _get_hook(self, agent, hook_class):
        return next(
            (h for h in agent.hook_registry if isinstance(h, hook_class)),
            None,
        )

    def test_different_harnesses_produce_different_memory_hook_namespaces(self, tmp_path):
        """Two harnesses with different names produce different MemoryHook namespaces."""
        harness_a = self._make_harness("domain-a", "{domain}")
        harness_b = self._make_harness("domain-b", "{domain}")

        agent_a = FoundationAgent(workspace_dir=str(tmp_path), harness=harness_a)
        agent_b = FoundationAgent(workspace_dir=str(tmp_path), harness=harness_b)

        hook_a = self._get_hook(agent_a, MemoryHook)
        hook_b = self._get_hook(agent_b, MemoryHook)

        assert hook_a is not None
        assert hook_b is not None
        assert hook_a.namespace != hook_b.namespace
        assert hook_a.namespace == "domain-a"
        assert hook_b.namespace == "domain-b"

    def test_default_no_harness_behavior_unchanged(self, tmp_path):
        """Without a harness, memory_hook uses workspace_dir with no namespace."""
        agent = FoundationAgent(workspace_dir=str(tmp_path))
        assert agent.memory_hook.namespace == ""
        assert agent.memory_hook.workspace_memory.workspace_dir == str(tmp_path)

    def test_session_id_available_as_namespace_var(self, tmp_path):
        """session_id is available as {session_id} in namespace_template."""
        harness = self._make_harness("mybot", "{domain}/{session_id}")
        agent = FoundationAgent(
            workspace_dir=str(tmp_path),
            harness=harness,
            session_id="sess-abc",
        )
        hook = self._get_hook(agent, MemoryHook)
        assert hook is not None
        assert hook.namespace == "mybot/sess-abc"

    def test_ttl_days_propagated_to_extraction_hook(self, tmp_path):
        """ttl_days from MemoryConfig is stored on MemoryExtractionHook."""
        harness = self._make_harness("test-agent", "", ttl_days=45)
        agent = FoundationAgent(workspace_dir=str(tmp_path), harness=harness)
        hook = self._get_hook(agent, MemoryExtractionHook)
        assert hook is not None
        assert hook.ttl_days == 45

    def test_ttl_days_propagated_to_consolidation_hook(self, tmp_path):
        """ttl_days from MemoryConfig is stored on ConsolidationHook."""
        harness = self._make_harness("test-agent", "", ttl_days=60)
        agent = FoundationAgent(workspace_dir=str(tmp_path), harness=harness)
        hook = self._get_hook(agent, ConsolidationHook)
        assert hook is not None
        assert hook.ttl_days == 60

    def test_namespace_empty_when_no_namespace_template(self, tmp_path):
        """When namespace_template is empty, hooks use workspace_dir directly."""
        harness = DomainHarness(
            name="plain-agent",
            memory_config=MemoryConfig(namespace_template=""),
            hooks=[HookConfig(hook="MemoryHook", category="domain")],
        )
        agent = FoundationAgent(workspace_dir=str(tmp_path), harness=harness)
        hook = self._get_hook(agent, MemoryHook)
        assert hook is not None
        assert hook.namespace == ""
        assert hook.workspace_memory.workspace_dir == str(tmp_path)
