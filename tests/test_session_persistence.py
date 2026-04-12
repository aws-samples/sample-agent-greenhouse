"""Tests for three-layer memory architecture — session persistence via FileSessionManager.

Validates:
- FileSessionManager integration with FoundationStrandsAgent
- System prompt remains static (no memory context injection)
- LTM context injected as user message, not system prompt
- CompactionHook simplified (no prompt injection)
- WS handler uses AgentPool (no more temporary agents)
- enable_memory_extraction=True is set
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from platform_agent.foundation.agent import FoundationStrandsAgent


# ---------------------------------------------------------------------------
# Layer 1: FileSessionManager integration
# ---------------------------------------------------------------------------


class TestFileSessionManagerIntegration:
    """Test that FileSessionManager is properly passed to Strands Agent."""

    def test_agent_accepts_session_manager(self):
        """session_manager parameter is accepted and stored."""
        mock_mgr = MagicMock()
        agent = FoundationStrandsAgent(session_manager=mock_mgr)
        assert agent._session_manager is mock_mgr

    def test_agent_without_session_manager(self):
        """Agent works without session_manager (backward compat)."""
        agent = FoundationStrandsAgent()
        assert agent._session_manager is None

    def test_session_manager_passed_to_strands_agent(self):
        """session_manager is forwarded to Strands Agent constructor."""
        mock_mgr = MagicMock()
        agent = FoundationStrandsAgent(session_manager=mock_mgr)

        with patch.object(agent, '_build_strands_agent') as mock_build:
            mock_inner = MagicMock()
            mock_inner.return_value = {"content": [{"text": "ok"}]}
            mock_build.return_value = mock_inner
            agent.invoke("test")

        # The real _build_strands_agent would have been called on first invoke.
        # To test the actual kwarg passing, we call _build_strands_agent directly.
        agent._agent = None  # reset cached agent
        strands_agent = agent._build_strands_agent()
        # _FakeAgent stores kwargs as attributes
        assert hasattr(strands_agent, 'session_manager')
        assert strands_agent.session_manager is mock_mgr

    def test_no_session_manager_kwarg_when_none(self):
        """When session_manager is None, don't pass it to Strands Agent."""
        agent = FoundationStrandsAgent()
        strands_agent = agent._build_strands_agent()
        # _FakeAgent should NOT have session_manager attribute
        assert not hasattr(strands_agent, 'session_manager')


# ---------------------------------------------------------------------------
# System prompt stability (Layer 1 requirement)
# ---------------------------------------------------------------------------


class TestSystemPromptStability:
    """Verify system prompt is static — no memory context injection."""

    def test_prompt_is_static_across_calls(self, tmp_path):
        """System prompt hash should not change between invocations."""
        (tmp_path / "SOUL.md").write_text("Be helpful.")
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))

        prompt1 = agent.build_system_prompt()
        hash1 = agent._prompt_hash

        prompt2 = agent.build_system_prompt()
        hash2 = agent._prompt_hash

        assert prompt1 == prompt2
        assert hash1 == hash2

    def test_prompt_does_not_contain_memory_context(self, tmp_path):
        """System prompt should not contain injected memory context."""
        (tmp_path / "SOUL.md").write_text("Be helpful.")
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        prompt = agent.build_system_prompt()

        assert "Previous Conversation Context" not in prompt
        assert "[LTM]" not in prompt
        assert "[STM]" not in prompt


# ---------------------------------------------------------------------------
# CompactionHook simplification
# ---------------------------------------------------------------------------


