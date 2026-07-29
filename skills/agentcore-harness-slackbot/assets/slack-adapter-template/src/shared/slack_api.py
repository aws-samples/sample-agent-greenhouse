from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

SLACK_API = "https://slack.com/api"
STREAM_CHUNK_CHARS = 12_000
FALLBACK_CHUNK_CHARS = 3_500


class SlackApiError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def split_fallback(text: str, *, limit: int = FALLBACK_CHUNK_CHARS) -> list[str]:
    remaining = text.strip()
    if not remaining:
        raise ValueError("Cannot post an empty Slack response")
    chunks: list[str] = []
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit + 1)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


class SlackClient:
    def __init__(
        self,
        bot_token: str,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not bot_token.startswith("xoxb-"):
            raise ValueError("Slack bot token must start with xoxb-")
        self._bot_token = bot_token
        self._opener = opener

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{SLACK_API}/{method}",
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={
                "authorization": f"Bearer {self._bot_token}",
                "content-type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=10) as response:
                result = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SlackApiError(f"Slack API call failed: {method}") from error
        if not isinstance(result, dict) or result.get("ok") is not True:
            code = result.get("error", "bad_response") if isinstance(result, dict) else None
            raise SlackApiError(f"Slack rejected {method}: {code}", code=str(code))
        return result

    @staticmethod
    def _timestamp(result: dict[str, Any]) -> str:
        value = result.get("ts")
        if not isinstance(value, str) or not value:
            raise SlackApiError("Slack response omitted message timestamp")
        return value

    def start_stream(
        self,
        *,
        channel: str,
        thread_ts: str,
        text: str,
        recipient_user_id: str | None,
        recipient_team_id: str | None,
    ) -> str:
        payload: dict[str, Any] = {
            "channel": channel,
            "thread_ts": thread_ts,
            "markdown_text": text,
        }
        if recipient_user_id:
            payload["recipient_user_id"] = recipient_user_id
        if recipient_team_id:
            payload["recipient_team_id"] = recipient_team_id
        return self._timestamp(self._call("chat.startStream", payload))

    def append_stream(self, *, channel: str, message_ts: str, text: str) -> None:
        self._call(
            "chat.appendStream",
            {"channel": channel, "ts": message_ts, "markdown_text": text},
        )

    def stop_stream(self, *, channel: str, message_ts: str) -> None:
        self._call("chat.stopStream", {"channel": channel, "ts": message_ts})

    def post_message(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None,
    ) -> str:
        payload: dict[str, Any] = {
            "channel": channel,
            "text": text,
            "mrkdwn": True,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        return self._timestamp(self._call("chat.postMessage", payload))
