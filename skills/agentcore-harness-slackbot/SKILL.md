---
name: agentcore-harness-slackbot
description: >-
  Build and deploy a small Slack Events API adapter for an Amazon Bedrock AgentCore
  Harness, with incremental responses delivered through Slack chat.startStream,
  chat.appendStream, and chat.stopStream. Use when a customer wants to create or reuse
  an AgentCore Harness, expose it as a Slack bot, stream InvokeHarness contentBlockDelta
  events into Slack, scaffold the API Gateway plus Lambda plus FIFO SQS adapter, create a
  named Harness endpoint such as PROD, configure Slack manifests and secrets, or debug
  Slack signature, endpoint, IAM, queue, or streaming failures. This is a sample that
  creates billable AWS resources, so obtain explicit consent before executing deployment
  or resource-creation steps.
---

# AgentCore Harness Slackbot

## Stop and obtain consent

Before creating, deploying, or changing resources, tell the user:

> This skill installs a sample/reference Slack adapter, not production-ready software.
> It creates real AWS resources, including an AgentCore Harness, API Gateway, Lambda,
> SQS, Secrets Manager, CloudWatch Logs, and model invocations. These resources incur
> charges. Slack workspace configuration also changes. Review security, retry semantics,
> data handling, monitoring, and cleanup before production use.

Wait for an explicit yes. If the user only wants an explanation, explain without running
resource-changing commands.

## Outcome

Create or reuse one declarative AgentCore Harness and connect it to Slack through:

```text
Slack Events API
  -> API Gateway HTTP API
  -> ingress Lambda (signature verification and quick acknowledgement)
  -> SQS FIFO
  -> worker Lambda
  -> InvokeHarness on a named endpoint
  -> Slack startStream / appendStream / stopStream
```

Keep the Harness channel-neutral. Do not export it to a custom runtime merely to support
Slack. The adapter consumes the Harness event stream and owns Slack-specific delivery.

This template intentionally omits DynamoDB delivery leases and durable stream checkpoints.
SQS deduplicates the same Slack event for five minutes, but a worker failure after Slack
accepts a stream call can still create a duplicate on retry. Read
`references/architecture-and-hardening.md` before describing this as production-ready.

## Bundled resources

- `scripts/scaffold_slack_adapter.py`: copy and render the generic adapter template into a
  customer's AgentCore project.
- `scripts/ensure_harness_endpoint.py`: create or update a named Harness endpoint from
  `agentcore/.cli/deployed-state.json`, then wait until it is ready.
- `assets/slack-adapter-template/`: standalone Python Lambda and TypeScript CDK project,
  focused tests, and two Slack manifests.
- `references/slack-setup-and-troubleshooting.md`: Slack bootstrap cycle, secrets, test
  procedure, and common errors.
- `references/architecture-and-hardening.md`: trust boundaries, delivery limitations,
  data handling, and the path from sample to production.

## Prerequisites

Confirm:

- AgentCore CLI is installed: `agentcore --version`.
- AWS credentials point at the intended account: `aws sts get-caller-identity`.
- The target region is explicit in `agentcore/aws-targets.json`.
- Node.js 20 or newer and npm are available.
- Python 3.12 or newer with `boto3>=1.43.39,<2` is available for the endpoint
  helper.
- Docker or Finch is running for CDK's Lambda dependency bundle.
- The user can create and install a Slack app in the target workspace.

Do not accept account IDs, ARNs, Slack tokens, signing secrets, or workspace IDs copied
from another customer or example. Discover them from the current project and workspace.

## Step 0: Inspect before changing

Read the project `AGENTS.md`, `agentcore/agentcore.json`, the Harness directory, and
`agentcore/.llm-context/` types. Check `git status` and preserve unrelated changes.

Determine whether the customer has:

1. An existing Harness to reuse.
2. A Harness without a named endpoint.
3. No AgentCore project yet.

