"""Tests for SessionRecordingHook — full session interaction recording.

Tests:
1. Start recording — before_invocation creates session record
2. Tool call recording — tool calls added to record
3. Finalize recording — after_invocation sets end_time
4. Get session record — returns complete dict
5. S3 key format — correct format: sessions/{tenant}/{YYYY/MM/DD}/{session_id}.json
6. S3 payload — valid JSON with all expected fields
7. Content truncation — previews truncated to 500 chars
8. Clear — resets all state
9. Multiple tool calls — records are accumulated correctly
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from platform_agent.foundation.hooks.session_recording_hook import (
    SessionRecordingHook,
    _MAX_PREVIEW_LENGTH,
)


@pytest.fixture
def hook() -> SessionRecordingHook:
    """Create a fresh SessionRecordingHook."""
    return SessionRecordingHook(
        session_id="sess_001",
        tenant_id="tenant_abc",
        skill_name="aidlc_inception",
    )


def _make_invocation_event(messages=None):
    """Create a mock BeforeInvocationEvent."""
    event = MagicMock()
    event.messages = messages or [{"role": "user", "content": "hello world"}]
    return event


def _make_after_invocation_event():
    """Create a mock AfterInvocationEvent."""
    return MagicMock()


def _make_before_tool_event(tool_name: str = "read_file", tool_use_id: str = "tu_001"):
    """Create a mock BeforeToolCallEvent."""
    event = MagicMock()
    event.tool_use = {
        "toolUseId": tool_use_id,
        "name": tool_name,
        "input": {"filepath": "test.txt"},
    }
    return event


def _make_after_tool_event(
    tool_name: str = "read_file",
    tool_use_id: str = "tu_001",
    tool_result: str = "file content here",
    status: str | None = None,
):
    """Create a mock AfterToolCallEvent."""
    event = MagicMock()
    event.tool_use = {
        "toolUseId": tool_use_id,
        "name": tool_name,
        "input": {"filepath": "test.txt"},
    }
    event.tool_result = tool_result
    event.status = status
    return event


class TestStartRecording:
    """Test that before_invocation creates session record."""

    def test_start_recording(self, hook: SessionRecordingHook):
        """Before invocation should set start_time and capture messages."""
        event = _make_invocation_event()
        hook.on_before_invocation(event)

        assert hook._start_time is not None
        assert len(hook._messages) == 1
        assert hook._messages[0]["role"] == "user"
        assert hook._messages[0]["content_preview"] == "hello world"
        assert "timestamp" in hook._messages[0]

    def test_start_recording_multiple_messages(self, hook: SessionRecordingHook):
        """Multiple messages in event are all captured."""
        messages = [
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "second message"},
        ]
        event = _make_invocation_event(messages=messages)
        hook.on_before_invocation(event)

        assert len(hook._messages) == 2
        assert hook._messages[0]["role"] == "user"
        assert hook._messages[1]["role"] == "assistant"


class TestToolCallRecording:
    """Test tool call recording."""

    def test_tool_call_recording(self, hook: SessionRecordingHook):
        """Tool calls should be added to the record."""
        hook.on_before_invocation(_make_invocation_event())

        hook.on_before_tool_call(_make_before_tool_event("read_file", "tu_001"))
        hook.on_after_tool_call(_make_after_tool_event("read_file", "tu_001", "file content"))

        assert len(hook._tool_calls) == 1
        tc = hook._tool_calls[0]
        assert tc["tool_name"] == "read_file"
        assert tc["status"] == "success"
        assert tc["duration_ms"] >= 0
        assert "input_preview" in tc
        assert "output_preview" in tc

    def test_tool_call_error_status(self, hook: SessionRecordingHook):
        """Error tool calls should be recorded with error status."""
        hook.on_before_invocation(_make_invocation_event())

        hook.on_before_tool_call(_make_before_tool_event("bad_tool", "tu_err"))
        hook.on_after_tool_call(_make_after_tool_event(
            "bad_tool", "tu_err", "error occurred", status="error",
        ))

        assert hook._tool_calls[0]["status"] == "error"


class TestFinalizeRecording:
    """Test that after_invocation sets end_time."""

    def test_finalize_recording(self, hook: SessionRecordingHook):
        """After invocation should set end_time."""
        hook.on_before_invocation(_make_invocation_event())
        hook.on_after_invocation(_make_after_invocation_event())

        assert hook._end_time is not None
        assert hook._end_time >= hook._start_time


class TestGetSessionRecord:
    """Test get_session_record returns complete dict."""

    def test_get_session_record(self, hook: SessionRecordingHook):
        """Returns complete dict with all expected fields."""
        hook.on_before_invocation(_make_invocation_event())
        hook.on_before_tool_call(_make_before_tool_event())
        hook.on_after_tool_call(_make_after_tool_event())
        hook.on_after_invocation(_make_after_invocation_event())

        record = hook.get_session_record()

        assert record["session_id"] == "sess_001"
        assert record["tenant_id"] == "tenant_abc"
        assert record["start_time"] is not None
        assert record["end_time"] is not None
        assert isinstance(record["messages"], list)
        assert isinstance(record["tool_calls"], list)
        assert isinstance(record["model_calls"], list)
        assert len(record["tool_calls"]) == 1

        metadata = record["metadata"]
        assert metadata["skill_name"] == "aidlc_inception"
        assert metadata["total_tool_calls"] == 1
        assert metadata["total_duration_ms"] > 0

    def test_get_session_record_empty(self):
        """Empty session record has correct structure."""
        hook = SessionRecordingHook()
        record = hook.get_session_record()

        assert record["session_id"] == "unknown"
        assert record["tenant_id"] == "unknown"
        assert record["start_time"] is None
        assert record["end_time"] is None
        assert record["messages"] == []
        assert record["tool_calls"] == []
        assert record["model_calls"] == []
        assert record["metadata"]["total_tool_calls"] == 0
        assert record["metadata"]["total_duration_ms"] == 0.0


class TestS3KeyFormat:
    """Test S3 key generation."""

    def test_s3_key_format(self, hook: SessionRecordingHook):
        """Correct format: sessions/{tenant}/{YYYY/MM/DD}/{session_id}.json."""
        hook.on_before_invocation(_make_invocation_event())

        key = hook.to_s3_key()
        assert key.startswith("sessions/tenant_abc/")
        assert key.endswith("/sess_001.json")

        # Verify date path format (YYYY/MM/DD)
        parts = key.split("/")
        # sessions / tenant_abc / YYYY / MM / DD / sess_001.json
        assert len(parts) == 6
        year = parts[2]
        month = parts[3]
        day = parts[4]
        assert len(year) == 4
        assert len(month) == 2
        assert len(day) == 2

    def test_s3_key_without_start_time(self):
        """Uses current time when start_time is not set."""
        hook = SessionRecordingHook(
            session_id="sess_no_start",
            tenant_id="tenant_x",
        )
        key = hook.to_s3_key()
        assert key.startswith("sessions/tenant_x/")
        assert key.endswith("/sess_no_start.json")


class TestS3Payload:
    """Test S3 payload serialization."""

    def test_s3_payload(self, hook: SessionRecordingHook):
        """Valid JSON with all expected fields."""
        hook.on_before_invocation(_make_invocation_event())
        hook.on_before_tool_call(_make_before_tool_event())
        hook.on_after_tool_call(_make_after_tool_event())
        hook.on_after_invocation(_make_after_invocation_event())

        payload = hook.to_s3_payload()

        # Must be valid JSON
        data = json.loads(payload)

        assert data["session_id"] == "sess_001"
        assert data["tenant_id"] == "tenant_abc"
        assert data["start_time"] is not None
        assert data["end_time"] is not None
        assert len(data["tool_calls"]) == 1
        assert data["metadata"]["skill_name"] == "aidlc_inception"


class TestContentTruncation:
    """Test that previews are truncated to 500 chars."""

    def test_content_truncation(self, hook: SessionRecordingHook):
        """Long content should be truncated to _MAX_PREVIEW_LENGTH."""
        long_content = "x" * 1000

        # Message content truncation
        messages = [{"role": "user", "content": long_content}]
        hook.on_before_invocation(_make_invocation_event(messages=messages))
        assert len(hook._messages[0]["content_preview"]) == _MAX_PREVIEW_LENGTH

        # Tool output truncation
        hook.on_before_tool_call(_make_before_tool_event())
        hook.on_after_tool_call(_make_after_tool_event(tool_result=long_content))
        assert len(hook._tool_calls[0]["output_preview"]) == _MAX_PREVIEW_LENGTH

    def test_short_content_not_truncated(self, hook: SessionRecordingHook):
        """Short content should not be truncated."""
        short_content = "hello"
        messages = [{"role": "user", "content": short_content}]
        hook.on_before_invocation(_make_invocation_event(messages=messages))
        assert hook._messages[0]["content_preview"] == "hello"


class TestClear:
    """Test clear resets all state."""

    def test_clear(self, hook: SessionRecordingHook):
        """Clear should reset all recorded data."""
        hook.on_before_invocation(_make_invocation_event())
        hook.on_before_tool_call(_make_before_tool_event())
        hook.on_after_tool_call(_make_after_tool_event())
        hook.on_after_invocation(_make_after_invocation_event())

        # Verify data exists before clear
        assert hook._start_time is not None
        assert len(hook._tool_calls) > 0

        hook.clear()

        assert hook._start_time is None
        assert hook._end_time is None
        assert hook._messages == []
        assert hook._tool_calls == []
        assert hook._model_calls == []
        assert hook._pending_tool_calls == {}


class TestMultipleToolCalls:
    """Test multiple tool calls are accumulated correctly."""

    def test_multiple_tool_calls(self, hook: SessionRecordingHook):
        """Multiple tool calls should all be recorded."""
        hook.on_before_invocation(_make_invocation_event())

        tools = [
            ("read_file", "tu_001"),
            ("write_file", "tu_002"),
            ("list_files", "tu_003"),
        ]

        for tool_name, tool_id in tools:
            hook.on_before_tool_call(_make_before_tool_event(tool_name, tool_id))
            hook.on_after_tool_call(_make_after_tool_event(tool_name, tool_id))

        assert len(hook._tool_calls) == 3
        tool_names = [tc["tool_name"] for tc in hook._tool_calls]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "list_files" in tool_names

        hook.on_after_invocation(_make_after_invocation_event())

        record = hook.get_session_record()
        assert record["metadata"]["total_tool_calls"] == 3
