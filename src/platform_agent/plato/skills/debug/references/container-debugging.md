# Container Debugging Guide

## Table of Contents
- [Build Failures](#build-failures)
- [Startup Crashes](#startup-crashes)
- [OOM Kills](#oom-kills)
- [Image Pull Errors](#image-pull-errors)
- [Dependency Conflicts](#dependency-conflicts)
- [Port Binding Issues](#port-binding-issues)

---

## Build Failures

### Symptom: Docker build fails during pip install

**Common causes:**
1. Missing system dependencies (gcc, libffi-dev, etc.)
2. Python version mismatch
3. Private package registry auth failure

**Diagnosis:**
```bash
# Check build logs
docker build --no-cache -t agent-debug . 2>&1 | tee build.log

# Verify Python version in Dockerfile
grep "FROM python" Dockerfile

# Check if requirements have platform-specific packages
pip install --dry-run -r requirements.txt
```

**Fixes:**
- Add system deps: `RUN apt-get update && apt-get install -y gcc libffi-dev`
- Pin Python version: `FROM python:3.11-slim`
- Use `--extra-index-url` for private packages

### Symptom: Multi-stage build fails on COPY

**Cause:** File not found because build context is wrong or .dockerignore excludes it.

**Fix:**
```bash
# Check what's in the build context
docker build --no-cache -f Dockerfile . 2>&1 | head -5
# Verify .dockerignore isn't excluding needed files
cat .dockerignore
```

---

## Startup Crashes

### Symptom: Container exits immediately (exit code 1)

**Diagnosis:**
```bash
# Check container logs
aws logs get-log-events \
  --log-group-name /agentcore/agents/<agent-id> \
  --log-stream-name <stream> \
  --limit 50

# Run locally to see error
docker run --rm -it agent-image:latest
```

**Common causes:**
1. Missing environment variables
2. Import error (missing dependency)
3. Port already in use
4. Invalid configuration file

**Fixes:**
- Check required env vars are set in AgentCore config
- Run `pip check` inside container to find missing deps
- Verify port configuration matches AgentCore expectations

### Symptom: Container starts but health check fails

**Diagnosis:**
```bash
# Check health endpoint locally
curl -v http://localhost:8080/health

# Check AgentCore health check config
aws bedrock-agent get-agent --agent-id <id> \
  --query 'agent.healthCheck'
```

**Fix:** Ensure health endpoint returns 200 within timeout period.

---

## OOM Kills

### Symptom: Container killed with exit code 137

**Diagnosis:**
```bash
# Check memory usage in CloudWatch
aws cloudwatch get-metric-statistics \
  --namespace AgentCore \
  --metric-name MemoryUtilization \
  --dimensions Name=AgentId,Value=<agent-id> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Maximum
```

**Common causes:**
1. Loading large models or datasets into memory
2. Unbounded conversation history
3. Memory leak in tool execution
4. Too many concurrent requests

**Fixes:**
- Increase memory allocation in AgentCore config
- Implement conversation history truncation
- Use streaming for large responses
- Add memory monitoring with periodic gc.collect()

---

## Image Pull Errors

### Symptom: ImagePullBackOff or authentication error

**Diagnosis:**
```bash
# Verify ECR login
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

# Check image exists
aws ecr describe-images \
  --repository-name <repo> \
  --image-ids imageTag=latest
```

**Fixes:**
- Ensure ECR repository policy allows AgentCore to pull
- Check image tag exists (typos are common)
- Verify cross-region ECR access if applicable

---

## Dependency Conflicts

### Symptom: ImportError or version conflict at runtime

**Diagnosis:**
```bash
# Inside container
pip check
pip list --format=freeze | sort

# Check for conflicting boto3 versions
pip show boto3 botocore
```

**Fixes:**
- Pin all dependencies: `pip freeze > requirements.txt`
- Use `pip install --no-deps` for specific overrides
- Consider separate virtual environments for conflicting deps

---

## Port Binding Issues

### Symptom: Address already in use or connection refused

**Diagnosis:**
```bash
# Check what's listening
netstat -tlnp | grep 8080
# Or
ss -tlnp | grep 8080
```

**Fixes:**
- Use the port AgentCore assigns via environment variable
- Don't hardcode ports; use `PORT` env var
- Ensure only one process binds to the port
