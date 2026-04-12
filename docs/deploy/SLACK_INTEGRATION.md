# Slack Integration Guide

Connect your Agent Greenhouse agent to Slack so users can chat with it via DMs and mentions.

This guide walks through the full pipeline: Cognito user pool for JWT auth, SSM parameter storage, AgentCore JWT authorizer, Slack app creation, and Lambda deployment.

## Prerequisites

- AWS account with [Amazon Bedrock](https://aws.amazon.com/bedrock/) model access enabled
- AgentCore agent already deployed — follow [AGENTCORE_DEPLOY.md](AGENTCORE_DEPLOY.md) first
- Slack workspace where you have permission to install apps
- AWS CLI and Python 3.11+ installed locally

## Architecture

```
Slack User
    │
    ▼
Slack Events API
    │
    ▼
API Gateway → plato-slack-ack Lambda (< 3s ack)
                    │
                    ▼ SQS FIFO queue
                    │  (exactly-once delivery,
                    │   per-thread ordering)
                    ▼
              plato-slack-worker Lambda
                    │
                    ├─► Cognito (JWT token exchange)
                    │
                    ▼
              AgentCore Runtime (with JWT Authorizer)
                    │
                    ▼
              Slack (chat.postMessage / chat.update)
```

The two-Lambda pattern ensures Slack's 3-second acknowledgment deadline is met. The SQS FIFO queue provides exactly-once processing (no double replies) and per-thread ordering (multi-turn conversations stay sequential).

---

## Step 1: Create a Cognito User Pool

The Cognito User Pool provides JWT tokens that the AgentCore JWT Authorizer validates on every request. Each Slack user maps to a Cognito user via a `custom:slack_id` attribute.

### 1a. Create the User Pool

```bash
aws cognito-idp create-user-pool \
  --pool-name plato-slack-users \
  --schema \
    Name=slack_id,AttributeDataType=String,Mutable=true,Required=false \
    Name=role,AttributeDataType=String,Mutable=true,Required=false \
  --auto-verified-attributes email \
  --policies "PasswordPolicy={MinimumLength=12,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=false}" \
  --region us-west-2
```

Note the `Id` field in the response — this is your `<USER_POOL_ID>` (format: `us-west-2_xxxxxxxxx`).

### 1b. Create an App Client

```bash
aws cognito-idp create-user-pool-client \
  --user-pool-id <USER_POOL_ID> \
  --client-name plato-slack-client \
  --explicit-auth-flows ADMIN_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH \
  --generate-secret \
  --region us-west-2
```

Note the `ClientId` and `ClientSecret` from the response.

> **Why ADMIN_USER_PASSWORD_AUTH?** The Slack Lambda authenticates on behalf of users server-side (bot-to-backend flow). Users never enter credentials directly — the Lambda looks up the password from SSM.

### 1c. Create an initial user

```bash
# Create the user
aws cognito-idp admin-create-user \
  --user-pool-id <USER_POOL_ID> \
  --username slack-bot-user \
  --user-attributes \
    Name=email,Value=slack-bot@example.com \
    Name=custom:slack_id,Value=<SLACK_USER_ID> \
    Name=custom:role,Value=admin \
  --message-action SUPPRESS \
  --region us-west-2

# Set a permanent password
aws cognito-idp admin-set-user-password \
  --user-pool-id <USER_POOL_ID> \
  --username slack-bot-user \
  --password '<STRONG_PASSWORD>' \
  --permanent \
  --region us-west-2
```

Repeat for each Slack user who should be able to talk to the bot. The `custom:slack_id` attribute must match the Slack user's member ID (find it in Slack: click the user's profile → "..." → "Copy member ID").

---

## Step 2: Store Cognito Credentials in SSM

The Slack Lambda retrieves Cognito config from AWS Systems Manager Parameter Store at runtime. This keeps secrets out of environment variables and Lambda code.

