from __future__ import annotations

from typing import Any

from shared.harness import HarnessInvoker, collect_harness_text


def test_collects_assistant_deltas_and_reports_cumulative_progress() -> None:
    events = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": "Hello "}}},
        {"contentBlockDelta": {"delta": {"text": "from Harness"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    progress: list[str] = []
    assert collect_harness_text(events, on_progress=progress.append) == "Hello from Harness"
    assert progress == ["Hello", "Hello from Harness"]


def test_invoker_sends_only_server_controlled_fields() -> None:
    class FakeClient:
        request: dict[str, Any]

        def invoke_harness(self, **kwargs: Any) -> dict[str, Any]:
            self.request = kwargs
            return {
                "stream": [
                    {"messageStart": {"role": "assistant"}},
                    {"contentBlockDelta": {"delta": {"text": "Answer"}}},
                    {"messageStop": {"stopReason": "end_turn"}},
                ]
            }

    client = FakeClient()
    invoker = HarnessInvoker(
        client,
        harness_arn="arn:aws:bedrock-agentcore:us-east-1:111122223333:harness/Test-abcdefghij",
        qualifier="PROD",
    )
    assert (
        invoker.invoke(
            prompt="Question",
            runtime_session_id="slack-1234567890123456789012345678901234567890",
            actor_id="actor-1",
        )
        == "Answer"
    )
    assert client.request["qualifier"] == "PROD"
    assert client.request["messages"] == [{"role": "user", "content": [{"text": "Question"}]}]
    for forbidden in ("model", "systemPrompt", "tools", "skills", "allowedTools"):
        assert forbidden not in client.request