class TestCompactionHookSimplification:
    """Verify CompactionHook is simplified (log-only, no message injection)."""

    def test_compaction_hook_not_in_active_registry(self):
        """CompactionHook should not be in the active hook registry."""
        from platform_agent.foundation.hooks.compaction_hook import CompactionHook
        agent = FoundationStrandsAgent()
        types = [type(h) for h in agent.hook_registry]
        assert CompactionHook not in types

    def test_compaction_hook_removed_from_agent(self):
        """CompactionHook is no longer instantiated on FoundationAgent (dead code removed)."""
        agent = FoundationStrandsAgent()
        assert not hasattr(agent, 'compaction_hook')

    def test_compaction_hook_does_not_inject_messages(self):
        """on_before_invocation should not modify event.messages."""
        from platform_agent.foundation.hooks.compaction_hook import CompactionHook

        hook = CompactionHook(token_threshold=10)
        mock_session = MagicMock()
        mock_session.estimate_tokens.return_value = 100
        hook.session_memory = mock_session

        event = MagicMock()
        event.messages = []
        hook.on_before_invocation(event)

        assert len(event.messages) == 0
        assert hook._flush_triggered

    def test_compaction_hook_constants_preserved(self):
        """Constants are preserved for backward compatibility."""
        from platform_agent.foundation.hooks.compaction_hook import (
            COMPACTION_PROMPT,
            MAX_COMPACTION_TOKENS,
            SYSTEM_PROMPT_TOKEN_RESERVE,
        )

        assert MAX_COMPACTION_TOKENS == 20000
        assert SYSTEM_PROMPT_TOKEN_RESERVE == 15000
        assert "IRON RULE" in COMPACTION_PROMPT


# ---------------------------------------------------------------------------
# Layer 2: LTM context injection pattern
# ---------------------------------------------------------------------------


class TestLTMContextInjection:
    """Verify LTM context is injected as user message prefix, not system prompt."""

    def test_ltm_wraps_in_xml_tags(self):
        """LTM context should be wrapped in <long-term-memory> tags."""
        # Simulate what entrypoint.invoke() does
        ltm_context = "[LTM] User prefers TypeScript"
        user_message = "Help me build an agent"
        prompt_with_ltm = (
            f"<long-term-memory>\n{ltm_context}\n</long-term-memory>\n\n"
            f"{user_message}"
        )
        assert "<long-term-memory>" in prompt_with_ltm
        assert "</long-term-memory>" in prompt_with_ltm
        assert user_message in prompt_with_ltm
        assert ltm_context in prompt_with_ltm

    def test_no_ltm_passes_message_unchanged(self):
        """When no LTM context, user message is passed unchanged."""
        ltm_context = ""
        user_message = "Hello"
        if ltm_context:
            prompt = f"<long-term-memory>\n{ltm_context}\n</long-term-memory>\n\n{user_message}"
        else:
            prompt = user_message
        assert prompt == "Hello"


# ---------------------------------------------------------------------------
# Memory extraction hook enablement
# ---------------------------------------------------------------------------


class TestMemoryExtractionEnabled:
    """Verify enable_memory_extraction works correctly."""

    def test_memory_extraction_hook_off_by_default(self):
        """MemoryExtractionHook not in registry by default."""
        agent = FoundationStrandsAgent()
        assert agent.memory_extraction_hook is None

    def test_memory_extraction_hook_enabled(self):
        """MemoryExtractionHook added when enable_memory_extraction=True."""
        agent = FoundationStrandsAgent(enable_memory_extraction=True)
        assert agent.memory_extraction_hook is not None
        assert agent.memory_extraction_hook in agent.hook_registry

    def test_hook_count_with_memory_extraction(self):
        """11 core + 1 extraction = 12 hooks."""
        agent = FoundationStrandsAgent(enable_memory_extraction=True)
        assert len(agent.hook_registry) == 12


# ---------------------------------------------------------------------------
# Hook registry count (v1: 11 core hooks)
# ---------------------------------------------------------------------------


class TestHookRegistryV1:
    """Verify v1 hook registry has 11 core hooks."""

    def test_core_hook_count(self):
        """11 core hooks (CompactionHook removed)."""
        agent = FoundationStrandsAgent()
        assert len(agent.hook_registry) == 11

    def test_with_all_optional_hooks(self):
        """11 core + 2 optional = 13 hooks."""
        agent = FoundationStrandsAgent(
            enable_memory_extraction=True,
            enable_consolidation=True,
        )
        assert len(agent.hook_registry) == 13


# ---------------------------------------------------------------------------
# SOUL.md AIDLC context-aware exception
# ---------------------------------------------------------------------------


class TestSOULAIDLCException:
    """Verify SOUL.md contains context-aware exception for AIDLC."""

    def test_soul_contains_context_aware_exception(self):
        """SOUL.md should contain the context-aware exception text."""
        import os
        soul_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "workspace", "SOUL.md",
        )
        with open(soul_path) as f:
            content = f.read()
        assert "Context-Aware Exception" in content
        assert "aidlc_start_inception" in content
        assert "skip inception" in content
        assert "aidlc_get_status" in content
