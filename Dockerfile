FROM public.ecr.aws/docker/library/python:3.11-slim AS base

LABEL maintainer="platform-agent"
LABEL description="Platform Agent (PLAI) - multi-agent system for the agent deployment lifecycle"

WORKDIR /app

# Install system deps (none needed beyond Python stdlib for core)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

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

# Copy workspace files (personality, skills)
COPY workspace/ workspace/

# Entry point: Use ADOT auto-instrumentation to export OTEL spans to AgentCore/CloudWatch
# This enables X-Ray traces and GenAI observability dashboard in CloudWatch
CMD ["opentelemetry-instrument", "python", "entrypoint.py"]
