from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from ingress.handler import Dependencies, handle

NOW = 1_700_000_000
SECRET = "signing-secret"


class FakeSecrets:
    def get(self, _arn: str) -> str:
        return SECRET


class FakeSqs:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)


def signed_request(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":"))
    base = f"v0:{NOW}:{body}".encode()
    signature = "v0=" + hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()
    return {
        "headers": {
            "x-slack-request-timestamp": str(NOW),
            "x-slack-signature": signature,
        },
        "body": body,
        "isBase64Encoded": False,
    }


def test_valid_mention_is_enqueued_before_acknowledgement() -> None:
    sqs = FakeSqs()
    event = {
        "type": "event_callback",
        "team_id": "T123",
        "event_id": "Ev123",
        "event": {
            "type": "app_mention",
            "user": "U123",
            "channel": "C123",
            "channel_type": "channel",
            "text": "<@UBOT> Hello",
            "ts": "1700000000.001",
        },
    }
    result = handle(
        signed_request(event),
        queue_url="https://sqs.example/events.fifo",
        signing_secret_arn="secret:signing",
        allowed_team_id="T123",
        bot_user_id="UBOT",
        dependencies=Dependencies(sqs=sqs, secrets=FakeSecrets()),  # type: ignore[arg-type]
        now=NOW,
    )
    assert result["statusCode"] == 200
    assert len(sqs.messages) == 1
    assert json.loads(sqs.messages[0]["MessageBody"])["text"] == "Hello"


def test_url_verification_requires_a_valid_signature() -> None:
    sqs = FakeSqs()
    result = handle(
        signed_request({"type": "url_verification", "challenge": "abc"}),
        queue_url="queue",
        signing_secret_arn="secret",
        allowed_team_id="T123",
        bot_user_id=None,
        dependencies=Dependencies(sqs=sqs, secrets=FakeSecrets()),  # type: ignore[arg-type]
        now=NOW,
    )
    assert json.loads(result["body"]) == {"challenge": "abc"}
    assert not sqs.messages
