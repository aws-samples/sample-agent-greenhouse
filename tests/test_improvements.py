"""Tests for the 7 CC-inspired improvements.

Tests each improvement independently:
1. Memory Extraction Hook
2. Consolidation Hook (three-trigger gate)
3. Structured Compaction (9-section pattern)
4. Evaluator Deterministic Checks + Honesty Preamble
5. Orchestrator Never Delegate Understanding
6. Prompt Cache Awareness
7. Enhanced Namespace Isolation in Memory
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Improvement 1: Memory Extraction Hook
# ---------------------------------------------------------------------------


class TestMemoryExtractionHook:
    """Tests for the AfterInvocationEvent-based memory extraction."""

    def test_hook_initializes_without_workspace(self):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        hook = MemoryExtractionHook()
        assert hook.workspace_memory is None
        assert hook.get_extracted_memories() == []

    def test_hook_initializes_with_workspace(self, tmp_path):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        hook = MemoryExtractionHook(workspace_dir=str(tmp_path))
        assert hook.workspace_memory is not None

    def test_extracts_decision_from_result_text(self):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        hook = MemoryExtractionHook()
        event = MagicMock()
        event.result = "We decided to use PostgreSQL for the database."
        hook.on_after_invocation(event)
        memories = hook.get_extracted_memories()
        assert len(memories) >= 1
        assert memories[0]["type"] == "decision"
        assert "PostgreSQL" in memories[0]["content"]

    def test_extracts_from_dict_result(self):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        hook = MemoryExtractionHook()
        event = MagicMock()
        event.result = {
            "content": [
                {"text": "Decision: We'll go with React for the frontend."}
            ]
        }
        hook.on_after_invocation(event)
        memories = hook.get_extracted_memories()
        assert len(memories) >= 1

    def test_no_extraction_on_empty_result(self):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        hook = MemoryExtractionHook()
        event = MagicMock()
        event.result = None
        hook.on_after_invocation(event)
        assert hook.get_extracted_memories() == []

    def test_custom_extraction_callback(self):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        def custom_extractor(text):
            return [{"type": "fact", "content": f"Extracted: {text[:20]}"}]

        hook = MemoryExtractionHook(extraction_callback=custom_extractor)
        event = MagicMock()
        event.result = "Some conversation content"
        hook.on_after_invocation(event)
        memories = hook.get_extracted_memories()
        assert len(memories) == 1
        assert memories[0]["type"] == "fact"
        assert "Extracted:" in memories[0]["content"]

    def test_clear_memories(self):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        hook = MemoryExtractionHook()
        event = MagicMock()
        event.result = "We decided to use Go."
        hook.on_after_invocation(event)
        assert len(hook.get_extracted_memories()) >= 1
        hook.clear()
        assert hook.get_extracted_memories() == []

    def test_persists_memories_to_workspace(self, tmp_path):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        hook = MemoryExtractionHook(workspace_dir=str(tmp_path))
        event = MagicMock()
        event.result = "We decided to use Rust."
        hook.on_after_invocation(event)
        # Check that files were written
        memory_dir = tmp_path / "memory" / "extracted"
        assert memory_dir.exists()
        files = list(memory_dir.glob("*.json"))
        assert len(files) >= 1

    def test_extraction_prompt_is_available(self):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        prompt = MemoryExtractionHook.get_extraction_prompt()
        assert "Extract key facts" in prompt
        assert "JSON" in prompt

    def test_register_hooks_adds_callback(self):
        from platform_agent.foundation.hooks.memory_extraction_hook import (
            MemoryExtractionHook,
        )

        hook = MemoryExtractionHook()
        registry = MagicMock()
        hook.register_hooks(registry)
        # Should have called add_callback
        registry.add_callback.assert_called_once()


# ---------------------------------------------------------------------------
# Improvement 2: Consolidation Hook (three-trigger gate)
# ---------------------------------------------------------------------------


class TestConsolidationHook:
    """Tests for the three-trigger-gate memory consolidation."""

    def test_hook_initializes_with_defaults(self):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        hook = ConsolidationHook()
        state = hook.get_state()
        assert state["last_consolidation_timestamp"] == 0
        assert state["events_since_last"] == 0

    def test_time_gate_blocks_when_recent(self, tmp_path):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        hook = ConsolidationHook(workspace_dir=str(tmp_path))
        # Set last consolidation to now
        hook._state["last_consolidation_timestamp"] = time.time()
        hook._event_count_since_last = 100  # plenty of events
        assert hook._should_consolidate() is False

    def test_count_gate_blocks_when_few_events(self, tmp_path):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        hook = ConsolidationHook(workspace_dir=str(tmp_path))
        # Old timestamp (> 24h ago) but few events
        hook._state["last_consolidation_timestamp"] = 0
        hook._event_count_since_last = 2
        hook._state["events_since_last"] = 0
        assert hook._should_consolidate() is False

    def test_all_gates_pass(self, tmp_path):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        hook = ConsolidationHook(
            workspace_dir=str(tmp_path),
            time_gate_seconds=0,  # no time gate
            count_gate=1,  # low count gate
        )
        hook._state["last_consolidation_timestamp"] = 0
        hook._event_count_since_last = 5
        hook._state["events_since_last"] = 0
        assert hook._should_consolidate() is True

    def test_on_before_invocation_increments_count(self):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        hook = ConsolidationHook(time_gate_seconds=999999)
        event = MagicMock()
        hook.on_before_invocation(event)
        assert hook._event_count_since_last == 1
        hook.on_before_invocation(event)
        assert hook._event_count_since_last == 2

    def test_consolidation_with_callback(self, tmp_path):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        def mock_consolidate(memories):
            return "Consolidated: " + ", ".join(memories)

        hook = ConsolidationHook(
            workspace_dir=str(tmp_path),
            consolidation_callback=mock_consolidate,
        )
        result = hook._consolidate(["fact1", "fact2"])
        assert result == "Consolidated: fact1, fact2"

    def test_consolidation_fallback_without_callback(self, tmp_path):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        hook = ConsolidationHook(workspace_dir=str(tmp_path))
        result = hook._consolidate(["insight1", "insight2"])
        assert "Consolidated insights:" in result
        assert "insight1" in result
        assert "insight2" in result

    def test_lock_acquisition(self, tmp_path):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        hook = ConsolidationHook(workspace_dir=str(tmp_path))
        assert hook._acquire_lock() is True
        # Second acquisition should fail (lock exists and is fresh)
        assert hook._acquire_lock() is False
        hook._release_lock()
        # After release, should succeed again
        assert hook._acquire_lock() is True

    def test_increment_event_count(self):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        hook = ConsolidationHook()
        assert hook._event_count_since_last == 0
        hook.increment_event_count()
        assert hook._event_count_since_last == 1

    def test_register_hooks_adds_callback(self):
        from platform_agent.foundation.hooks.consolidation_hook import (
            ConsolidationHook,
        )

        hook = ConsolidationHook()
        registry = MagicMock()
        hook.register_hooks(registry)
        registry.add_callback.assert_called_once()


# ---------------------------------------------------------------------------
# Improvement 3: Structured Compaction (9-section pattern)
# ---------------------------------------------------------------------------


class TestStructuredCompaction:
    """Tests for the 9-section compaction prompt."""

    def test_compaction_prompt_has_9_sections(self):
        from platform_agent.foundation.hooks.compaction_hook import (
            COMPACTION_PROMPT,
        )

        for i in range(1, 10):
            assert f"## {i}." in COMPACTION_PROMPT

    def test_compaction_prompt_preserves_user_messages(self):
        from platform_agent.foundation.hooks.compaction_hook import (
            COMPACTION_PROMPT,
        )

        assert "IRON RULE" in COMPACTION_PROMPT
        assert "Never summarize" in COMPACTION_PROMPT or "never summarize" in COMPACTION_PROMPT.lower()

    def test_section_names_returns_9(self):
        from platform_agent.foundation.hooks.compaction_hook import (
            CompactionHook,
        )

        sections = CompactionHook.get_section_names()
        assert len(sections) == 9
        assert "System Context Summary" in sections
        assert "User Messages (Verbatim)" in sections
        assert "Next Steps" in sections

    def test_max_compaction_tokens(self):
        from platform_agent.foundation.hooks.compaction_hook import (
            MAX_COMPACTION_TOKENS,
        )

        assert MAX_COMPACTION_TOKENS == 20000

    def test_system_prompt_reserve(self):
        from platform_agent.foundation.hooks.compaction_hook import (
            SYSTEM_PROMPT_TOKEN_RESERVE,
        )

        assert SYSTEM_PROMPT_TOKEN_RESERVE == 15000

    def test_flush_logs_warning_no_injection(self):
        """v1: CompactionHook logs warning instead of injecting messages."""
        from platform_agent.foundation.hooks.compaction_hook import (
            CompactionHook,
        )

        hook = CompactionHook(token_threshold=100)
        mock_session = MagicMock()
        mock_session.estimate_tokens.return_value = 200
        hook.session_memory = mock_session

        event = MagicMock()
        event.messages = []
        hook.on_before_invocation(event)

        # v1: no message injection, only warning log + _flush_triggered
        assert len(event.messages) == 0
        assert hook._flush_triggered

    def test_get_compaction_prompt_static_method(self):
        from platform_agent.foundation.hooks.compaction_hook import (
            CompactionHook,
        )

        prompt = CompactionHook.get_compaction_prompt()
        assert "## 1." in prompt
        assert "## 9." in prompt


# ---------------------------------------------------------------------------
# Improvement 4: Evaluator Deterministic Checks + Honesty Preamble
# ---------------------------------------------------------------------------


class TestEvaluatorImprovements:
    """Tests for honesty preamble and deterministic checks."""

    def test_honesty_preamble_exists(self):
        from platform_agent.plato.evaluator.base import HONESTY_PREAMBLE

        assert "independent evaluator" in HONESTY_PREAMBLE
        assert "false pass" in HONESTY_PREAMBLE

    def test_honesty_preamble_in_base_eval_prompt(self):
        from platform_agent.plato.evaluator.base import (
            EvaluationRubric,
            EvaluatorAgent,
            HONESTY_PREAMBLE,
            RubricItem,
        )

        rubric = EvaluationRubric(
            name="test",
            version="1.0",
            items=[RubricItem(id="q", name="Q", description="quality")],
        )
        agent = EvaluatorAgent(rubric=rubric)
        prompt = agent.build_evaluation_prompt("output", "request", 1)
        assert HONESTY_PREAMBLE in prompt

    def test_honesty_preamble_in_code_review_prompt(self):
        from platform_agent.plato.evaluator.code_review import CodeReviewEvaluator
        from platform_agent.plato.evaluator.base import HONESTY_PREAMBLE

        evaluator = CodeReviewEvaluator()
        prompt = evaluator.build_evaluation_prompt("output", "request", 1)
        assert HONESTY_PREAMBLE in prompt

    def test_honesty_preamble_in_design_prompt(self):
        from platform_agent.plato.evaluator.design import DesignEvaluator
        from platform_agent.plato.evaluator.base import HONESTY_PREAMBLE

        evaluator = DesignEvaluator()
        prompt = evaluator.build_evaluation_prompt("output", "request", 1)
        assert HONESTY_PREAMBLE in prompt

    def test_honesty_preamble_in_scaffold_prompt(self):
        from platform_agent.plato.evaluator.scaffold import ScaffoldEvaluator
        from platform_agent.plato.evaluator.base import HONESTY_PREAMBLE

        evaluator = ScaffoldEvaluator()
        prompt = evaluator.build_evaluation_prompt("output", "request", 1)
        assert HONESTY_PREAMBLE in prompt

    def test_honesty_preamble_in_deployment_prompt(self):
        from platform_agent.plato.evaluator.deployment import DeployConfigEvaluator
        from platform_agent.plato.evaluator.base import HONESTY_PREAMBLE

        evaluator = DeployConfigEvaluator()
        prompt = evaluator.build_evaluation_prompt("output", "request", 1)
        assert HONESTY_PREAMBLE in prompt

    def test_deterministic_checks_base_returns_empty(self):
        from platform_agent.plato.evaluator.base import EvaluatorAgent

        agent = EvaluatorAgent()
        result = agent.deterministic_checks("output", "request")
        assert result == {}

    def test_code_review_deterministic_checks_structure(self):
        from platform_agent.plato.evaluator.code_review import CodeReviewEvaluator

        evaluator = CodeReviewEvaluator()
        # Deterministic checks should return a dict
        result = evaluator.deterministic_checks("output mentioning ruff", "request")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_evaluate_once_merges_deterministic_results(self):
        from platform_agent.plato.evaluator.base import (
            EvaluationRubric,
            EvaluatorAgent,
            ItemScore,
            RubricItem,
        )

        rubric = EvaluationRubric(
            name="test",
            version="1.0",
            items=[
                RubricItem(id="a", name="A", description="check a"),
                RubricItem(id="b", name="B", description="check b"),
            ],
        )

        class TestEvaluator(EvaluatorAgent):
            def deterministic_checks(self, output, request):
                return {
                    "a": ItemScore(
                        rubric_item_id="a",
                        score=1.0,
                        passed=True,
                        evidence="Deterministic pass",
                    )
                }

        evaluator = TestEvaluator(rubric=rubric)
        result = await evaluator.evaluate_once("output", "request", 1)
        # Item "a" should have deterministic score of 1.0
        a_score = next(s for s in result.item_scores if s.rubric_item_id == "a")
        assert a_score.score == 1.0
        assert a_score.evidence == "Deterministic pass"

    def test_deployment_deterministic_validates_json(self):
        from platform_agent.plato.evaluator.deployment import DeployConfigEvaluator

        evaluator = DeployConfigEvaluator()

        # Valid IAM policy JSON
        valid_output = '```json\n{"Statement": [{"Effect": "Allow", "Action": "s3:GetObject"}]}\n```'
        result = evaluator.deterministic_checks(valid_output, "request")
        assert "iam_least_privilege" in result
        assert result["iam_least_privilege"].score > 0

    def test_deployment_deterministic_catches_invalid_json(self):
        from platform_agent.plato.evaluator.deployment import DeployConfigEvaluator

        evaluator = DeployConfigEvaluator()

        # Invalid JSON
        invalid_output = '```json\n{"Statement": [{"Effect": "Allow", "Action": ]\n```'
        result = evaluator.deterministic_checks(invalid_output, "request")
        if "iam_least_privilege" in result:
            assert result["iam_least_privilege"].score < 0.5


# ---------------------------------------------------------------------------
# Improvement 5: Orchestrator Never Delegate Understanding
# ---------------------------------------------------------------------------


class TestOrchestratorImprovements:
    """Tests for the orchestrator's NEVER DELEGATE UNDERSTANDING principle."""

    def test_prompt_includes_never_delegate(self):
        from platform_agent.plato.orchestrator import build_orchestrator_prompt

        prompt = build_orchestrator_prompt({})
        assert "NEVER DELEGATE UNDERSTANDING" in prompt

    def test_prompt_includes_verification_step(self):
        from platform_agent.plato.orchestrator import build_orchestrator_prompt

        prompt = build_orchestrator_prompt({})
        assert "Verification" in prompt or "verify" in prompt.lower()

    def test_prompt_includes_architect_principle(self):
        from platform_agent.plato.orchestrator import build_orchestrator_prompt

        prompt = build_orchestrator_prompt({})
        assert "architect" in prompt.lower()
        assert "dispatcher" in prompt.lower()

    def test_specialist_tools_exclude_task(self):
        from platform_agent.plato.orchestrator import skillpack_to_agent_definition

        class MockSkill:
            description = "Test skill"
            system_prompt_extension = "Do things"
            tools = ["Read", "Write", "Task", "Grep"]

        agent_def = skillpack_to_agent_definition(MockSkill())
        assert "Task" not in agent_def.tools
        assert "Read" in agent_def.tools
        assert "Write" in agent_def.tools
        assert "Grep" in agent_def.tools

    def test_specialist_tools_preserve_non_denied(self):
        from platform_agent.plato.orchestrator import skillpack_to_agent_definition

        class MockSkill:
            description = "Test skill"
            system_prompt_extension = "Do things"
            tools = ["Read", "Write"]

        agent_def = skillpack_to_agent_definition(MockSkill())
        assert len(agent_def.tools) == 2


