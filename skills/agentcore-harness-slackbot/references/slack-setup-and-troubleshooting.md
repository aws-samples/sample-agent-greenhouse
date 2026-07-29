# Slack setup and troubleshooting

Read this while creating the Slack app, populating secrets, enabling Event Subscriptions,
or diagnosing the first end-to-end test.

## Table of contents

- Bootstrap sequence
- Required Slack configuration
- Secret handling
- Acceptance tests
- Troubleshooting

## Bootstrap sequence

Slack validates an Events API request URL, but the URL exists only after the adapter is
deployed. Use the two bundled manifests:

1. Create the app from `slack-app-manifest.bootstrap.yml`. It has scopes but no Events API
   request URL.
2. Install the app in the approved workspace.
3. Record the team ID, bot user ID, signing secret, and installed bot token.
4. Deploy the adapter with team ID and bot user ID as non-secret CDK context.
5. Store the signing secret and bot token in the stack-created Secrets Manager secrets.
6. Put the stack's `SlackRequestUrl` into `slack-app-manifest.yml`.
7. Apply the final manifest to the same app.
8. Confirm Slack verifies the URL.
9. Invite the bot only to intended channels.

Do not create a second Slack app for the final manifest.

## Required Slack configuration

Bot scopes:

- `app_mentions:read`
- `chat:write`
- `im:history`

Bot events:

- `app_mention`
- `message.im`

Socket Mode is disabled. Interactivity is disabled. Token rotation is disabled in the
sample and should be revisited for production.

In channels, users must mention the bot on every turn, including follow-ups in a thread.
In DMs, no mention is required.

`message.channels` is deliberately absent. Adding it sends every visible channel message to
the app, not only direct requests.

## Secret handling

The Slack signing secret appears under Basic Information. The bot token appears under
OAuth and Permissions after installation and starts with `xoxb-`.

The stack creates three secrets:

- signing secret: ingress Lambda can read;
- bot token: worker Lambda can read;
- session HMAC key: worker Lambda can read and the stack generates.

Prefer the AWS Secrets Manager console or an approved secret pipeline. If a shell must be
used, avoid literal secrets in command arguments and history. For example, in bash:

```bash
read -rsp "Slack signing secret: " SLACK_SIGNING_SECRET
printf '\n'
aws secretsmanager put-secret-value \
  --secret-id "$SIGNING_SECRET_ARN" \
  --secret-string "$SLACK_SIGNING_SECRET"
unset SLACK_SIGNING_SECRET

read -rsp "Slack bot token: " SLACK_BOT_TOKEN
printf '\n'
aws secretsmanager put-secret-value \
  --secret-id "$BOT_TOKEN_SECRET_ARN" \
  --secret-string "$SLACK_BOT_TOKEN"
unset SLACK_BOT_TOKEN
```

Do not rotate the generated session HMAC key casually. Existing Slack conversations will
map to new AgentCore sessions and actors.

## Acceptance tests

Channel:

1. Invite the bot.
2. Mention it with a prompt that takes several seconds.
3. Confirm one message appears early and grows.
4. Confirm it stops as one final message.
5. Mention the bot again inside the same thread and check continuity.

DM:

1. Open the app's direct-message surface.
2. Send a prompt without mentioning the bot.
3. Confirm one streamed response.
4. Send a follow-up and check continuity.

Operations:

1. Check API Gateway returns `2xx`.
2. Check ingress log events show enqueue success.
3. Check the FIFO queue drains.
4. Check worker logs show completion.
5. Check the DLQ is empty.
6. Confirm logs omit prompt and response content.

## Troubleshooting

### Slack says the request URL cannot be verified

- Confirm the final URL ends in `/slack/events`.
- Confirm the signing secret in Secrets Manager belongs to this exact Slack app.
- Confirm the request reaches the same region and stack just deployed.
- Inspect ingress logs for `invalid_signature`.
- Do not answer URL verification before validating Slack's signature.

### `invalid_signature`

- Use the untouched raw request body.
- Respect API Gateway's `isBase64Encoded` flag.
- Build the signature base as `v0:<timestamp>:<raw-body>`.
- Reject timestamps older than five minutes.
- Compare with constant-time `hmac.compare_digest`.

### Slack retries the same event

- A `503` means durable enqueue failed and retry is expected.
- A timeout means ingress did too much work. Harness invocation belongs in the worker.
- FIFO deduplication uses Slack `event_id` and lasts five minutes.
- Production deduplication beyond five minutes requires durable state.

### Worker reports `AccessDeniedException`

Confirm its role allows:

- `bedrock-agentcore:InvokeHarness`
- `bedrock-agentcore:InvokeAgentRuntime`

on the exact Harness ARN and named endpoint ARN. Confirm the endpoint qualifier is correct
and `READY`.

### Worker says boto3 has no `invoke_harness`

The Lambda package did not include a recent enough boto3/botocore. Build with Docker or
Finch so `requirements-lambda.txt` is bundled into the function asset.

### `chat.startStream` is rejected

- Confirm the bot token belongs to the installed app and starts with `xoxb-`.
- Confirm `chat:write` is granted and reinstall the app after scope changes.
- Confirm the bot is in the channel.
- Check the Slack error code in worker logs.
- The sample falls back to `chat.postMessage`; that proves basic delivery, not native
  streaming.

### Stream starts but a retry creates another message

This is the documented sample limitation. Add durable event and stream checkpoints before
production; see `architecture-and-hardening.md`.

### No channel response

- Mention the bot explicitly.
- Confirm `app_mention` is subscribed.
- Confirm the bot is invited to the channel.
- Confirm the event's team ID matches `allowedTeamId`.

### No DM response

- Confirm `message.im` is subscribed.
- Confirm `im:history` is granted.
- Reinstall the app after changing scopes.

### Harness responds but Slack receives no final text

- Inspect `contentBlockDelta` events and ensure only assistant deltas are collected.
- Check Slack append and stop error codes.
- Confirm the final suffix is flushed before `chat.stopStream`.
- Check Slack rate limits and `Retry-After`.
