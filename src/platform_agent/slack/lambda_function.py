"""AWS Lambda handler for Slack → Plato integration.

Architecture: Two-Lambda async pattern with SQS FIFO queue.

    Slack → API Gateway → plato-slack-ack (this file: lambda_handler)
                              ↓ SQS FIFO (MessageDeduplicationId = event ts)
                          plato-slack-worker (this file: sqs_worker)
                              ↓
                          AgentCore Runtime (Plato agent)
                              ↓
                          Slack (chat.postMessage / chat.update)

SQS FIFO guarantees:
- Exactly-once processing (MessageDeduplicationId prevents double delivery)
- Per-thread ordering (MessageGroupId = channel + thread_ts)
- No more double replies from at-least-once delivery

Environment variables:
    SLACK_BOT_TOKEN: Slack Bot User OAuth Token (xoxb-...)
                     [legacy; prefer SSM /plato/slack/bot-token]
    SLACK_SIGNING_SECRET: Slack App signing secret
                     [legacy; prefer SSM /plato/slack/signing-secret]
    PLATO_SLACK_CONFIG_SOURCE: "env" (default) | "ssm" | "ssm_fallback"
                     Controls where SlackConfig loads secrets from.
    PLATO_SLACK_MODE: "echo" (default) | "agentcore"
    PLATO_REGION: AWS region for Bedrock (default: us-west-2)
    AGENTCORE_RUNTIME_ARN: AgentCore Runtime ARN
    ASYNC_QUEUE_URL: SQS FIFO queue URL for async processing
    SLACK_DEDUP_TABLE: DynamoDB table for cross-container event dedup
                     (7-day TTL; fails open if unset/unreachable).
"""

from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Stale event guard: drop any event whose `event.ts` is older than this.
# Slack's own dedup window is 7 days, but for replay-style re-deliveries
# we refuse to re-process anything more than 1 hour old. Normal Slack
# retries (3s / 1min / 5min) are well under this bound.
_STALE_EVENT_MAX_AGE_SECONDS = 3600


def _log_json(stage: str, **fields) -> None:
    """Emit a single structured JSON log line for CloudWatch Logs Insights."""
    try:
        payload = {"stage": stage, **fields}
        logger.info(json.dumps(payload, default=str))
    except Exception:  # pragma: no cover - logging must never raise
        logger.info("stage=%s fields=%s", stage, fields)


def _extract_diagnostics(event: dict, body: dict) -> dict:
    """Pull structured diagnostic fields out of an API Gateway event + Slack body.

    Fields mirror what's most useful when reconstructing a Slack replay
    incident from CloudWatch:
      - x-slack-retry-num / x-slack-retry-reason  (Slack retry storm signals)
      - truncated x-slack-signature prefix        (tie logs back to a request)
      - event_id / event_time                     (Slack envelope identifiers)
      - event.type / event.subtype                (what Slack delivered)
      - team_id / api_app_id                      (multi-tenant debugging)
      - event.ts / event.channel                  (fastest dedup-key reverse lookup)
    No user text is logged here; stay PII-friendly.
    """
    headers = event.get("headers") or {}
    # API Gateway normalizes header casing inconsistently across stages.
    header_lc = {str(k).lower(): v for k, v in headers.items()}
    retry_num = header_lc.get("x-slack-retry-num", "")
    retry_reason = header_lc.get("x-slack-retry-reason", "")
    sig = header_lc.get("x-slack-signature", "") or ""
    sig_prefix = sig[:10] if sig else ""

    evt = body.get("event", {}) if isinstance(body.get("event"), dict) else {}
    return {
        "retry_num": retry_num,
        "retry_reason": retry_reason,
        "signature_prefix": sig_prefix,
        "event_id": body.get("event_id", ""),
        "event_time": body.get("event_time", ""),
        "event_type": evt.get("type", ""),
        "event_subtype": evt.get("subtype", ""),
        "team_id": body.get("team_id", ""),
        "api_app_id": body.get("api_app_id", ""),
        "event_ts": evt.get("ts", ""),
        "channel": evt.get("channel", ""),
        "channel_type": evt.get("channel_type", ""),
    }


