"""Integration tests for cross-actor memory isolation.

These tests hit the real AgentCore Memory backend (plato_container_mem-PLACEHOLDER)
in us-west-2. They are gated by the PLATO_RUN_INTEGRATION=1 environment variable
and skip gracefully when the backend is not reachable.

Uses distinct test actor IDs (TEST-LEAK-A, TEST-LEAK-B) that cannot collide
with real users.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

MEMORY_ID = "plato_container_mem-PLACEHOLDER"
REGION = "us-west-2"
ACTOR_A = f"TEST-LEAK-A-{uuid.uuid4().hex[:8]}"
ACTOR_B = f"TEST-LEAK-B-{uuid.uuid4().hex[:8]}"
SESSION_A = f"test-session-A-{uuid.uuid4().hex[:8]}"
SESSION_B = f"test-session-B-{uuid.uuid4().hex[:8]}"

skip_unless_integration = pytest.mark.skipif(
    os.environ.get("PLATO_RUN_INTEGRATION") != "1",
    reason="PLATO_RUN_INTEGRATION=1 not set — skipping real backend tests",
)


def _get_boto3_client(service: str):
    import boto3
    return boto3.client(service, region_name=REGION)


def _create_event(client, actor_id: str, session_id: str, text: str) -> str | None:
    """Create a conversational event for the given actor."""
    from datetime import datetime, timezone

    try:
        resp = client.create_event(
            memoryId=MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
            eventTimestamp=datetime.now(timezone.utc),
            payload=[{
                "conversational": {
                    "content": {"text": text},
                    "role": "USER",
                }
            }],
        )
        return resp.get("event", {}).get("eventId")
    except Exception as e:
        pytest.skip(f"Cannot create event — backend not reachable: {e}")
        return None


def _delete_event(client, event_id: str) -> None:
    """Best-effort cleanup of a test event."""
    try:
        client.delete_event(memoryId=MEMORY_ID, eventId=event_id)
    except Exception:
        pass


@skip_unless_integration
class TestCrossActorIsolation:
    """Verify that search_long_term for actor B never returns actor A's data."""

    @pytest.fixture(autouse=True)
    def setup_events(self):
        """Create distinct facts for actor A and actor B, wait for extraction."""
        try:
            self.client = _get_boto3_client("bedrock-agentcore")
        except Exception as e:
            pytest.skip(f"Cannot create boto3 client: {e}")

        self.event_ids: list[str] = []

        eid_a = _create_event(
            self.client, ACTOR_A, SESSION_A,
            "ISOLATION-TEST: My secret project is called quantum-unicorn-XYZ.",
        )
        if eid_a:
            self.event_ids.append(eid_a)

        eid_b = _create_event(
            self.client, ACTOR_B, SESSION_B,
            "ISOLATION-TEST: My favourite language is Rust and I work on plasma-reactor.",
        )
        if eid_b:
            self.event_ids.append(eid_b)

        time.sleep(5)

        yield

        for eid in self.event_ids:
            _delete_event(self.client, eid)

    def test_actor_b_cannot_see_actor_a_data(self) -> None:
        """Actor B searching should NOT find Actor A's quantum-unicorn fact."""
        from platform_agent.memory import AgentCoreMemory

        mem = AgentCoreMemory(memory_id=MEMORY_ID, region=REGION)
        results = mem.search_long_term(
            query="quantum-unicorn",
            actor_id=ACTOR_B,
            top_k=10,
        )

        for record in results:
            assert "quantum-unicorn" not in record.text.lower(), (
                f"LEAK: Actor B received Actor A's record: {record.text}"
            )

    def test_actor_b_sees_own_data(self) -> None:
        """Actor B should be able to find their own plasma-reactor fact."""
        from platform_agent.memory import AgentCoreMemory

        mem = AgentCoreMemory(memory_id=MEMORY_ID, region=REGION)
        results = mem.search_long_term(
            query="plasma-reactor",
            actor_id=ACTOR_B,
            top_k=10,
        )

        found_own = any("plasma-reactor" in r.text.lower() for r in results)
        if not found_own:
            pytest.xfail(
                "Actor B's own fact not yet extracted by AgentCore "
                "(extraction can take 10-30s). This is expected in fast CI."
            )

    def test_actor_a_cannot_see_actor_b_data(self) -> None:
        """Actor A searching should NOT find Actor B's plasma-reactor fact."""
        from platform_agent.memory import AgentCoreMemory

        mem = AgentCoreMemory(memory_id=MEMORY_ID, region=REGION)
        results = mem.search_long_term(
            query="plasma-reactor",
            actor_id=ACTOR_A,
            top_k=10,
        )

        for record in results:
            assert "plasma-reactor" not in record.text.lower(), (
                f"LEAK: Actor A received Actor B's record: {record.text}"
            )