```bash
# Pool and client config
aws ssm put-parameter \
  --name "/plato/cognito/user-pool-id" \
  --value "<USER_POOL_ID>" \
  --type String \
  --region us-west-2

aws ssm put-parameter \
  --name "/plato/cognito/client-id" \
  --value "<CLIENT_ID>" \
  --type String \
  --region us-west-2

aws ssm put-parameter \
  --name "/plato/cognito/client-secret" \
  --value "<CLIENT_SECRET>" \
  --type SecureString \
  --region us-west-2

# Per-user passwords (one for each Cognito user)
aws ssm put-parameter \
  --name "/plato/cognito/users/slack-bot-user/password" \
  --value "<STRONG_PASSWORD>" \
  --type SecureString \
  --region us-west-2
```

The `CognitoTokenExchange` class in `src/platform_agent/slack/cognito_exchange.py` loads these parameters automatically via `CognitoConfig.from_ssm()`.

---

## Step 3: Configure JWT Authorizer on AgentCore

The JWT Authorizer validates Cognito ID tokens on every request to the AgentCore Runtime. Without this, the agent is accessible to anyone with IAM permissions.

### 3a. Edit `.bedrock_agentcore.yaml`

Add the `authorizer_configuration` block under your agent:

```yaml
agents:
  plato:
    # ... existing config ...
    authorizer_configuration:
      customJWTAuthorizer:
        discoveryUrl: https://cognito-idp.<REGION>.amazonaws.com/<USER_POOL_ID>/.well-known/openid-configuration
        allowedAudience:
          - <CLIENT_ID>
```

See `.bedrock_agentcore.yaml.example` for a complete template.

### 3b. Re-deploy the agent

```bash
agentcore deploy -a plato_container --auto-update-on-conflict
```

> **WARNING**: Never run `agentcore configure --non-interactive` after setting up the JWT authorizer — it overwrites the `authorizer_configuration` section and all Slack users will get 403 errors. Always edit `.bedrock_agentcore.yaml` directly. The `scripts/deploy.sh` script enforces this by checking that the JWT authorizer survives each deploy.

### 3c. Verify the authorizer is active

```bash
# Curl the HTTP endpoint WITHOUT a Bearer token — should return 401
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://<AGENT_ENDPOINT>/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "test"}'
# Expected output: 401

# This should succeed (IAM auth bypasses JWT for CLI testing)
agentcore invoke --iam '{"prompt": "Reply with: AUTH_OK"}' 2>&1 | head -3
```

> **Note**: `agentcore invoke` uses IAM auth, not JWT, so it cannot verify the JWT authorizer is enforced. Curl the HTTP endpoint directly without a Bearer token to confirm JWT enforcement returns 401.

---

## Step 4: Create the Slack App

### 4a. Create a new Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name: `Plato` (or your agent's name)
3. Pick your workspace

### 4b. Configure Bot Token Scopes

Go to **OAuth & Permissions** → **Scopes** → **Bot Token Scopes** and add:

| Scope | Purpose |
|-------|---------|
| `chat:write` | Post responses to channels and DMs |
| `app_mentions:read` | Detect @-mentions in channels |
| `im:history` | Read DM message history |
| `im:read` | View DM metadata |
| `im:write` | Open DM conversations |

### 4c. Enable Event Subscriptions

