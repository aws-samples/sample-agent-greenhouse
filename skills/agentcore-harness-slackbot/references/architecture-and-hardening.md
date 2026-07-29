# Architecture and production hardening

Read this when evaluating the generated adapter, explaining its trust boundaries, or
deciding what must change before production.

## Table of contents

- Why the sample has two Lambdas
- Streaming contract
- Identity and memory
- Security boundaries
- Delivery semantics
- Data handling
- Production hardening checklist

## Why the sample has two Lambdas

Slack expects the Events API endpoint to acknowledge a valid event quickly. A Harness
invocation can run for minutes, so one synchronous request handler is not reliable.

The sample therefore keeps the smallest asynchronous boundary:

```text
Slack -> API Gateway -> ingress Lambda -> FIFO SQS -> worker Lambda
```

The ingress Lambda verifies the Slack HMAC signature over the untouched raw body, checks
the configured team ID, filters unsupported events, and enqueues before returning `200`.
If enqueue fails, it returns `503` so Slack retries.

The worker Lambda invokes the Harness and owns Slack response delivery. It receives only
the Slack signing-independent queue payload and cannot read the Slack signing secret.

## Streaming contract

`InvokeHarness` returns an SDK event stream. Assistant text arrives in
`contentBlockDelta.delta.text` events between `messageStart` and `messageStop`.

The worker:

1. Accumulates the canonical assistant Markdown.
2. Calls `chat.startStream` on the first non-empty partial.
3. Coalesces later partials and sends only new suffixes with `chat.appendStream`.
4. Flushes any remaining suffix.
5. Calls `chat.stopStream`.

The Harness remains channel-neutral. Do not add Slack `mrkdwn` instructions to the Harness
system prompt. Slack presentation belongs in the adapter.

The sample falls back to `chat.postMessage` only when `chat.startStream` is rejected. An
append or stop failure is retried through SQS and can duplicate an already accepted stream.

## Identity and memory

Raw Slack IDs are not sent to AgentCore. The worker uses a generated Secrets Manager HMAC
key to derive:

- one stable `runtimeSessionId` per channel thread;
- one stable `runtimeSessionId` per DM channel;
- one `actorId` per DM user;
- one conversation-scoped `actorId` per channel thread.

This gives channel threads isolated context while DMs retain context across unthreaded
messages. Changing the HMAC key changes every derived identity and behaves like a
conversation reset.

Harness managed memory, if enabled, follows these actor and session choices. Slack memory
does not automatically match identities used by a web or mobile channel.

## Security boundaries

Ingress Lambda:

- public through API Gateway;
- verifies timestamp and HMAC before parsing;
- reads only the signing secret;
- can only send to the event queue;
- accepts only one configured Slack team.

Worker Lambda:

- has no public endpoint;
- reads the bot token and session HMAC secret;
- consumes only the event queue;
- can invoke only the configured Harness and endpoint ARN;
- cannot change model, prompt, tools, skills, or endpoint per Slack request.

Harness:

- uses AWS IAM inbound authorization;
- has explicit tools and limits;
- is reached through a named endpoint such as `PROD`.

Do not pass secrets in CDK context. CDK context is persisted in local files and can appear
in synthesized templates.

## Delivery semantics

The sample provides:

- durable enqueue before Slack acknowledgement;
- FIFO ordering per conversation;
- Slack event deduplication through SQS FIFO for five minutes;
- a DLQ after repeated worker failures;
- one Harness invocation per accepted queue delivery;
- native Slack streaming with cadence-based append calls.

The sample does not provide:

- deduplication beyond the SQS FIFO window;
- a durable event lease;
- a stored final Harness response reused on retry;
- a durable Slack stream timestamp or sent-text checkpoint;
- exactly-once Slack delivery;
- automatic DLQ redrive.

Failure after Slack accepts `startStream` or `appendStream` but before the worker completes
can produce an orphaned or duplicate stream on retry. This limitation is intentional in the
small template and must be stated plainly.

For production, add a DynamoDB event state machine keyed by Slack `event_id`. Persist the
Harness response, Slack stream timestamp, sent prefix, completion marker, lease expiry, and
TTL. Resume only when regenerated text has the stored prefix; otherwise close the old
stream with a restart notice and post the fresh answer.

## Data handling

The SQS message body contains the user's Slack prompt. Lambda logs should contain event IDs
and error types, not prompt or response text. The Harness and Slack naturally process the
content.

Define retention and access controls for:

- SQS and DLQ messages;
- CloudWatch Logs;
- AgentCore traces and memory;
- Slack message history;
- Secrets Manager values.

Do not paste DLQ bodies into tickets or chat.

## Production hardening checklist

Before production:

1. Add user and channel allowlists or an explicit workspace-wide policy.
2. Add DynamoDB idempotency, leases, response reuse, and stream checkpoints.
3. Add CloudWatch alarms for API 5xx, Lambda errors, queue age, and DLQ depth.
4. Add structured metrics for Harness latency, first partial, stream append failures, and
   fallback posts.
5. Tune Lambda concurrency against Harness and Slack rate limits.
6. Handle Slack `Retry-After` with bounded backoff.
7. Review Harness execution-role least privilege and explicit `allowedTools`.
8. Pin dependency versions and run vulnerability review.
9. Decide whether managed memory is appropriate for workspace content.
10. Document HMAC and bot-token rotation procedures.
11. Add a tested DLQ redrive runbook.
12. Define data retention, deletion, incident response, and audit requirements.
13. Add integration tests against a non-production Slack workspace and Harness endpoint.
14. Put deployment in CI/CD with a reviewed CDK diff and rollback procedure.
