from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SlackMessage:
    event_id: str
    team_id: str
    channel_id: str
    channel_type: str
    user_id: str
    message_ts: str
    thread_ts: str | None
    text: str

    @property
    def is_direct_message(self) -> bool:
        return self.channel_type == "im"

    @property
    def conversation_key(self) -> str:
        if self.is_direct_message:
            return f"dm:{self.team_id}:{self.channel_id}"
        return f"thread:{self.team_id}:{self.channel_id}:{self.thread_ts or self.message_ts}"

    @property
    def queue_group_id(self) -> str:
        return hashlib.sha256(self.conversation_key.encode()).hexdigest()

    @property
    def queue_deduplication_id(self) -> str:
        return hashlib.sha256(self.event_id.encode()).hexdigest()

    @property
    def stream_thread_ts(self) -> str:
        return self.thread_ts or self.message_ts

    @property
    def fallback_thread_ts(self) -> str | None:
        if self.is_direct_message and self.thread_ts is None:
            return None
        return self.thread_ts or self.message_ts

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> SlackMessage:
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise ValueError("Queue message must be a JSON object")
        for key in (
            "event_id",
            "team_id",
            "channel_id",
            "channel_type",
            "user_id",
            "message_ts",
            "text",
        ):
            if not isinstance(payload.get(key), str) or not payload[key]:
                raise ValueError(f"{key} must be a non-empty string")
        thread_ts = payload.get("thread_ts")
        if thread_ts is not None and not isinstance(thread_ts, str):
            raise ValueError("thread_ts must be a string or null")
        return cls(
            event_id=payload["event_id"],
            team_id=payload["team_id"],
            channel_id=payload["channel_id"],
            channel_type=payload["channel_type"],
            user_id=payload["user_id"],
            message_ts=payload["message_ts"],
            thread_ts=thread_ts,
            text=payload["text"],
        )

    @classmethod
    def from_event(
        cls,
        envelope: dict[str, Any],
        event: dict[str, Any],
        *,
        text: str,
    ) -> SlackMessage:
        values = {
            "event_id": envelope.get("event_id"),
            "team_id": envelope.get("team_id") or envelope.get("context_team_id"),
            "channel_id": event.get("channel"),
            "channel_type": event.get("channel_type") or "channel",
            "user_id": event.get("user"),
            "message_ts": event.get("ts"),
        }
        for key, value in values.items():
            if not isinstance(value, str) or not value:
                raise ValueError(f"Slack event is missing {key}")
        thread_ts = event.get("thread_ts")
        if thread_ts is not None and not isinstance(thread_ts, str):
            raise ValueError("Slack thread_ts must be a string")
        return cls(**values, thread_ts=thread_ts, text=text)