# ---------------------------------------------------------------------------
# Improvement 6: Prompt Cache Awareness
# ---------------------------------------------------------------------------


class TestPromptCacheAwareness:
    """Tests for static/dynamic prompt separation and hash tracking."""

    def test_system_prompt_is_stable_across_calls(self):
        from platform_agent.foundation.agent import (
            FoundationStrandsAgent,
        )

        agent = FoundationStrandsAgent()
        prompt1 = agent.build_system_prompt()
        prompt2 = agent.build_system_prompt()
        assert prompt1 == prompt2

    def test_prompt_hash_is_set_after_build(self):
        from platform_agent.foundation.agent import (
            FoundationStrandsAgent,
        )

        agent = FoundationStrandsAgent()
        assert agent._prompt_hash == ""
        agent.build_system_prompt()
        assert agent._prompt_hash != ""
        assert len(agent._prompt_hash) == 16

    def test_prompt_hash_changes_when_content_changes(self, tmp_path):
        from platform_agent.foundation.agent import (
            FoundationStrandsAgent,
        )

        (tmp_path / "SOUL.md").write_text("Version 1")
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        agent.build_system_prompt()
        hash1 = agent._prompt_hash

        (tmp_path / "SOUL.md").write_text("Version 2")
        agent.soul_system._load_all()
        agent.build_system_prompt()
        hash2 = agent._prompt_hash

        assert hash1 != hash2

    def test_prompt_no_longer_contains_dynamic_timestamp(self):
        from platform_agent.foundation.agent import (
            FoundationStrandsAgent,
        )
        import re

        agent = FoundationStrandsAgent()
        prompt = agent.build_system_prompt()
        # Should not contain an actual ISO timestamp (e.g., 2026-03-31T21:18:32)
        # but may contain static text about "Current Time"
        iso_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        assert not re.search(iso_pattern, prompt), "System prompt should not contain dynamic ISO timestamps"

    def test_dynamic_context_contains_timestamp(self):
        from platform_agent.foundation.agent import (
            FoundationStrandsAgent,
        )

        agent = FoundationStrandsAgent()
        ctx = agent._build_dynamic_context()
        assert "Current date and time" in ctx
        assert "UTC" in ctx

    def test_prompt_hash_logs_warning_on_change(self, tmp_path, caplog):
        import logging
        from platform_agent.foundation.agent import (
            FoundationStrandsAgent,
        )

        (tmp_path / "SOUL.md").write_text("V1")
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        agent.build_system_prompt()

        (tmp_path / "SOUL.md").write_text("V2")
        agent.soul_system._load_all()
        with caplog.at_level(logging.WARNING):
            agent.build_system_prompt()
        assert "System prompt changed" in caplog.text

    def test_new_hooks_opt_in(self):
        from platform_agent.foundation.agent import (
            FoundationStrandsAgent,
        )

        # Default: 10 hooks (CompactionHook + StmIngestionHook removed from active registry)
        agent = FoundationStrandsAgent()
        assert len(agent.hook_registry) == 10

        # With extraction and consolidation enabled: 12 hooks
        agent2 = FoundationStrandsAgent(
            enable_memory_extraction=True,
            enable_consolidation=True,
        )
        assert len(agent2.hook_registry) == 12


