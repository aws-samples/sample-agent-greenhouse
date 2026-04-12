"""Tests for STM ingestion (feeding AgentCore Memory LTM pipeline).

Verifies:
- _ingest_to_stm writes both user and assistant messages
- Failures are silent (fire-and-forget)
- No-op when memory_backend is None
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest


@pytest.fixture(autouse=True)
def _mock_entrypoint_deps(monkeypatch):
    """Mock heavy entrypoint dependencies so we can import the function."""
    import sys

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


class TestIngestToStm:
    """Test STM ingestion for the LTM pipeline."""

    def test_writes_user_and_assistant_messages(self):
        """Should call add_user_message and add_assistant_message."""
        import entrypoint

        mock_backend = MagicMock()
        with patch.object(entrypoint, "memory_backend", mock_backend):
            entrypoint._ingest_to_stm(
                actor_id="user1",
                session_id="sess1",
                user_message="hello",
                agent_response="hi there",
            )

        mock_backend.add_user_message.assert_called_once_with(
            actor_id="user1",
            session_id="sess1",
            text="hello",
        )
        mock_backend.add_assistant_message.assert_called_once_with(
            actor_id="user1",
            session_id="sess1",
            text="hi there",
        )

    def test_noop_when_no_memory_backend(self):
        """No memory_backend → no-op, no error."""
        import entrypoint

        with patch.object(entrypoint, "memory_backend", None):
            # Should not raise
            entrypoint._ingest_to_stm("u1", "s1", "msg", "resp")

    def test_user_message_failure_does_not_block_assistant(self):
        """If user message fails, assistant message should still be attempted."""
        import entrypoint

        mock_backend = MagicMock()
        mock_backend.add_user_message.side_effect = Exception("network error")

        with patch.object(entrypoint, "memory_backend", mock_backend):
            # Should not raise
            entrypoint._ingest_to_stm("u1", "s1", "msg", "resp")

        # Assistant message should still be called despite user message failure
        mock_backend.add_assistant_message.assert_called_once()

    def test_assistant_message_failure_is_silent(self):
        """If assistant message fails, should not raise."""
        import entrypoint

        mock_backend = MagicMock()
        mock_backend.add_assistant_message.side_effect = Exception("timeout")

        with patch.object(entrypoint, "memory_backend", mock_backend):
            # Should not raise
            entrypoint._ingest_to_stm("u1", "s1", "msg", "resp")

        mock_backend.add_user_message.assert_called_once()

    def test_both_messages_fail_silently(self):
        """Both messages failing should still not raise."""
        import entrypoint

        mock_backend = MagicMock()
        mock_backend.add_user_message.side_effect = Exception("err1")
        mock_backend.add_assistant_message.side_effect = Exception("err2")

        with patch.object(entrypoint, "memory_backend", mock_backend):
            # Should not raise
            entrypoint._ingest_to_stm("u1", "s1", "msg", "resp")
