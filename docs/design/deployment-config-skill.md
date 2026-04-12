# Deployment Config Skill — Design Document

## Purpose

The `deployment_config` skill pack augments the Foundation Agent with deployment
configuration generation capabilities for Amazon Bedrock AgentCore. When loaded,
the agent becomes a "Deployment Config Specialist" that can generate all files
needed to take an agent app from development to production on AgentCore.

**Core question this skill answers:** "What deployment configuration do I need
to get my agent app running on Amazon Bedrock AgentCore?"

## Developer Pain Points Addressed

1. **"What infrastructure do I need?"** — Developers shouldn't have to piece
   together IAM policies, CDK stacks, and runtime configs from scattered docs.
   The Deployment Config skill generates it all.
2. **"Is my IAM policy too permissive?"** — Least-privilege IAM policies are
   hard to write from scratch. Generated policies grant only what's needed.
3. **"How do I set up CI/CD?"** — buildspec.yml for CodeBuild, ready to go.
4. **"What env vars does AgentCore expect?"** — Documented .env.template with
   all required and optional environment variables.

## Integration with Design Advisor

Before generating deployment configs, the skill encourages running a Design
Advisor readiness check. This ensures the app meets platform requirements
(C1–C12) before generating deployment artifacts. The workflow is:

```
1. Run Design Advisor readiness check on the agent app
2. Fix any BLOCKER issues
3. Generate deployment configs with Deployment Config skill
```

## What Gets Generated

| File | Purpose | Details |
|------|---------|---------|
| `Dockerfile` | Container image build | Multi-stage, non-root user, health check, layer caching |
| `buildspec.yml` | CI/CD pipeline | CodeBuild spec for building and pushing to ECR |
| `iam-policy.json` | IAM permissions | Least-privilege policy for agent runtime |
| `cdk/app_stack.py` | Infrastructure as Code | Python CDK stack for AgentCore runtime deployment |
| `runtime-config.yaml` | Runtime settings | AgentCore runtime configuration (resources, scaling, env) |
| `.env.template` | Environment variables | Documented template of required/optional env vars |

### Dockerfile

- Multi-stage build for smaller image size
- Non-root user for security
- HEALTHCHECK directive for container orchestration
- Layer caching: copy dependency spec first, install, then copy source
- python:3.11-slim base image

### buildspec.yml (CodeBuild)

- Three phases: pre_build (ECR login), build (Docker build + tag), post_build (push)
- Uses environment variables for AWS account, region, ECR repo
- Produces `imagedefinitions.json` artifact for downstream deployment

### IAM Policy

- Least-privilege: only permissions the agent needs at runtime
- `bedrock:InvokeModel` / `bedrock:InvokeModelWithResponseStream` for model calls
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch
- Optional S3 access scoped to a specific bucket
- Optional Secrets Manager access for API keys
- No `*` resources unless absolutely necessary (e.g., log group creation)

### CDK Stack

- Python CDK stack that deploys to AgentCore Runtime
- ECR repository for container images
- IAM role with the generated least-privilege policy
- AgentCore runtime resource configuration
- Environment variable injection from SSM/Secrets Manager

### Runtime Config

- Resource limits (CPU, memory)
- Scaling configuration (min/max instances)
- Health check settings (path, interval, timeout)
- Logging configuration
- Network settings

### .env.template

- Required variables: AWS region, model ID, agent port
- Optional variables: log level, memory store endpoint, feature flags
- Each variable documented with description and example value

## System Prompt Extension

The deployment_config skill injects a comprehensive system prompt that teaches
the agent:

1. When and how to generate each deployment artifact
2. Dockerfile best practices for agent containers
3. IAM least-privilege principles for agent workloads
4. CDK patterns for AgentCore deployment
5. Runtime configuration options and defaults
6. CI/CD pipeline structure with CodeBuild
7. How to customize templates based on the agent's specific needs

See the implementation in `src/platform_agent/skills/deployment_config/__init__.py`
for the complete prompt text.

## Template Implementation

Templates are implemented as Python string constants in
`src/platform_agent/skills/deployment_config/templates.py`. Each template uses
`{placeholder}` markers for project-specific values.

This approach was chosen (matching the scaffold skill pattern) for:
- **Simplicity** — No file I/O or path resolution needed
- **Testability** — Templates can be imported and validated in unit tests
- **Portability** — Skill is self-contained in a single package

Placeholder markers used:
- `{project_name}` — The agent project name
- `{aws_account_id}` — AWS account ID
- `{aws_region}` — AWS region (e.g., us-east-1)
- `{ecr_repo_name}` — ECR repository name
- `{s3_bucket_name}` — S3 bucket for agent artifacts (optional)

## Evaluation Criteria

**Test cases** (minimum for MVP):

1. **Registration** — DeploymentConfigSkill registers correctly in skill registry
2. **System prompt** — Extension covers IAM, Docker, CDK, runtime topics
3. **IAM policy validity** — Template is valid JSON
4. **buildspec validity** — Template is valid YAML
5. **IAM least-privilege** — No `*` in Action fields, scoped resources
6. **Placeholder markers** — All templates have substitution placeholders
7. **FoundationAgent integration** — Skill loads onto agent correctly

**Quality metrics:**
- Generated IAM policies should follow least-privilege
- Generated Dockerfiles should follow container best practices
- All JSON templates should be parseable
- All YAML templates should be parseable

## Integration with Other Skills

The deployment_config skill works in concert with other platform skills:

- **design_advisor** — Run before generating configs to verify readiness
- **scaffold** — Scaffold generates the app; deployment_config generates the infra
- **code_review** — Review generated configs for security issues

Typical workflow:
```
plato scaffold "weather lookup agent with API integration"
→ Generates basic-agent project

plato review ./my-weather-agent
→ Design Advisor confirms READY rating

plato deploy-config ./my-weather-agent
→ Generates AgentCore deployment configuration
```
