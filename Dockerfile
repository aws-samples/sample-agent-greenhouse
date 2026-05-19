FROM public.ecr.aws/docker/library/python:3.11-slim AS base

LABEL maintainer="platform-agent"
LABEL description="Platform Agent (PLAI) - multi-agent system for the agent deployment lifecycle"

WORKDIR /app

# Install system deps (curl for health check, Node.js for Claude Code CLI)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y --auto-remove gnupg && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI (npm package). Used by the `claude_code` Strands tool
# in entrypoint.py. CLI talks to Bedrock when CLAUDE_CODE_USE_BEDROCK=1 (set by
# tools/claude_code.py at subprocess time, no provider key needed inside the
# container — IAM does the auth).
RUN npm install -g @anthropic-ai/claude-code && \
    npm cache clean --force && \
    claude --version

# Tell claude-code CLI we're inside a recognized sandbox so it allows
# --permission-mode bypassPermissions while running as root. AgentCore
# Runtime containers are already isolated execution environments; the CLI's
# root-check is intended for laptops, not for sandboxed runtimes.
ENV IS_SANDBOX=1

# Copy dependency spec first for better layer caching
COPY pyproject.toml README.md requirements.txt ./
COPY src/ src/

# Install all dependencies (requirements.txt has bedrock-agentcore, strands, boto3)
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir .

# Copy entrypoint
COPY entrypoint.py ./

# Health check using the built-in health endpoint
ENV HEALTH_PORT=8080
# MEMORY_ID must be set at deploy time (via agentcore config or --build-arg)
# Do NOT hardcode — each deployment creates a new memory resource.
ENV MEMORY_ID=
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${HEALTH_PORT}/ping || exit 1

EXPOSE 8080

# Copy workspace files (personality — soul files, policies, examples)
# Skills are now in plato/skills/ domain directory, loaded via harness.
COPY workspace/ workspace/

# Entry point: Use ADOT auto-instrumentation to export OTEL spans to AgentCore/CloudWatch
# This enables X-Ray traces and GenAI observability dashboard in CloudWatch
CMD ["opentelemetry-instrument", "python", "entrypoint.py"]
