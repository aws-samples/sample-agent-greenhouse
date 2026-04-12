# Platform Readiness Checklist (C1-C12)

Complete reference for all 12 platform readiness checks used by the
Design Advisor to assess agent applications for AgentCore deployment.

## Table of Contents

- [BLOCKER Checks (C1-C2)](#blocker-checks)
- [WARNING Checks (C3, C4, C5, C8, C9, C11)](#warning-checks)
- [INFO Checks (C6, C7, C10, C12)](#info-checks)
- [Scoring Rules](#scoring-rules)
- [Auto-Fix Suggestions](#auto-fix-suggestions)

## BLOCKER Checks

Failure on any blocker = NOT READY for deployment.

### C1 — Containerizable

**What**: The application must be containerizable (Dockerfile present or generatable).

**Check for**:
- `Dockerfile` in project root
- `docker-compose.yml` or `docker-compose.yaml`
- Standard project structure (pyproject.toml + src/ or main.py)

**Pass criteria**: Dockerfile exists OR project structure allows auto-generation.

**Auto-fix**: Generate a multi-stage Dockerfile:
```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

FROM python:3.11-slim
RUN useradd -r agent
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .
USER agent
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"
CMD ["python", "-m", "agent"]
```

### C2 — No Hardcoded Secrets

**What**: No API keys, passwords, tokens, or credentials in source code.

**Check for** (grep patterns):
- `sk-[a-zA-Z0-9]{20,}` (OpenAI keys)
- `AKIA[A-Z0-9]{16}` (AWS access keys)
- `ghp_[a-zA-Z0-9]{36}` (GitHub tokens)
- Variables: `*_KEY`, `*_SECRET`, `*_PASSWORD`, `*_TOKEN` with string literals
- `.env` files NOT in `.gitignore`

**Pass criteria**: Zero hardcoded secrets found across ALL source files.

**Auto-fix**: Replace with environment variable lookups:
```python
# Before (FAIL)
api_key = "sk-proj-abc123..."

# After (PASS)
api_key = os.environ["OPENAI_API_KEY"]
```

## WARNING Checks

Should fix before deployment, but not blockers.

### C3 — Environment-Based Config

**What**: Configuration from environment variables, not hardcoded values.

**Check for**: Hardcoded hostnames, ports, URLs, model names, region names.

**Pass criteria**: All configurable values come from `os.environ`, `os.getenv()`,
or a config file that reads from environment.

### C4 — Health Check Endpoint

**What**: HTTP endpoint for container health monitoring.

**Check for**: Routes matching `/health`, `/healthz`, `/ready`, `/ping`.

**Pass criteria**: At least one health endpoint exists and returns 200 OK.

**Auto-fix**: Add health endpoint:
```python
@app.get("/health")
async def health():
    return {"status": "healthy"}
```

### C5 — Stateless Design

**What**: No local filesystem for persistent state.

**Check for**: SQLite usage, JSON file writes for state, pickle files,
local databases, session files.

**Pass criteria**: No local state persistence. Temporary files for processing OK.

**Exception**: Apps using AgentCore Memory SDK are compliant.

### C8 — Error Handling

**What**: Robust error handling throughout the application.

**Check for**:
- Bare `except:` clauses (should catch specific exceptions)
- Tool/API calls wrapped in try/except
- Meaningful error messages
- No silently swallowed exceptions

**Pass criteria**: No bare except, all external calls have error handling.

### C9 — Dependency Management

**What**: Dependencies specified with version pins.

**Check for**: `pyproject.toml`, `requirements.txt`, `setup.py`, `Pipfile`.

**Pass criteria**: Dependency file exists with version pins (not `package>=0`).

### C11 — MCP Tool Safety

**What**: Safe tool definitions without code injection risks.

**Check for**:
- `eval()` or `exec()` on user input
- Missing input validation on tool parameters
- Arbitrary code execution without sandboxing

**Pass criteria**: No unsafe eval/exec, all tool inputs validated.

## INFO Checks

Nice to have, not required for deployment.

### C6 — Graceful Shutdown

**What**: Handles SIGTERM for zero-downtime deploys.

**Check for**: Signal handlers, framework shutdown hooks.

### C7 — Logging to stdout

**What**: Logs to stdout/stderr for CloudWatch integration.

**Check for**: Logging config, no local log files.

### C10 — Agent Framework Compatibility

**What**: Uses a supported agent framework.

**Supported frameworks**: Claude Agent SDK, Strands, LangGraph, LangChain,
CrewAI, PydanticAI.

### C12 — Memory Pattern

**What**: If persistent state needed, uses compatible pattern.

**Compatible patterns**: AgentCore Memory SDK, external database (DynamoDB,
RDS), API-based state store.

## Scoring Rules

| Result | Condition |
|--------|-----------|
| ✅ READY | 0 blockers, ≤2 warnings |
| ⚠️ NEEDS WORK | 0 blockers, >2 warnings |
| ❌ NOT READY | 1+ blockers |

## Auto-Fix Suggestions

Each failing check should include a specific, implementable fix:
1. Which file to modify
2. What code to add/change
3. Example of the correct pattern

The deployment_config skill can auto-generate fixes for C1 (Dockerfile),
C4 (health check), C6 (SIGTERM handler), and C7 (logging config).
