# Troubleshooting Guide

Common deployment failures, error messages, and fixes for AgentCore.

## Table of Contents

- [Container Failures](#container-failures)
- [IAM and Permissions](#iam-and-permissions)
- [Runtime Errors](#runtime-errors)
- [Health Check Failures](#health-check-failures)
- [Memory and Performance](#memory-and-performance)

## Container Failures

### "exec format error"

**Cause**: Image built for wrong architecture (e.g., ARM image on x86).

**Fix**: Build with `--platform linux/amd64`:
```bash
docker build --platform linux/amd64 -t my-agent .
```

### "OCI runtime create failed"

**Cause**: Invalid Dockerfile CMD or ENTRYPOINT.

**Fix**: Ensure CMD uses exec form:
```dockerfile
# Wrong
CMD python agent.py

# Right
CMD ["python", "-m", "agent"]
```

### "no space left on device"

**Cause**: Docker image too large (multi-GB).

**Fix**: Use multi-stage builds, slim base images:
```dockerfile
FROM python:3.11-slim AS builder
# ... build stage

FROM python:3.11-slim
# ... only copy what's needed
```

## IAM and Permissions

### "AccessDeniedException: User is not authorized to perform bedrock:InvokeModel"

**Cause**: IAM role missing Bedrock permissions.

**Fix**: Add to IAM policy:
```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
  "Resource": "arn:aws:bedrock:*:*:model/*"
}
```

### "AccessDeniedException: ... secrets"

**Cause**: Agent trying to read Secrets Manager without permission.

**Fix**: Add specific secret ARN to policy:
```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "arn:aws:secretsmanager:REGION:ACCOUNT:secret:SECRET_NAME-*"
}
```

### "AssumeRoleAccessDenied"

**Cause**: Trust policy doesn't allow the AgentCore service to assume the role.

**Fix**: Update trust policy:
```json
{
  "Effect": "Allow",
  "Principal": {"Service": "agentcore.amazonaws.com"},
  "Action": "sts:AssumeRole"
}
```

## Runtime Errors

### "ModuleNotFoundError"

**Cause**: Dependency not installed in container.

**Fix**: Ensure all deps are in pyproject.toml and Dockerfile installs them:
```dockerfile
COPY pyproject.toml .
RUN pip install --no-cache-dir .
```

### "Connection refused" on tool calls

**Cause**: Tool endpoint not reachable from container.

**Fix**: Use environment variables for endpoints, ensure network access:
```python
endpoint = os.getenv("TOOL_ENDPOINT", "https://api.example.com")
```

### Agent timeout

**Cause**: Agent taking too long to respond (default 30s).

**Fix**: Increase timeout in runtime config, optimize agent logic,
add streaming for long operations.

## Health Check Failures

### Container marked unhealthy

**Cause**: Health endpoint not responding within timeout.

**Fix checklist**:
1. Verify health endpoint exists and returns 200
2. Check the endpoint path matches HEALTHCHECK directive
3. Ensure the agent starts serving before health check interval
4. Add a startup grace period if initialization is slow

### Health check passes locally but fails in AgentCore

**Cause**: Different network config, port binding.

**Fix**: Bind to `0.0.0.0`, not `127.0.0.1`:
```python
# Wrong
app.run(host="127.0.0.1", port=8080)

# Right
app.run(host="0.0.0.0", port=8080)
```

## Memory and Performance

### OOM (Out of Memory) kill

**Cause**: Container exceeding memory limit.

**Fix**:
1. Increase memory in runtime config
2. Use streaming instead of loading full responses
3. Clean up resources after tool calls
4. Profile memory usage with `tracemalloc`

### High latency on first request

**Cause**: Cold start — model loading, dependency imports.

**Fix**:
1. Keep container warm with min instances > 0
2. Lazy-load heavy dependencies
3. Pre-warm in container startup