Never add Slack behavior by editing generated `agentcore/cdk` source. JSON and the Harness
directory remain authoritative for the AgentCore deployment. The Slack adapter is a
separate standalone CDK app.

## Step 1: Create or harden the Harness

If no project exists, have the user run the interactive wizard:

```bash
agentcore create
```

The user chooses the project name, model, region, tools, skills, and memory. Guide them to
select a Harness, but do not guess those choices through a large non-interactive command.

For an existing project, reuse its Harness. Do not export it.

Before deployment, inspect `app/<HARNESS>/harness.json` and require:

- `authorizerType` is `AWS_IAM`;
- `allowedTools` explicitly names only intended tools;
- `maxIterations`, `maxTokens`, and `timeoutSeconds` are explicit;
- no `shell`, `file_operations`, wildcard, or unknown tool is exposed;
- the system prompt contains no channel-specific Slack formatting instructions.

For a tool-free starter Harness, an empty `allowedTools` list is appropriate. If tools are
present, preserve their exact configured names. Use the local schema rather than copying a
possibly stale example.

The generated adapter sends invocation limits of `10` iterations, `8000` tokens, and `240`
seconds. Align the Harness-level limits with those values, or deliberately lower both the
Harness and adapter values after reviewing the workload. Do not let a channel adapter
silently request broader limits than the Harness security review approved.

Validate:

```bash
agentcore validate
```

Stop on validation errors.

## Step 2: Deploy and pin a named endpoint

Deploy the AgentCore project:

```bash
agentcore deploy
agentcore status --type harness --json
```

Confirm the deployed Harness is `READY`. Then create or update a stable endpoint:

```bash
python <SKILL_DIR>/scripts/ensure_harness_endpoint.py \
  --project-root . \
  --harness-name <HARNESS_NAME> \
  --endpoint-name PROD
```

The helper reads the current target's Harness ID and deployed version, calls the AgentCore
control plane, and waits until the endpoint reports `READY` with that `liveVersion`.

Do not infer serving state from `harnessVersion` alone. The adapter invokes the endpoint
qualifier, so the endpoint's live version is the serving authority.

## Step 3: Scaffold the Slack adapter

From the AgentCore project root:

```bash
python <SKILL_DIR>/scripts/scaffold_slack_adapter.py \
  --project-root . \
  --app-name "<CUSTOMER_APP_NAME>"
```

This creates `slack-adapter/` and refuses to overwrite an existing directory. Review the
generated files before deployment.

Run local checks:

```bash
cd slack-adapter
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q

cd infra
npm install
npm run build
npm test
```

Run `npm audit` and report findings. Do not claim that CDK development-tool dependencies
are packaged into the Python Lambdas.

## Step 4: Create the Slack app without events

Read `references/slack-setup-and-troubleshooting.md`.

Create a Slack app from:

```text
slack-adapter/slack-app-manifest.bootstrap.yml
```

The bootstrap manifest intentionally omits Event Subscriptions, breaking the request URL
cycle. Install the app in the approved workspace, then collect:

- Slack team/workspace ID;
- bot user ID;
- signing secret;
- bot token beginning with `xoxb-`.

Treat the signing secret and bot token as secrets. Never put them in source, manifests,
CDK context, logs, tickets, or chat.

## Step 5: Deploy the adapter

Read the Harness ARN from the current project's deploy output or
`agentcore/.cli/deployed-state.json`. Do not paste a remembered ARN.

Review the exact infrastructure change:

```bash
cd slack-adapter/infra
npm run cdk -- diff \
  -c harnessArn=<CURRENT_HARNESS_ARN> \
  -c harnessQualifier=PROD \
  -c allowedTeamId=<SLACK_TEAM_ID> \
  -c slackBotUserId=<SLACK_BOT_USER_ID>
```

Then deploy with the same context:

