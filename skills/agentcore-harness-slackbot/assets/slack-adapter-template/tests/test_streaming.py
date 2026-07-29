from __future__ import annotations

from typing import Any

from shared.models import SlackMessage
from worker.handler import SlackStreamPublisher


class FakeSlack:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.appends: list[dict[str, Any]] = []
        self.stops: list[dict[str, Any]] = []

    def start_stream(self, **kwargs: Any) -> str:
        self.starts.append(kwargs)
        return "1700000001.001"

    def append_stream(self, **kwargs: Any) -> None:
        self.appends.append(kwargs)

    def stop_stream(self, **kwargs: Any) -> None:
        self.stops.append(kwargs)


def message() -> SlackMessage:
    return SlackMessage(
        event_id="Ev123",
        team_id="T123",
        channel_id="C123",
        channel_type="channel",
        user_id="U123",
        message_ts="1700000000.001",
        thread_ts=None,
        text="Question",
    )


def test_streams_only_new_suffix_and_flushes_before_stop() -> None:
    slack = FakeSlack()
    times = iter((0.0, 0.5, 2.0))
    publisher = SlackStreamPublisher(
        message(),
        slack,  # type: ignore[arg-type]
        clock=lambda: next(times),
    )
    publisher.publish("Hello")
    publisher.publish("Hello from")
    publisher.publish("Hello from Harness")
    assert publisher.finish("Hello from Harness!")

    assert slack.starts[0]["text"] == "Hello"
    assert [item["text"] for item in slack.appends] == [
        " from Harness",
        "!",
    ]
    assert slack.stops == [{"channel": "C123", "message_ts": "1700000001.001"}]
