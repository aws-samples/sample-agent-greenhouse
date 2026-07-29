from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config

from shared.harness import HarnessInvoker, HarnessLimits
from shared.identity import derive_harness_identity
from shared.models import SlackMessage
from shared.secrets import SecretCache
from shared.slack_api import (
    STREAM_CHUNK_CHARS,
    SlackApiError,
    SlackClient,
    split_fallback,
)

STREAM_UPDATE_INTERVAL_SECONDS = 1.5


@dataclass(frozen=True)
class Dependencies:
    harness: HarnessInvoker
    slack: SlackClient
    session_hmac_secret: str


class SlackStreamPublisher:
    def __init__(
        self,
        message: SlackMessage,
        slack: SlackClient,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._message = message
        self._slack = slack
        self._clock = clock
        self._latest = ""
        self._sent = ""
        self._message_ts: str | None = None
        self._last_flush: float | None = None
        self._start_failed = False

    def _append_pending(self) -> None:
        if self._message_ts is None:
            return
        pending = self._latest[len(self._sent) :]
        for offset in range(0, len(pending), STREAM_CHUNK_CHARS):
            chunk = pending[offset : offset + STREAM_CHUNK_CHARS]
            self._slack.append_stream(
                channel=self._message.channel_id,
                message_ts=self._message_ts,
                text=chunk,
            )
            self._sent += chunk

    def _start(self) -> None:
        first = self._latest[:STREAM_CHUNK_CHARS]
        try:
            self._message_ts = self._slack.start_stream(
                channel=self._message.channel_id,
                thread_ts=self._message.stream_thread_ts,
                text=first,
                recipient_user_id=(
                    None if self._message.is_direct_message else self._message.user_id
                ),
                recipient_team_id=(
                    None if self._message.is_direct_message else self._message.team_id
                ),
            )
        except SlackApiError as error:
            self._start_failed = True
            print(
                json.dumps(
                    {
                        "level": "WARNING",
                        "event": "stream_start_failed",
                        "event_id": self._message.event_id,
                        "error_code": error.code,
                    }
                )
            )
            return
        self._sent = first
        self._append_pending()
        self._last_flush = self._clock()

    def publish(self, cumulative_text: str) -> None:
        if not cumulative_text or self._start_failed:
            return
        if self._latest and not cumulative_text.startswith(self._latest):
            raise RuntimeError("Harness progress diverged during one invocation")
        self._latest = cumulative_text
        if self._message_ts is None:
            self._start()
            return
        now = self._clock()
        if self._last_flush is None or now - self._last_flush >= STREAM_UPDATE_INTERVAL_SECONDS:
            self._append_pending()
            self._last_flush = now

    def finish(self, final_text: str) -> bool:
        if self._start_failed:
            return False
        if self._latest and not final_text.startswith(self._latest):
            raise RuntimeError("Final Harness text does not extend streamed progress")
        self._latest = final_text
        if self._message_ts is None:
            self._start()
        if self._message_ts is None:
            return False
        self._append_pending()
        self._slack.stop_stream(
            channel=self._message.channel_id,
            message_ts=self._message_ts,
        )
        return True


_dependencies: Dependencies | None = None


def default_dependencies() -> Dependencies:
    global _dependencies
    if _dependencies is None:
        secrets = SecretCache(boto3.client("secretsmanager"))
        timeout = int(os.environ.get("HARNESS_TIMEOUT_SECONDS", "240"))
        client = boto3.client(
            "bedrock-agentcore",
            config=Config(
                connect_timeout=5,
                read_timeout=timeout + 15,
                retries={"mode": "standard", "total_max_attempts": 3},
            ),
        )
        _dependencies = Dependencies(
            harness=HarnessInvoker(
                client,
                harness_arn=os.environ["HARNESS_ARN"],
                qualifier=os.environ["HARNESS_QUALIFIER"],
                limits=HarnessLimits(
                    max_iterations=int(os.environ.get("HARNESS_MAX_ITERATIONS", "10")),
                    max_tokens=int(os.environ.get("HARNESS_MAX_TOKENS", "8000")),
                    timeout_seconds=timeout,
                ),
            ),
            slack=SlackClient(secrets.get(os.environ["BOT_TOKEN_SECRET_ARN"])),
            session_hmac_secret=secrets.get(os.environ["SESSION_HMAC_SECRET_ARN"]),
        )
    return _dependencies


def process(message: SlackMessage, dependencies: Dependencies) -> None:
    identity = derive_harness_identity(dependencies.session_hmac_secret, message)
    stream = SlackStreamPublisher(message, dependencies.slack)
    final_text = dependencies.harness.invoke(
        prompt=message.text,
        runtime_session_id=identity.runtime_session_id,
        actor_id=identity.actor_id,
        on_progress=stream.publish,
    )
    streamed = stream.finish(final_text)
    if not streamed:
        for chunk in split_fallback(final_text):
            dependencies.slack.post_message(
                channel=message.channel_id,
                text=chunk,
                thread_ts=message.fallback_thread_ts,
            )
    print(
        json.dumps(
            {
                "level": "INFO",
                "event": "event_completed",
                "event_id": message.event_id,
                "streamed": streamed,
            }
        )
    )


def handle(
    event: dict[str, Any],
    *,
    dependencies: Dependencies,
) -> dict[str, list[dict[str, str]]]:
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        message_id = str(record.get("messageId") or "")
        try:
            process(SlackMessage.from_json(record["body"]), dependencies)
        except Exception as error:
            print(
                json.dumps(
                    {
                        "level": "ERROR",
                        "event": "event_failed",
                        "message_id": message_id,
                        "error_type": type(error).__name__,
                    }
                )
            )
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def lambda_handler(
    event: dict[str, Any],
    _context: Any,
) -> dict[str, list[dict[str, str]]]:
    return handle(event, dependencies=default_dependencies())
