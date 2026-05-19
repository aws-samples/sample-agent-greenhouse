# Security Policy

## Reporting a vulnerability

If you discover a potential security issue in this project, please notify
AWS Security via our [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/).

Please do **not** create a public GitHub issue for security vulnerabilities.

---

## Secret-handling policy

> **Hard rule.** No plaintext credentials, tokens, or signing secrets are
> permitted in this repository, in container images, or in deployed
> resource configurations (Lambda env vars, ECS task defs, AgentCore
> runtime env). Every credential lives in AWS SSM Parameter Store as a
> `SecureString` and is fetched at cold-start by the workload's IAM role.

### Canonical SSM paths

| Secret | SSM path | Type | Used by |
|---|---|---|---|
| Slack bot token (`xoxb-…`) | `/plato/slack/bot-token` | SecureString | `plato-slack-worker` Lambda, `plato-slack-ack` Lambda |
| Slack signing secret | `/plato/slack/signing-secret` | SecureString | `plato-slack-ack` Lambda (request signature verify) |
| Cognito user-pool ID | `/plato/cognito/user-pool-id` | String | `plato-slack-worker`, `entrypoint.py` |
| Cognito client ID | `/plato/cognito/client-id` | String | `plato-slack-worker`, `entrypoint.py` |
| Cognito client secret | `/plato/cognito/client-secret` | SecureString | `plato-slack-worker` (token exchange) |
| Cognito user passwords (test) | `/plato/cognito/users/{username}/password` | SecureString | smoke-test scripts only |
| GitHub PAT (Plato runtime) | `/plato/github/pat` | SecureString | AgentCore container (`entrypoint.py`) |
| GitHub PAT (legacy alias) | `/plato/github/token` | SecureString | runtime — kept for back-compat with Dockerfile |

The migration tool `scripts/grant_lambda_ssm.sh` provisions SSM read +
KMS decrypt to `plato-slack-lambda-role`. After running it,
`scripts/strip_lambda_inline_secrets.sh` removes plaintext secrets from
Lambda environment variables.

### Authoritative reading rules

- **Lambda code** (`src/platform_agent/slack/handler.py`,
  `src/platform_agent/slack/cognito_exchange.py`) reads via
  `SlackConfig.from_ssm()` / `CognitoConfig.from_ssm()`. The boot path
  honours `PLATO_SLACK_CONFIG_SOURCE`:
  - `ssm` — production. SSM-only, fail-closed if SSM unavailable.
  - `ssm_fallback` — migration mode. SSM-first, env-var fallback.
  - `env` — local dev only. Never used in production.
- **AgentCore container** (`entrypoint.py`) loads `GITHUB_TOKEN` from
  `/plato/github/token` at cold-start.
- **Smoke tests** (`scripts/smoke_privacy_two_gate.py`) read Cognito user
  passwords from `/plato/cognito/users/<u>/password` only. Never embed
  real passwords in source.

### What is forbidden

The repo lint (`scripts/lint_no_inline_secrets.sh`, also wired into a
pre-commit hook and the `security-lint` GitHub Actions job) blocks the
following patterns from being committed:

- Slack bot/user tokens: `xoxb-…`, `xoxp-…`
- GitHub fine-grained PATs: `github_pat_…`
- GitHub classic PATs: `ghp_…`, `gho_…`, `ghu_…`, `ghs_…`, `ghr_…`
- AWS access keys: `AKIA[A-Z0-9]{16}`, `ASIA[A-Z0-9]{16}`
- OpenAI keys: `sk-[A-Za-z0-9]{20,}`
- Generic `*_TOKEN=`/`*_SECRET=` assignments with non-empty literal
  RHS in `*.env`, `*.yaml`, `*.json`, `*.sh`, `*.py`.
- Inline `Environment.Variables` assignments to those keys in
  Lambda/CloudFormation/SAM/CDK templates.

### Allowlist

If a hit is a genuine fixture (e.g. `tests/fixtures/`) and not a
real credential, append the offending `path:pattern` line to
`.security-allowlist`. Reviewers must look at every new allowlist entry
on the PR.

## Rotation procedure

When a secret is suspected to be leaked, follow this order:

1. **Issue a new credential** (Slack: rotate via Slack admin UI; GitHub:
   create a new fine-grained PAT with identical scopes, do not delete
   the old one yet; Cognito: `aws cognito-idp update-user-pool-client
   --client-id … --generate-secret …` _or_ rotate via CDK/Terraform).
2. **Write the new value to SSM**:
   ```bash
   aws ssm put-parameter --name /plato/slack/bot-token \
       --type SecureString --value "$NEW_TOKEN" \
       --region us-west-2 --overwrite
   ```
3. **Invalidate the running Lambda's cached credential** by forcing a
   fresh container (env update no-op):
   ```bash
   aws lambda update-function-configuration \
       --function-name plato-slack-worker \
       --environment 'Variables={PLATO_SLACK_CONFIG_SOURCE=ssm,...}'
   ```
4. **Smoke test** end-to-end (`scripts/smoke_privacy_two_gate.py`).
5. **Revoke the old credential** at the source (Slack/GitHub/Cognito).

The Cognito client secret rotation is automatable and is the only one
the agent fleet can self-service — Slack and GitHub require human
operator action in their respective web UIs.

## Defence-in-depth controls

- AgentCore Memory namespaces are per-actor. `recall_memory` post-filters
  results that don't begin with the caller's actor namespace prefix and
  logs `MEMORY LEAK BLOCKED` at ERROR level if anything is dropped. See
  `src/platform_agent/memory.py`.
- The Plato runtime requires JWT auth via Cognito (`customJWTAuthorizer`).
  IAM-only invocation paths still require an actor identity in the
  payload. Calls without a real identity refuse to read long-term
  memory.
- The Slack worker dedups events via DynamoDB (`plato-slack-dedup`,
  7-day TTL) so that a leaked Slack URL replay can't mint additional
  agent invocations.
