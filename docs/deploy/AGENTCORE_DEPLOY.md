# Deploying Foundation Agent to AgentCore Runtime

## Prerequisites

- AWS Account with credentials configured (`aws configure`)
- Python 3.10+
- Amazon Bedrock model access enabled for `global.anthropic.claude-opus-4-6-v1` (or your chosen model). Enable it in [Bedrock Model Access](https://console.aws.amazon.com/bedrock/home#/modelaccess)
- AgentCore permissions ([see docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html))
- IAM execution role with these permissions:
  - `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` (model access)
  - `ecr:GetDownloadUrlForLayer`, `ecr:BatchGetImage`, `ecr:GetAuthorizationToken` (container image pull)
  - `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` (CloudWatch logging)

### AgentCore Execution Role Permissions

The AgentCore execution role (auto-created or custom) needs these permissions for Memory, Observability, and Model invocation. See [`iam-policy.json`](../../iam-policy.json) for the full policy.

> **⚠️ Common fresh-deploy failure**: `agentcore deploy` auto-creates an execution role but does NOT add Memory API permissions. Memory tools (save/recall) will silently fail with `AccessDeniedException`. You must add the Memory permissions from `iam-policy.json` to the execution role after first deploy.

```bash
# After first deploy, find the execution role name:
aws bedrock-agentcore get-agent-runtime --agent-runtime-id <AGENT_ID> \
  --region us-west-2 --query "agentRuntime.roleArn" --output text

# Add Memory permissions:
aws iam put-role-policy --role-name <EXECUTION_ROLE_NAME> \
  --policy-name agentcore-memory-access \
  --policy-document file://iam-policy.json
```

### ECR Repository

Create the ECR repository before deploying:

```bash
aws ecr create-repository \
  --repository-name bedrock-agentcore-<YOUR_AGENT_NAME> \
  --region us-west-2
```

The repository name must match the `ecr_repository` field in `.bedrock_agentcore.yaml`.

## Quick Deploy

```bash
# 1. Install dependencies
pip install bedrock-agentcore strands-agents bedrock-agentcore-starter-toolkit

# 2. Install the foundation agent package
pip install -e .

# 3. Configure the agent for AgentCore (FIRST TIME ONLY)
agentcore configure -e entrypoint.py
# ⚠️  FIRST TIME ONLY — never run `agentcore configure` again after initial setup!
#   It wipes the JWT authorizer config. Use deploy.sh for all subsequent deploys.
# ⚠️  WARNING: --non-interactive generates wrong defaults!
#   - Agent name defaults to "entrypoint" (not your chosen name)
#   - Auth defaults to IAM (need JWT for Slack)
#   - Memory defaults to STM_ONLY (need STM_AND_LTM for cross-session)
# After running, MANUALLY edit .bedrock_agentcore.yaml to fix these.
# See Troubleshooting section below for details.

# 3.5. Create ECR repository (if it doesn't exist)
aws ecr create-repository --repository-name bedrock-agentcore-plato --region us-west-2
# Note: ECR repo names must use hyphens, not underscores

# 4. Deploy to AgentCore Runtime
agentcore deploy

# 5. Test the deployed agent
agentcore invoke '{"prompt": "Hello, tell me about yourself"}'
```

## Local Testing

```bash
# Start the agent locally (serves on http://localhost:8080)
python entrypoint.py

# Test with curl
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello!"}'
```

### Session Isolation in Local Testing

When testing locally, use the correct header for session isolation.
**Important**: Session IDs must be at least 33 characters for cloud deployment
compatibility. Use UUIDs or padded strings:

```bash
# Session A (use UUID for cloud compatibility)
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -d '{"prompt": "My name is Alice"}'

# Session B (isolated — does NOT know about Alice)
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: b2c3d4e5-f6a7-8901-bcde-f12345678901" \
  -d '{"prompt": "What is my name?"}'
```

> **Important**: The header must be `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`.
> Using the wrong header (e.g. `X-Session-Id`) causes all requests to share the
> "default" session and conversation histories will leak between users.
> In cloud deployment, AgentCore injects this header automatically.

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKSPACE_DIR` | `/app/workspace` | Path to workspace with SOUL.md, skills/, etc. |
| `MODEL_ID` | `global.anthropic.claude-opus-4-6-v1` | Bedrock model ID (global inference profile) |
| `ENABLE_CLAUDE_CODE` | `true` | Enable CC CLI tool |
| `MEMORY_ID` | (none) | AgentCore Memory resource ID for cross-session memory |
| `AWS_REGION` | `us-west-2` | AWS region |

## With AgentCore Memory

```bash
# 1. Create memory resource during configure
agentcore configure -e entrypoint.py
# Choose "yes" when prompted for memory

# 2. Set MEMORY_ID in your runtime environment
# The memory ID is shown in the deployment output
```

## Architecture

```
AgentCore Runtime
├── BedrockAgentCoreApp (HTTP: /invocations, /ping, /ws)
│   └── @app.entrypoint → invoke(payload, context)
│
├── Foundation Agent (Strands SDK)
│   ├── Soul System (SOUL.md → system prompt)
│   ├── 7 HookProviders (Soul/Memory/Audit/Guardrails/ToolPolicy/Compaction/AgentCoreMemory)
│   ├── Tools (@tool: claude_code + workspace tools)
│   └── Skill Registry (lazy loading)
│
├── Bedrock Model (Claude via BedrockModel)
├── AgentCore Memory (STM + LTM, optional)
└── AgentCore Identity/Policy (managed by runtime)
```

## Memory Configuration

AgentCore Memory provides cross-session long-term memory with 4 strategies (semantic, summary, preferences, episodic). Memory is optional but required for production Slack deployments where users expect the bot to remember context across conversations.

### Create the Memory Resource

```bash
# During initial configure, choose "yes" when prompted for memory
agentcore configure -e entrypoint.py

# Or create via API
aws bedrock-agentcore create-memory \
  --name plato-memory \
  --region us-west-2
```

Note the `memoryId` from the output (format: `mem-xxxxxxxxxx`).

### Add memory to `.bedrock_agentcore.yaml`

```yaml
agents:
  plato:
    # ... existing config ...
    memory_enabled: true
    memory:
      memory_arn: arn:aws:bedrock-agentcore:us-west-2:<ACCOUNT_ID>:memory/<MEMORY_ID>
```

Also ensure `MEMORY_ID` is set in the Dockerfile environment:

```dockerfile
ENV MEMORY_ID=<MEMORY_ID>
```

### Create Memory Strategies

Run the setup script to create all 4 strategies idempotently:

```bash
python3 scripts/setup_memory.py --memory-id <MEMORY_ID> --verify
```

This creates:

| Strategy | Type | Scope | Purpose |
|----------|------|-------|---------|
| semanticKnowledge | Semantic | Per-actor | Factual knowledge, technical decisions |
| conversationSummary | Summary | Per-session | Conversation summaries |
| userPreferences | UserPreference | Per-actor | User working style and preferences |
| episodicMemory | Episodic | Per-actor | "What happened" with reflection |

Use `--dry-run` to preview without creating, or `--verify` to confirm strategies exist after creation.

### Verify Memory Works

```bash
agentcore invoke '{"prompt": "Save this fact: my favorite color is blue", "actor_id": "test-user"}'
# Wait ~30 seconds for STM → LTM pipeline
agentcore invoke '{"prompt": "What is my favorite color?", "actor_id": "test-user"}'
```

The agent should recall the saved fact. For a comprehensive test, run:

```bash
python3 scripts/e2e_memory_test.py --memory-id <MEMORY_ID> --wait 90
```

## JWT Authorizer

The JWT Authorizer gates access to the AgentCore Runtime using Cognito ID tokens. This is required for the Slack integration (each Slack user gets a per-user JWT) and recommended for any multi-user deployment.

For full Cognito setup instructions, see [SLACK_INTEGRATION.md](SLACK_INTEGRATION.md) Steps 1–3.

### Quick config

Add to `.bedrock_agentcore.yaml`:

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

> **WARNING**: `agentcore configure --non-interactive` **will wipe the `authorizer_configuration` section**. Never use it after initial setup. Always edit `.bedrock_agentcore.yaml` directly and deploy with `agentcore deploy`. The `scripts/deploy.sh` script checks for this and will abort if the JWT authorizer goes missing.

## Post-Deploy Verification with `deploy.sh`

The `scripts/deploy.sh` script automates the full deploy-and-verify cycle. It runs pre-deploy checks, deploys the agent, sets up memory strategies, and then runs an 11-point post-deploy checklist.

```bash
bash scripts/deploy.sh
```

### What each check verifies

**Pre-deploy checks** (abort if failed):

| # | Check | Failure means |
|---|-------|--------------|
| 1 | `.bedrock_agentcore.yaml` exists | Run `agentcore configure -e entrypoint.py` first |
| 2 | JWT authorizer configured | Slack OAuth will get 403 — add `authorizer_configuration` |
| 3 | `MEMORY_ID` available | Memory tools won't work — set in config or env |
| 4 | Dockerfile has `MEMORY_ID` | Container won't find memory config — add `ENV MEMORY_ID` |

**Deploy steps**: git pull → `agentcore deploy` → wait for Active → setup memory strategies

**Post-deploy verification**:

| # | Check | Failure means |
|---|-------|--------------|
| 5 | Agent status Active | Deploy didn't complete — check CloudWatch build logs |
| 6 | JWT authorizer survived deploy | agentcore CLI may have wiped it — restore from YAML |
| 7 | CLI invoke (IAM path) | Agent not responding — check runtime logs |
| 8 | Memory tools registered | `MEMORY_ID` not reaching the container — check Dockerfile |
| 9 | JWT invoke (Cognito path) | Slack auth broken — check SSM params and Cognito config |
| 10 | E2E memory smoke test | STM→LTM pipeline broken — check memory strategy setup |
| 11 | Observability (logs + metrics) | CloudWatch not receiving data — check `observability.enabled` |

At the end, the script prints the `AGENTCORE_RUNTIME_ARN` and `AGENTCORE_MEMORY_ID` values needed for the Slack Lambda environment variables.

## Gotchas & Known Issues

### 1. Session ID Minimum Length (33 characters)

AgentCore requires `runtimeSessionId` to be **at least 33 characters**. Short IDs
like `"test-123"` will be rejected by the API. Always use full UUIDs:

```python
import uuid
session_id = str(uuid.uuid4())  # e.g. "a1b2c3d4-e5f6-7890-abcd-ef1234567890" (36 chars) ✅
# NOT: session_id = "test-123"  ❌ (too short, API will reject)
```

The allowed character pattern is `[a-zA-Z0-9][a-zA-Z0-9-_]*` — no dots or other
special characters. If you need a human-readable prefix, pad to at least 33 chars:

```python
session_id = f"my-session-{uuid.uuid4()}"  # Always long enough ✅
```

### 2. IAM Permissions for `agentcore deploy`

By default, `agentcore deploy` tries to **auto-create an IAM execution role**,
which requires `iam:CreateRole` permission. If your IAM user/role doesn't have
this permission:

```yaml
# In .bedrock_agentcore.yaml — disable auto-creation and specify an existing role:
agents:
  entrypoint:
    aws:
      execution_role: arn:aws:iam::123456789012:role/YourExistingRole
      execution_role_auto_create: false
```

Create the execution role manually with the required Bedrock trust policy, then
reference its ARN in the config.

### 3. Orphaned Memory Resources on Deploy Failure

If `agentcore deploy` creates a Memory resource but then fails (e.g., due to
missing IAM permissions), the Memory resource becomes orphaned — it exists but
isn't attached to a running agent. This is a known issue in the toolkit.

**Workaround**: Before deploying, verify IAM permissions are correct. If you
encounter orphaned memory resources, clean them up via:

```bash
aws bedrock-agent delete-memory --memory-id <orphaned-memory-id> --region us-west-2
```

Or use `agentcore memory list` to find and manage memory resources.

## Programmatic Invocation

```python
import json, uuid, boto3

client = boto3.client('bedrock-agentcore')

# IMPORTANT: session ID must be >= 33 characters. Use full UUID.
response = client.invoke_agent_runtime(
    agentRuntimeArn="<your-agent-arn>",
    runtimeSessionId=str(uuid.uuid4()),  # Full UUID (36 chars) ✅
    payload=json.dumps({"prompt": "Hello!"}).encode(),
    qualifier="DEFAULT"
)

content = [chunk.decode('utf-8') for chunk in response.get("response", [])]
print(json.loads(''.join(content)))
```

## Post-Deploy Verification (MANDATORY)

**Every deploy must be verified end-to-end before being declared successful.**

Run the smoke test:

```bash
bash scripts/smoke-test.sh \
  --runtime-arn "arn:aws:bedrock-agentcore:us-west-2:ACCOUNT:runtime/AGENT_ID" \
  --memory-id "MEMORY_ID" \
  --region us-west-2
```

The smoke test checks:

| Check | What it verifies | Failure means |
|-------|-----------------|---------------|
| Agent Reachable | Basic invoke works | Agent not running or IAM denied |
| Agent Identity | Plato knows its name | SOUL.md not loaded |
| Skills Loaded | Skills discovered from workspace | workspace dir missing or wrong path |
| Memory Tools | save_memory/recall_memory available | Memory backend not initialized |
| Claude Code CLI | `claude` binary on PATH | CLI not installed in runtime |
| Memory Resource | Memory ID is ACTIVE | Memory not created or deleted |

**Rules:**
- Any FAIL → deploy is NOT successful. Fix and re-test.
- Warnings are acceptable but should be investigated.
- **Test the actual user path** (e.g., Slack → Lambda → AgentCore), not just direct invoke.
- Never say "tested successfully" based on partial checks.

### Slack End-to-End Test

After smoke test passes, manually verify the Slack integration:

1. Send a message to Plato bot in Slack
2. Verify response arrives (not an error message)
3. Send a follow-up in the same thread (verify session continuity)
4. Ask Plato to use a tool (e.g., "save this fact: I prefer Python")

If the Slack test fails but direct invoke works, check:
- Lambda `AGENTCORE_RUNTIME_ARN` env var points to the correct agent
- Lambda execution role has `bedrock-agentcore:InvokeAgentRuntime` on the new agent ARN
- Lambda timeout is sufficient (recommend 15 minutes for worker)

## Troubleshooting

Issues discovered during fresh deploy end-to-end testing (2026-04-12).

### 1. `agentcore configure --non-interactive` Generates Wrong Defaults

Running `agentcore configure -e entrypoint.py` (with or without `--non-interactive`)
produces a `.bedrock_agentcore.yaml` with incorrect defaults:

| Setting | Default | What You Need |
|---------|---------|---------------|
| Agent name | `entrypoint` (from filename) | Your chosen agent name (e.g. `plato`) |
| Auth | IAM only | JWT authorizer (required for Slack) |
| Memory mode | `STM_ONLY` | `STM_AND_LTM` (required for cross-session memory) |

**Fix**: After running `agentcore configure`, manually edit `.bedrock_agentcore.yaml`:

```yaml
agents:
  plato:  # ← fix agent name
    memory_enabled: true
    memory:
      mode: STM_AND_LTM  # ← fix memory mode
      memory_arn: arn:aws:bedrock-agentcore:us-west-2:<ACCOUNT_ID>:memory/<MEMORY_ID>
    authorizer_configuration:  # ← add JWT authorizer
      customJWTAuthorizer:
        discoveryUrl: https://cognito-idp.<REGION>.amazonaws.com/<USER_POOL_ID>/.well-known/openid-configuration
        allowedAudience:
          - <CLIENT_ID>
```

### 2. New Execution Role Missing ECR Permissions

When `agentcore configure` creates a **new** IAM execution role, it does NOT
include the ECR permissions needed to pull the container image. The deploy will
fail with image pull errors.

Missing permissions:
- `ecr:GetDownloadUrlForLayer`
- `ecr:BatchGetImage`
- `ecr:GetAuthorizationToken`

**Fix**: Attach the `AmazonEC2ContainerRegistryReadOnly` managed policy to the
execution role:

```bash
aws iam attach-role-policy \
  --role-name <EXECUTION_ROLE_NAME> \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
```

### 3. Memory Deletion Is Asynchronous

After deleting a memory resource, it stays in `DELETING` state for several
minutes. If you deploy immediately with the old `memory_id` still in your config,
the deploy or invocation will fail because the memory resource is gone but not
yet fully cleaned up.

**Fix**: Either:
- **Wait** for the deletion to complete (`aws bedrock-agentcore get-memory --memory-id <ID>`
  until it returns 404), or
- **Remove** `memory_id` / `memory_arn` from `.bedrock_agentcore.yaml` and the
  Dockerfile, deploy without memory, then create a new memory resource and
  redeploy with the new ID.

### 4. ECR Repository Naming — No Underscores

`agentcore deploy` may auto-create an ECR repository named
`bedrock-agentcore-{agent_name}`. If your agent name contains **underscores**
(e.g. `my_agent`), the ECR repo creation fails because ECR does not allow
underscores in repository names.

**Fix**: Either:
- Use **hyphens** in your agent name (e.g. `my-agent` instead of `my_agent`), or
- **Pre-create** the ECR repository with a valid name and specify it in
  `.bedrock_agentcore.yaml`:

```yaml
agents:
  my-agent:
    ecr:
      repository_name: bedrock-agentcore-my-agent
```

### 5. `.bedrock_agentcore.yaml.example` Is Incomplete

The example config shipped with the toolkit only shows minimal fields. For a
production Slack deployment, you need JWT authorizer, memory, observability, and
ECR config. See the [JWT Authorizer](#jwt-authorizer) and
[Memory Configuration](#memory-configuration) sections above for the full
structure, or refer to the project's `.bedrock_agentcore.yaml.example` which
includes a complete template with all sections.