# ---------------------------------------------------------------------------
# Improvement 7: Enhanced Namespace Isolation in Memory
# ---------------------------------------------------------------------------


class TestNamespaceIsolation:
    """Tests for structured namespace isolation in AgentCore Memory."""

    def test_build_session_namespace(self):
        from platform_agent.memory import build_session_namespace

        ns = build_session_namespace("user-123", "sess-456")
        assert ns == "/teams/user-123/sessions/sess-456/"

    def test_build_consolidation_namespace(self):
        from platform_agent.memory import build_consolidation_namespace

        ns = build_consolidation_namespace("user-123")
        assert ns == "/teams/user-123/consolidated/"

    def test_build_actor_namespace(self):
        from platform_agent.memory import build_actor_namespace

        ns = build_actor_namespace("user-123")
        assert ns == "/teams/user-123/"

    def test_build_legacy_namespace(self):
        from platform_agent.memory import build_legacy_namespace

        ns = build_legacy_namespace("user-123")
        assert ns == "/actors/user-123/"

    def test_local_memory_still_works(self):
        from platform_agent.memory import LocalMemory

        mem = LocalMemory()
        eid = mem.add_user_message("user1", "sess1", "hello")
        assert eid is not None
        history = mem.get_conversation_history("user1", "sess1")
        assert len(history) == 1
        assert history[0].text == "hello"

    def test_local_memory_search_with_actor_filter(self):
        from platform_agent.memory import LocalMemory

        mem = LocalMemory()
        mem.add_user_message("user1", "sess1", "python programming")
        mem.add_user_message("user2", "sess2", "python is great")

        # Search with actor filter
        results = mem.search_long_term("python", actor_id="user1")
        assert len(results) == 1
        assert results[0].text == "python programming"

    def test_namespace_helpers_import(self):
        from platform_agent.memory import (
            build_actor_namespace,
            build_consolidation_namespace,
            build_legacy_namespace,
            build_session_namespace,
        )

        # All should be callable
        assert callable(build_session_namespace)
        assert callable(build_consolidation_namespace)
        assert callable(build_actor_namespace)
        assert callable(build_legacy_namespace)

    def test_create_memory_backend_factory(self):
        from platform_agent.memory import create_memory_backend

        mem = create_memory_backend(backend="local")
        assert mem is not None
        eid = mem.add_user_message("u1", "s1", "test")
        assert eid is not None