Go to **Event Subscriptions** → toggle **Enable Events** → set Request URL to your API Gateway endpoint (you'll create this in Step 5).

Subscribe to these **bot events**:

| Event | Purpose |
|-------|---------|
| `message.im` | Direct messages to the bot |
| `app_mention` | @-mentions in channels |

### 4d. Install to workspace

Go to **Install App** → **Install to Workspace** → Authorize.

Note these values from the app settings:
- **Bot User OAuth Token** (`xoxb-...`) — from OAuth & Permissions
- **Signing Secret** — from Basic Information → App Credentials

---

## Step 5: Deploy the Slack Handler Lambda

The Slack integration uses a two-Lambda async pattern. The source code is in `src/platform_agent/slack/`.

### 5a. Lambda functions

| Lambda | Handler | Timeout | Memory | Purpose |
|--------|---------|---------|--------|---------|
| `plato-slack-ack` | `platform_agent.slack.lambda_function.lambda_handler` | 10s | 256 MB | Ack Slack within 3s, enqueue to SQS |
| `plato-slack-worker` | `platform_agent.slack.lambda_function.sqs_worker` | 15 min | 1024 MB | Process event, call AgentCore, reply to Slack |

### 5b. Environment variables

Both Lambdas need:

| Variable | Example | Description |
|----------|---------|-------------|
| `SLACK_BOT_TOKEN` | `xoxb-...` | Bot User OAuth Token from Slack |
| `SLACK_SIGNING_SECRET` | (from Slack app) | Signing secret for request verification |
| `PLATO_SLACK_MODE` | `agentcore` | Set to `agentcore` for production |
| `PLATO_REGION` | `us-west-2` | AWS region for Bedrock/AgentCore |
| `AGENTCORE_RUNTIME_ARN` | `arn:aws:bedrock-agentcore:...` | Agent runtime ARN from deploy output |

The ack Lambda also needs:

| Variable | Example | Description |
|----------|---------|-------------|
| `ASYNC_QUEUE_URL` | `https://sqs.<REGION>.amazonaws.com/<ACCOUNT_ID>/plato-slack.fifo` | SQS FIFO queue URL |

Cognito credentials are loaded from SSM at runtime (see Step 2), not from environment variables. The `CognitoTokenExchange` class handles this automatically.

### 5c. SQS FIFO queue

Create an SQS FIFO queue for the async handoff:

```bash
aws sqs create-queue \
  --queue-name plato-slack.fifo \
  --attributes '{
    "FifoQueue": "true",
    "ContentBasedDeduplication": "false",
    "VisibilityTimeout": "900",
    "MessageRetentionPeriod": "3600"
  }' \
  --region us-west-2
```

- `VisibilityTimeout` (900s = 15 min) must match the worker Lambda timeout
- The ack Lambda sets `MessageDeduplicationId` = `{channel}-{ts}` for exactly-once delivery
- `MessageGroupId` = `{channel}-{thread_ts}` for per-thread ordering

### 5d. IAM permissions

The worker Lambda execution role needs:

```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock-agentcore:InvokeAgentRuntime",
    "cognito-idp:AdminInitiateAuth",
    "cognito-idp:ListUsers",
    "ssm:GetParameter"
  ],
  "Resource": [
    "arn:aws:bedrock-agentcore:<REGION>:<ACCOUNT_ID>:runtime/<AGENT_ID>",
    "arn:aws:cognito-idp:<REGION>:<ACCOUNT_ID>:userpool/<USER_POOL_ID>",
    "arn:aws:ssm:<REGION>:<ACCOUNT_ID>:parameter/plato/cognito/*"
  ]
}
```

The ack Lambda execution role needs `sqs:SendMessage` on the FIFO queue.

### 5e. API Gateway

Create an HTTP API Gateway as the Slack Events endpoint:

1. Create an HTTP API (API Gateway v2)
2. Add a `POST /slack/events` route → integrate with the `plato-slack-ack` Lambda
3. Deploy to a stage (e.g., `prod`)
4. Copy the invoke URL: `https://<API_ID>.execute-api.<REGION>.amazonaws.com/prod/slack/events`
5. Paste this URL into Slack's Event Subscriptions → Request URL field

Slack will send a `url_verification` challenge — the Lambda handles this automatically.

### 5f. Wire up SQS → Worker Lambda

Add the FIFO queue as an event source for the worker Lambda:

```bash
aws lambda create-event-source-mapping \
  --function-name plato-slack-worker \
  --event-source-arn arn:aws:sqs:<REGION>:<ACCOUNT_ID>:plato-slack.fifo \
  --batch-size 1 \
  --region us-west-2
```

Use `batch-size 1` so each Slack message is processed individually.

---

## Step 6: Verify

### 6a. Quick smoke test

1. Open Slack and DM the bot: `Hello, who are you?`
2. The bot should reply within 30–60 seconds (first invocation may be slower due to cold start)
3. Send a follow-up in the same thread to verify session continuity
4. Ask the bot to use a memory tool: `Remember that my favorite language is Python`

### 6b. Automated verification

Run the full deploy verification script:

```bash
bash scripts/deploy.sh
```

This runs an 11-point checklist including:

| # | Check | What it verifies |
|---|-------|-----------------|
| 1 | Config file exists | `.bedrock_agentcore.yaml` present |
| 2 | JWT authorizer configured | Slack OAuth won't get 403 |
| 3 | MEMORY_ID available | Memory tools will work |
| 4 | Dockerfile has MEMORY_ID | Container environment correct |
| 5 | Agent status active | Deploy succeeded |
| 6 | Memory strategies configured | 4 strategies created |
| 7 | JWT authorizer survived deploy | Not wiped by agentcore CLI |
| 8 | CLI invoke (IAM path) | Agent responds to prompts |
| 9 | Memory tools registered | `recall_memory`/`save_memory` available |
| 10 | JWT invoke (Cognito path) | Slack auth flow works end-to-end |
| 11 | E2E memory smoke test | Cross-session recall works |

### 6c. Check CloudWatch logs

If the bot doesn't respond:

```bash
# Check ack Lambda logs
aws logs tail /aws/lambda/plato-slack-ack --since 5m --region us-west-2

# Check worker Lambda logs
aws logs tail /aws/lambda/plato-slack-worker --since 5m --region us-west-2
```

Common issues:

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| No response at all | Ack Lambda not triggered | Check API Gateway → Lambda integration |
| "Invalid signature" in ack logs | Wrong signing secret | Verify `SLACK_SIGNING_SECRET` env var |
| 403 from AgentCore | JWT authorizer misconfigured | Check `discoveryUrl` and `allowedAudience` in YAML |
| "No Cognito user found" | Missing `custom:slack_id` | Add the attribute to the Cognito user |
| Timeout in worker | Agent cold start too long | Increase worker Lambda timeout to 15 min |
| Double replies | SQS not FIFO | Ensure queue name ends in `.fifo` |

---

## Adding New Slack Users

To grant a new Slack user access:

```bash
# 1. Create Cognito user with their Slack member ID
aws cognito-idp admin-create-user \
  --user-pool-id <USER_POOL_ID> \
  --username <USERNAME> \
  --user-attributes \
    Name=email,Value=<EMAIL> \
    Name=custom:slack_id,Value=<SLACK_MEMBER_ID> \
    Name=custom:role,Value=standard \
  --message-action SUPPRESS \
  --region us-west-2

# 2. Set their password
aws cognito-idp admin-set-user-password \
  --user-pool-id <USER_POOL_ID> \
  --username <USERNAME> \
  --password '<STRONG_PASSWORD>' \
  --permanent \
  --region us-west-2

# 3. Store password in SSM
aws ssm put-parameter \
  --name "/plato/cognito/users/<USERNAME>/password" \
  --value "<STRONG_PASSWORD>" \
  --type SecureString \
  --region us-west-2
```

The user can immediately DM the bot — no Lambda restart needed. The `CognitoTokenExchange` discovers new users automatically via `ListUsers`.

---

## Reference: Key Source Files

| File | Purpose |
|------|---------|
| `src/platform_agent/slack/handler.py` | Core event handler — signature verification, agent invocation, Slack replies |
| `src/platform_agent/slack/lambda_function.py` | Lambda entry points (ack + worker) with SQS FIFO pattern |
| `src/platform_agent/slack/cognito_exchange.py` | Slack → Cognito user mapping and JWT token exchange |
| `.bedrock_agentcore.yaml.example` | Complete AgentCore config template with JWT authorizer |
| `scripts/deploy.sh` | Automated deploy + 11-point verification checklist |
