"""Deployment configuration templates for Amazon Bedrock AgentCore.

Each template is a string constant with ``{placeholder}`` markers for
project-specific values.  Templates follow AWS best practices and the
platform readiness checklist (C1–C12).

Placeholders used across templates:
  - ``{project_name}``   — agent project name (e.g. ``my_agent``)
  - ``{aws_account_id}`` — 12-digit AWS account ID
  - ``{aws_region}``     — AWS region (e.g. ``us-east-1``)
  - ``{ecr_repo_name}``  — ECR repository name
  - ``{s3_bucket_name}`` — S3 bucket for agent artifacts (optional)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# IAM Policy — least-privilege for agent runtime
# ---------------------------------------------------------------------------

IAM_POLICY_JSON = """\
{{
  "Version": "2012-10-17",
  "Statement": [
    {{
      "Sid": "BedrockModelInvocation",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:{aws_region}::foundation-model/*"
    }},
    {{
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:{aws_region}:{aws_account_id}:log-group:/agentcore/{project_name}:*"
    }},
    {{
      "Sid": "S3ArtifactAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::{s3_bucket_name}",
        "arn:aws:s3:::{s3_bucket_name}/*"
      ]
    }},
    {{
      "Sid": "SecretsManagerReadOnly",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:{aws_region}:{aws_account_id}:secret:{project_name}/*"
    }}
  ]
}}
"""

# ---------------------------------------------------------------------------
# buildspec.yml — CodeBuild for AgentCore container
# ---------------------------------------------------------------------------

BUILDSPEC_YML = """\
version: 0.2

env:
  variables:
    ECR_REPO_NAME: "{ecr_repo_name}"
    AWS_DEFAULT_REGION: "{aws_region}"
  parameter-store:
    AWS_ACCOUNT_ID: "/agentcore/{project_name}/aws-account-id"

phases:
  pre_build:
    commands:
      - echo Logging in to Amazon ECR...
      - aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com
      - REPOSITORY_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/$ECR_REPO_NAME
      - COMMIT_HASH=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c 1-7)
      - IMAGE_TAG=${{COMMIT_HASH:=latest}}
  build:
    commands:
      - echo Building Docker image...
      - docker build -t $REPOSITORY_URI:latest .
      - docker tag $REPOSITORY_URI:latest $REPOSITORY_URI:$IMAGE_TAG
  post_build:
    commands:
      - echo Pushing Docker image to ECR...
      - docker push $REPOSITORY_URI:latest
      - docker push $REPOSITORY_URI:$IMAGE_TAG
      - printf '[{{"name":"{project_name}","imageUri":"%s"}}]' $REPOSITORY_URI:$IMAGE_TAG > imagedefinitions.json

artifacts:
  files:
    - imagedefinitions.json
"""

# ---------------------------------------------------------------------------
# CDK Stack — Python CDK for AgentCore Runtime deployment
# ---------------------------------------------------------------------------

CDK_STACK_PY = '''\
"""CDK stack for deploying {project_name} to Amazon Bedrock AgentCore Runtime."""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class {class_name}Stack(Stack):
    """Deploy {project_name} agent to AgentCore Runtime.

    Creates:
    - ECR repository for container images
    - IAM role with least-privilege policy
    - CloudWatch log group
    - AgentCore runtime configuration
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ECR repository for agent container images
        repository = ecr.Repository(
            self,
            "AgentRepo",
            repository_name="{ecr_repo_name}",
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                ecr.LifecycleRule(max_image_count=10, description="Keep last 10 images")
            ],
        )

        # CloudWatch log group
        log_group = logs.LogGroup(
            self,
            "AgentLogGroup",
            log_group_name="/agentcore/{project_name}",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # IAM role for the agent runtime
        agent_role = iam.Role(
            self,
            "AgentRole",
            assumed_by=iam.ServicePrincipal("agentcore.amazonaws.com"),
            description="IAM role for {project_name} AgentCore runtime",
        )

        # Bedrock model invocation
        agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=["arn:aws:bedrock:{aws_region}::foundation-model/*"],
            )
        )

        # CloudWatch logging
        log_group.grant_write(agent_role)

        # ECR pull access
        repository.grant_pull(agent_role)
'''

# ---------------------------------------------------------------------------
# Runtime config — AgentCore runtime settings
# ---------------------------------------------------------------------------

RUNTIME_CONFIG_YAML = """\
# AgentCore Runtime Configuration for {project_name}
# See: https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore-runtime.html

runtime:
  name: "{project_name}"
  framework: "custom"       # custom | strands | langchain | crewai

container:
  image: "{aws_account_id}.dkr.ecr.{aws_region}.amazonaws.com/{ecr_repo_name}:latest"
  port: 8080
  health_check:
    path: "/health"
    interval_seconds: 30
    timeout_seconds: 5
    healthy_threshold: 2
    unhealthy_threshold: 3

resources:
  cpu: "0.5 vCPU"
  memory: "1 GB"

scaling:
  min_instances: 1
  max_instances: 5
  target_cpu_utilization: 70

logging:
  driver: "awslogs"
  options:
    log_group: "/agentcore/{project_name}"
    region: "{aws_region}"

environment:
  AGENT_MODEL: "claude-sonnet-4-20250514"
  AGENT_PORT: "8080"
  LOG_LEVEL: "INFO"
  AWS_DEFAULT_REGION: "{aws_region}"
"""

# ---------------------------------------------------------------------------
# .env.template — documented environment variables
# ---------------------------------------------------------------------------

ENV_TEMPLATE = """\
# =============================================================================
# Environment variables for {project_name}
# Copy this file to .env and fill in the values.
# NEVER commit .env to version control.
# =============================================================================

# --- Required ---

# AWS region for Bedrock and other AWS services
AWS_DEFAULT_REGION={aws_region}

# Claude model to use for agent inference
AGENT_MODEL=claude-sonnet-4-20250514

# Port the agent HTTP server listens on
AGENT_PORT=8080

# --- Optional ---

# Logging level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO

# AgentCore Memory store endpoint (if using persistent memory)
# MEMORY_STORE_ENDPOINT=

# S3 bucket for agent artifacts
# S3_BUCKET_NAME={s3_bucket_name}

# Feature flags
# ENABLE_STREAMING=true
# ENABLE_TOOL_USE=true
"""

# ---------------------------------------------------------------------------
# Dockerfile — multi-stage, non-root, health check
# ---------------------------------------------------------------------------

DOCKERFILE = """\
# Multi-stage build for {project_name}
# Stage 1: Install dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime image
FROM python:3.11-slim

# Security: run as non-root user
RUN groupadd -r agent && useradd -r -g agent agent

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ src/

# Set ownership
RUN chown -R agent:agent /app

USER agent

ENV AGENT_PORT=8080
EXPOSE 8080

# C1/C4: Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \\
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "-m", "{project_name}.agent"]
"""

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

DEPLOYMENT_TEMPLATES: dict[str, str] = {
    "iam-policy.json": IAM_POLICY_JSON,
    "buildspec.yml": BUILDSPEC_YML,
    "cdk/app_stack.py": CDK_STACK_PY,
    "runtime-config.yaml": RUNTIME_CONFIG_YAML,
    ".env.template": ENV_TEMPLATE,
    "Dockerfile": DOCKERFILE,
}

TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "iam-policy.json": "Least-privilege IAM policy for agent runtime",
    "buildspec.yml": "CodeBuild spec for building and pushing container to ECR",
    "cdk/app_stack.py": "Python CDK stack for AgentCore runtime deployment",
    "runtime-config.yaml": "AgentCore runtime configuration (resources, scaling, env)",
    ".env.template": "Documented environment variables template",
    "Dockerfile": "Multi-stage container build with non-root user and health check",
}