def _is_stale_event(body: dict, diagnostics: dict) -> bool:
    """Return True if Slack is re-delivering an event older than our threshold.

    A "stale" event is one where `event.ts` (the original message creation
    time) is more than `_STALE_EVENT_MAX_AGE_SECONDS` old. This indicates a
    Slack-side event recovery / replay, not a normal sub-second retry.

    We explicitly allow legitimate Slack retries (x-slack-retry-num set) to
    pass through, because those have a non-stale `event.ts` — but if Slack
    is replaying a very old event, the retry_num is typically also 0.
    """
    try:
        event_ts_raw = diagnostics.get("event_ts") or ""
        if not event_ts_raw:
            return False
        event_ts = float(event_ts_raw)
    except (TypeError, ValueError):
        return False
    age = time.time() - event_ts
    return age > _STALE_EVENT_MAX_AGE_SECONDS

# Reuse handler across warm invocations
_handler = None

# In-memory dedup as a fast first layer (catches Slack retries within same
# Lambda container). SQS FIFO's MessageDeduplicationId is the authoritative
# dedup layer that works across containers.
_seen_events: dict[str, float] = {}
_DEDUP_TTL_SECONDS = 300  # 5 minutes


def _is_duplicate(body: dict) -> bool:
    """Fast in-memory dedup (first layer, same-container only).

    SQS FIFO MessageDeduplicationId is the authoritative second layer.
    """
    import time

    now = time.time()
    # Clean expired entries
    expired = [k for k, v in _seen_events.items() if now - v > _DEDUP_TTL_SECONDS]
    for k in expired:
        del _seen_events[k]

    # Use event timestamp as the unique key (same ts = same user message)
    evt = body.get("event", {})
    dedup_key = f"{evt.get('channel', '')}-{evt.get('ts', '')}"

    if not dedup_key or dedup_key == "-":
        return False

    if dedup_key in _seen_events:
        logger.info("In-memory dedup: skipping %s", dedup_key)
        return True

    _seen_events[dedup_key] = now
    return False


def _get_handler():
    """Lazy-initialize the SlackEventHandler."""
    global _handler
    if _handler is None:
        from platform_agent.slack.handler import SlackEventHandler

        _handler = SlackEventHandler()
    return _handler


def lambda_handler(event: dict, context) -> dict:
    """API Gateway → Lambda entry point (plato-slack-ack).

    Must return within 3 seconds to satisfy Slack's ack requirement.
    Validates the request, then enqueues to SQS FIFO for async processing.
    """
    # Parse body
    body_str = event.get("body", "{}")
    if event.get("isBase64Encoded"):
        import base64

        body_str = base64.b64decode(body_str).decode("utf-8")

    try:
        body = json.loads(body_str)
    except (json.JSONDecodeError, TypeError):
        _log_json("rejected_invalid_json")
        return {"statusCode": 400, "body": "Invalid JSON"}

    handler = _get_handler()

    # Verify Slack signature
    headers = event.get("headers", {})
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")

    # Build diagnostics once per invocation and emit one structured log line
    # at "received" stage. Subsequent stages (url_verification / duplicate /
    # enqueued / stale / signature_bad) share the same diagnostics.
    diagnostics = _extract_diagnostics(event, body)
    _log_json("received", envelope_type=body.get("type", ""), **diagnostics)

    if not handler.verify_signature(body_str, timestamp, signature):
        _log_json("signature_invalid", **diagnostics)
        logger.warning("Invalid Slack signature")
        return {"statusCode": 401, "body": "Invalid signature"}

    # URL verification — must be synchronous
    if body.get("type") == "url_verification":
        _log_json("url_verification", **diagnostics)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"challenge": body.get("challenge", "")}),
        }

    # Fix 2: stale-event guard. Slack occasionally re-delivers event_callback
    # envelopes hours after the original message. Those replays produce
    # spurious bot greetings because downstream dedup layers expire in
    # minutes. Any event.ts older than 1 hour is dropped here (we still
    # return 200 so Slack does not retry further). Legitimate Slack retries
    # (retry_num=1/2/3) pass through because their event.ts is recent.
    if _is_stale_event(body, diagnostics):
        _log_json(
            "dropped_stale",
            reason="event_ts older than {}s".format(_STALE_EVENT_MAX_AGE_SECONDS),
            **diagnostics,
        )
        return {"statusCode": 200, "body": "ok"}

    # Fast in-memory dedup (catches Slack retries within same container)
    if _is_duplicate(body):
        _log_json("dropped_duplicate_memory", **diagnostics)
        return {"statusCode": 200, "body": "ok"}

    # Enqueue to SQS FIFO for async processing
    queue_url = os.environ.get("ASYNC_QUEUE_URL")
    if queue_url:
        _log_json("enqueueing", queue_url=queue_url, **diagnostics)
        return _enqueue_async(queue_url, body)

    # Synchronous fallback (if no queue configured — dev/testing only)
    _log_json("sync_fallback", **diagnostics)
    result = handler.handle(body)
    return {
        "statusCode": result.get("statusCode", 200),
        "body": result.get("body", "ok"),
    }


