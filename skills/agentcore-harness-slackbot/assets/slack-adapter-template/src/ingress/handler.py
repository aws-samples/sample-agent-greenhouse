from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any

import boto3

from shared.models import SlackMessage
from shared.secrets import SecretCache
from shared.security import clean_prompt, verify_slack_signature


@dataclass(frozen=True)
class Dependencies:
    sqs: Any
    secrets: SecretCache


_dependencies: Dependencies | None = None


def default_dependencies() -> Dependencies:
    global _dependencies
    if _dependencies is None:
        _dependencies = Dependencies(
            sqs=boto3.client("sqs"),
            secrets=SecretCache(boto3.client("secretsmanager")),
        )
    return _dependencies


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, separators=(",", ":")),
    }


def header(event: dict[str, Any], name: str) -> str:
    headers = event.get("headers")
    if not isinstance(headers, dict):
        return ""
    for key, value in headers.items():
        if str(key).lower() == name.lower() and isinstance(value, str):
            return value
    return ""


def raw_body(event: dict[str, Any]) -> bytes:
    body = event.get("body")
    if not isinstance(body, str):
        raise ValueError("Missing request body")
    if event.get("isBase64Encoded"):
        return base64.b64decode(body, validate=True)
    return body.encode()


def supported_user_event(event: dict[str, Any]) -> bool:
    if event.get("bot_id") or event.get("bot_profile") or event.get("subtype"):
        return False
    if event.get("type") == "app_mention":
        return True
    return event.get("type") == "message" and event.get("channel_type") == "im"


def handle(
    event: dict[str, Any],
    *,
    queue_url: str,
    signing_secret_arn: str,
    allowed_team_id: str,
    bot_user_id: str | None,
    dependencies: Dependencies,
    now: int | None = None,
) -> dict[str, Any]:
    try:
        body = raw_body(event)
    except (ValueError, TypeError):
        return response(400, {"error": "invalid_request"})
    if len(body) > 131_072:
        return response(413, {"error": "request_too_large"})

    signing_secret = dependencies.secrets.get(signing_secret_arn)
    if not verify_slack_signature(
        signing_secret,
        header(event, "x-slack-request-timestamp"),
        header(event, "x-slack-signature"),
        body,
        now=now,
    ):
        print(json.dumps({"level": "WARNING", "event": "invalid_signature"}))
        return response(401, {"error": "invalid_signature"})

    try:
        envelope = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return response(400, {"error": "invalid_json"})
    if not isinstance(envelope, dict):
        return response(400, {"error": "invalid_envelope"})

    if envelope.get("type") == "url_verification":
        challenge = envelope.get("challenge")
        if not isinstance(challenge, str):
            return response(400, {"error": "invalid_challenge"})
        return response(200, {"challenge": challenge})

    team_id = envelope.get("team_id") or envelope.get("context_team_id")
    if team_id != allowed_team_id:
        return response(403, {"error": "workspace_not_authorized"})
    if envelope.get("type") != "event_callback":
        return response(200, {"ok": True, "ignored": "unsupported_envelope"})

    slack_event = envelope.get("event")
    if not isinstance(slack_event, dict) or not supported_user_event(slack_event):
        return response(200, {"ok": True, "ignored": "unsupported_event"})
    if bot_user_id and slack_event.get("user") == bot_user_id:
        return response(200, {"ok": True, "ignored": "self_message"})

    try:
        message = SlackMessage.from_event(
            envelope,
            slack_event,
            text=clean_prompt(str(slack_event.get("text") or "")),
        )
    except ValueError:
        return response(200, {"ok": True, "ignored": "invalid_message"})

    try:
        dependencies.sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=message.to_json(),
            MessageGroupId=message.queue_group_id,
            MessageDeduplicationId=message.queue_deduplication_id,
        )
    except Exception:
        print(
            json.dumps(
                {
                    "level": "ERROR",
                    "event": "enqueue_failed",
                    "event_id": message.event_id,
                }
            )
        )
        return response(503, {"error": "temporarily_unavailable"})

    print(json.dumps({"level": "INFO", "event": "event_enqueued", "event_id": message.event_id}))
    return response(200, {"ok": True})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    return handle(
        event,
        queue_url=os.environ["QUEUE_URL"],
        signing_secret_arn=os.environ["SIGNING_SECRET_ARN"],
        allowed_team_id=os.environ["ALLOWED_TEAM_ID"],
        bot_user_id=os.environ.get("SLACK_BOT_USER_ID") or None,
        dependencies=default_dependencies(),
    )