```bash
npm run cdk -- deploy \
  -c harnessArn=<CURRENT_HARNESS_ARN> \
  -c harnessQualifier=PROD \
  -c allowedTeamId=<SLACK_TEAM_ID> \
  -c slackBotUserId=<SLACK_BOT_USER_ID>
```

Review the CDK diff before confirming. The expected resources are:

- one HTTP API;
- two Lambda functions;
- one FIFO queue and one FIFO DLQ;
- three Secrets Manager secrets;
- narrowly scoped invoke, queue, and secret permissions.

Record stack outputs: `SlackRequestUrl`, `SigningSecretArn`, `BotTokenSecretArn`, and
`DeadLetterQueueUrl`.

## Step 6: Populate secrets

Use the Slack app's Basic Information and OAuth pages. Prefer the AWS Secrets Manager
console or an approved secret-management workflow.

If using the CLI, read secrets without echo and pass shell variables rather than literal
secret values in command history. Update:

- `SigningSecretArn` with the Slack signing secret;
- `BotTokenSecretArn` with the installed bot token.

Do not replace the generated session HMAC key after conversations begin. Rotating it changes
all derived AgentCore actor and session IDs.

## Step 7: Enable Event Subscriptions

Replace `REPLACE_WITH_REQUEST_URL` in:

```text
slack-adapter/slack-app-manifest.yml
```

with the `SlackRequestUrl` stack output. Apply that manifest to the existing Slack app, or
set the same values in Slack's Event Subscriptions UI.

The request URL must verify successfully. Subscribe only to:

- `app_mention` for channels;
- `message.im` for direct messages.

Invite the bot only to intended channels. In a channel, mention it on every turn, including
follow-ups in a thread. Do not add `message.channels` merely to avoid mentions; that sends
unrelated channel traffic to the app.

## Step 8: Verify end to end

Run these acceptance checks:

1. Mention the bot in an approved channel.
2. Confirm one Slack message starts before the Harness answer completes.
3. Confirm that message grows and then stops, rather than creating one post per delta.
4. Ask a follow-up in the same thread and confirm the same AgentCore session is reused.
5. Send a DM and confirm streaming works there.
6. Inspect ingress and worker logs by Slack `event_id`; confirm prompt and response text are
   not logged.
7. Confirm the FIFO queue drains and the DLQ remains empty.
8. Confirm the worker invokes the intended endpoint qualifier and not an unqualified
   Harness version.

If streaming is unavailable, the sample falls back to ordinary `chat.postMessage`. Treat
that as a compatibility result, not proof that native streaming worked.

## Step 9: Hand off honestly

Report:

- project path, branch, and dirty state;
- Harness name, ARN, endpoint name, endpoint status, and live version;
- adapter stack name and request URL;
- local validation results;
- whether channel and DM tests passed;
- whether the reply used native Slack streaming or fallback posting;
- resources created and cleanup commands;
- that changes are committed or uncommitted.

Before production, use `references/architecture-and-hardening.md` to discuss durable
idempotency, stream checkpoints, allowlists, monitoring, rate limits, secret rotation, data
retention, concurrency, and incident recovery.

## Cleanup

Delete the Slack adapter stack when it is no longer needed:

```bash
cd slack-adapter/infra
npm run cdk -- destroy \
  -c harnessArn=<CURRENT_HARNESS_ARN> \
  -c harnessQualifier=PROD \
  -c allowedTeamId=<SLACK_TEAM_ID>
```

Remove the Slack app or disable Event Subscriptions. Remove the Harness only when the user
explicitly confirms it is not shared by other channels or applications.

## Quick order

1. Obtain consent.
2. Inspect or create the Harness.
3. Harden and validate Harness configuration.
4. Deploy Harness and pin `PROD`.
5. Scaffold and test `slack-adapter/`.
6. Create and install the bootstrap Slack app.
7. Deploy the adapter.
8. Populate Slack secrets.
9. Apply the final manifest.
10. Verify channel, thread, DM, streaming, logs, queue, and endpoint version.
11. Report limitations and cleanup.