def _enqueue_async(queue_url: str, body: dict) -> dict:
    """Push event to SQS queue for async processing.

    Supports both standard and FIFO queues:
    - Standard: simple send_message (dedup handled in handler code)
    - FIFO (.fifo suffix): adds MessageDeduplicationId + MessageGroupId
      for exactly-once processing and per-thread ordering

    Returns 200 to Slack immediately.
    """
    try:
        import boto3

        sqs = boto3.client("sqs")

        evt = body.get("event", {})
        channel = evt.get("channel", "unknown")
        ts = evt.get("ts", "0")
        thread_ts = evt.get("thread_ts", ts)

        send_params: dict = {
            "QueueUrl": queue_url,
            "MessageBody": json.dumps(body),
        }

        # FIFO queue detection: URL ends with .fifo
        if queue_url.endswith(".fifo"):
            # MessageDeduplicationId: unique per Slack message (channel + ts).
            # Prevents double processing from Slack retries or dual events.
            # SQS FIFO dedup window is 5 minutes.
            send_params["MessageDeduplicationId"] = f"{channel}-{ts}"

            # MessageGroupId: per-thread ordering.
            # Same thread → sequential processing. Different threads → concurrent.
            send_params["MessageGroupId"] = f"{channel}-{thread_ts}"

            logger.info(
                "Enqueuing to FIFO: dedup=%s, group=%s",
                send_params["MessageDeduplicationId"],
                send_params["MessageGroupId"],
            )

        sqs.send_message(**send_params)
        return {"statusCode": 200, "body": "ok"}

    except Exception as e:
        error_msg = str(e)
        logger.error("Failed to enqueue: %s", e)

        # If it's a FIFO dedup rejection, that's fine (message already queued)
        if "duplicate" in error_msg.lower():
            logger.info("SQS FIFO dedup rejected message — already queued")
            return {"statusCode": 200, "body": "ok"}

        # For other errors, fallback to sync processing
        handler = _get_handler()
        result = handler.handle(body)
        return {
            "statusCode": result.get("statusCode", 200),
            "body": result.get("body", "ok"),
        }


def sqs_worker(event: dict, context) -> None:
    """SQS FIFO → Lambda worker entry point (plato-slack-worker).

    Processes Slack events asynchronously. FIFO queue guarantees
    exactly-once delivery, so we don't need additional dedup here.
    Per-thread ordering ensures multi-turn conversations are sequential.
    """
    handler = _get_handler()

    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            handler.handle(body)
        except Exception as e:
            logger.error("Worker failed for record: %s", e)
            raise  # Let SQS retry (with backoff via visibility timeout)
