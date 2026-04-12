# Plato Platform Guide — Claude Code Skill

> Install this skill in Claude Code to automatically follow platform best practices
> when building agent applications for Amazon Bedrock AgentCore.

## Trigger

Activate this skill when:
- Creating a new agent application or project skeleton
- Writing agent code that will deploy to Amazon Bedrock AgentCore
- Reviewing or refactoring agent code for platform readiness
- Setting up deployment configurations (Dockerfile, IAM, CDK, CI/CD)
- The user mentions "platform", "AgentCore", "deploy", "Plato", or "platform readiness"

## Platform Architecture

Plato (Platform as Agent) uses the **Foundation Agent + Skills** pattern:

- **Foundation Agent**: Base agent with file I/O, shell, and core capabilities
- **Skill Packs**: Domain extensions that add system prompt + tools to create specialists
- **Orchestrator**: Routes requests to the right specialist agent (agent-as-tool pattern)
- **Framework**: Claude Agent SDK (`claude-agent-sdk` package)
- **Runtime**: Amazon Bedrock AgentCore

### Specialist Agents

| Agent | Role | Tools |
|-------|------|-------|
| `design_advisor` | Platform readiness assessment (12-item checklist) | Read, Glob, Grep |
| `scaffold` | Generate project skeletons from templates | Read, Write, Edit, Bash, Glob |
| `code_review` | Security, quality, and agent-pattern review | Read, Glob, Grep |
| `deployment_config` | Generate deploy artifacts (IAM, CDK, buildspec) | Read, Write, Edit, Bash, Glob, Grep |

## Platform Readiness Checklist

When building or reviewing an agent app, check every item below. This is the same
checklist used by the platform's Design Advisor skill.

### 🔴 BLOCKER (must pass — blocks deployment)

**C1 — Containerizable**
- ✅ Include a `Dockerfile` in the project root
- ✅ Use `python:3.11-slim` as base image (not alpine — C extension issues)
- ✅ Multi-stage build: builder stage for `pip install`, slim runtime stage
- ✅ Include `HEALTHCHECK` directive using Python's urllib:
  ```dockerfile
  HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
      CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1
  ```
- ✅ Run as non-root user (`RUN groupadd -r agent && useradd -r -g agent agent`)
- ✅ `EXPOSE 8080` and set `ENV AGENT_PORT=8080`
- ✅ Layer caching: copy `pyproject.toml` first → install → then copy source

**C2 — No Hardcoded Secrets**
- ❌ NEVER put API keys, passwords, or tokens in source code
- ❌ NEVER commit `.env` files — add `.env` to `.gitignore`
- ✅ All secrets via `os.getenv()` with clear variable names
- ✅ Use AWS Secrets Manager for production secrets
- ✅ Check for patterns: `sk-*`, `AKIA*`, `ghp_*`, `password=`, `token=`
- ✅ Search ALL files (including tests, configs, notebooks)

### 🟡 WARNING (should fix before deployment)

**C3 — Environment-based Config**
- ✅ All configuration via environment variables: `os.getenv("VAR_NAME", "default")`
- ❌ No hardcoded hostnames, ports, URLs, model names, region names
- ✅ Provide `.env.template` with documented variables and example values

**C4 — Health Check Endpoint**
- ✅ HTTP `GET /health` returning `{"status": "healthy"}` with 200 OK
- ✅ Use stdlib `http.server` (no external dependencies for health check)
- ✅ Health server runs on port from `HEALTH_PORT` env var (default 8080)

**C5 — Stateless Design**
- ❌ No SQLite databases, local JSON state files, or pickle files for persistent data
- ❌ No local filesystem for session data or conversation history
- ✅ Temporary files for processing are OK (cleaned up after use)
- ✅ Use AgentCore Memory API for persistent state (see C12)

**C8 — Error Handling**
- ❌ No bare `except:` clauses — always catch specific exceptions
- ✅ All tool calls and API calls wrapped in try/except
- ✅ Meaningful error messages returned to users (not raw stack traces)
- ✅ Use Python `logging` module, not `print()` for errors
- ❌ No silently swallowed exceptions

**C9 — Dependency Management**
- ✅ `pyproject.toml` with pinned version ranges:
  ```toml
  dependencies = [
      "claude-agent-sdk>=0.1,<1.0",
      "aiohttp>=3.9,<4.0",
  ]
  ```
- ❌ No unpinned dependencies (`package` without version)
- ✅ Include dev dependencies separately: `[project.optional-dependencies] dev = [...]`

**C11 — MCP Tool Safety**
- ❌ No `eval()` or `exec()` on user-provided input
- ❌ No `subprocess.run()` with unsanitized user input
- ✅ Validate all tool inputs against expected types/ranges
- ✅ Validate file paths to prevent path traversal (`../../../etc/passwd`)
- ✅ Document tool side effects in tool descriptions

### 🟢 INFO (nice to have — shows maturity)

**C6 — Graceful Shutdown**
- ✅ Handle `SIGTERM` for zero-downtime deploys:
  ```python
  import signal
  def handle_sigterm(signum, frame):
      logger.info("Received SIGTERM, shutting down gracefully...")
      # Clean up resources
      sys.exit(0)
  signal.signal(signal.SIGTERM, handle_sigterm)
  ```

**C7 — Logging to stdout**
- ✅ Configure logging to stdout for CloudWatch integration:
  ```python
  import logging, sys
  logging.basicConfig(
      level=os.getenv("LOG_LEVEL", "INFO"),
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
      stream=sys.stdout,
  )
  ```
- ❌ No local log files — CloudWatch collects from stdout/stderr

**C10 — Agent Framework Compatibility**
- ✅ Use a supported framework: Claude Agent SDK, Strands, LangGraph, LangChain,
  CrewAI, PydanticAI
- ✅ Follow the Foundation Agent + Skills pattern when using Claude Agent SDK

**C12 — Memory Pattern**
- ✅ If the agent needs persistent state, use AgentCore Memory API:
  ```python
  from platform_agent.memory import create_memory_store
  store = create_memory_store()  # auto-selects backend
  await store.put("session-1", "context", {"summary": "..."})
  result = await store.get("session-1", "context")
  ```
- ✅ `InMemoryStore` for local dev, `AgentCoreMemoryStore` for production
- ✅ Set `PLATO_MEMORY_BACKEND=agentcore` and `AGENTCORE_MEMORY_ID=<id>` in production

## Project Structure

Follow this standard layout for agent projects:

```
my-agent/
├── pyproject.toml           # Dependencies + project metadata
├── Dockerfile               # Container build (multi-stage, non-root)
├── .gitignore               # Exclude .env, __pycache__, etc.
├── .env.template            # Documented env vars (NOT .env)
├── README.md                # Setup + deployment instructions
├── src/
│   └── my_agent/
│       ├── __init__.py
│       ├── agent.py         # Foundation Agent entry point + HTTP server
│       ├── health.py        # Stdlib health check (GET /health)
│       ├── orchestrator.py  # (if multi-agent) Routes to specialists
│       └── skills/          # (if multi-agent) Skill pack modules
│           ├── __init__.py
│           └── my_skill.py
├── tests/
│   ├── __init__.py
│   └── test_agent.py
├── cdk/                     # (optional) CDK deployment stack
│   └── app_stack.py
├── buildspec.yml            # (optional) CodeBuild CI/CD
├── runtime-config.yaml      # (optional) AgentCore runtime settings
└── iam-policy.json          # (optional) Least-privilege IAM policy
```

## Code Patterns

### Foundation Agent Setup

```python
from claude_agent_sdk import ClaudeAgentOptions, query

SYSTEM_PROMPT = """You are a helpful agent. [Your agent's purpose here]"""

agent_options = ClaudeAgentOptions(
    model=os.getenv("AGENT_MODEL", "claude-sonnet-4-20250514"),
    system_prompt=SYSTEM_PROMPT,
    allowed_tools=["Read", "Glob", "Grep"],  # Explicit tool list
    max_turns=int(os.getenv("MAX_TURNS", "50")),
)

async for event in query(prompt=user_input, options=agent_options):
    # Handle streaming events
    pass
```

### Skill Pack Pattern

```python
from platform_agent.skills.base import SkillPack
from platform_agent.skills import register_skill

class MySkill(SkillPack):
    name = "my_skill"
    description = "What this skill does"
    system_prompt_extension = "Detailed instructions for the agent..."
    tools = ["Read", "Glob", "Grep"]  # Tools this skill needs

    def configure(self) -> None:
        pass  # Optional setup logic

register_skill("my_skill", MySkill)
```

### HTTP Server with Health Check

```python
from aiohttp import web

async def health_handler(request):
    return web.json_response({"status": "healthy"})

async def agent_handler(request):
    data = await request.json()
    # Process with Foundation Agent
    return web.json_response({"response": result})

app = web.Application()
app.router.add_get("/health", health_handler)
app.router.add_post("/api/agent", agent_handler)
web.run_app(app, port=int(os.getenv("AGENT_PORT", "8080")))
```

### IAM Policy (Least Privilege)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockModelInvocation",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-1:ACCOUNT_ID:log-group:/agentcore/my-agent:*"
    }
  ]
}
```

## Scoring

After checking all items, determine the overall readiness:

| Rating | Criteria | Action |
|--------|----------|--------|
| **READY** ✅ | 0 blockers, ≤2 warnings | Deploy to AgentCore |
| **NEEDS WORK** ⚠️ | 0 blockers, >2 warnings | Fix warnings first |
| **NOT READY** ❌ | 1+ blockers | Must fix blockers before proceeding |

## CLI Commands

```bash
# Check platform readiness (design_advisor skill, 12-item C1-C12 checklist)
plato readiness /path/to/agent
plato readiness /path/to/agent --verbose

# Code review (security, quality, agent patterns)
plato review /path/to/agent
plato review /path/to/agent --focus security    # security | quality | patterns | all

# Scaffold a new agent project
plato scaffold "A weather lookup agent with API integration"
plato scaffold "Multi-agent orchestrator" --template multi-agent -o ./new-project

# Generate deployment configurations (IAM, Dockerfile, CDK, buildspec)
plato deploy-config /path/to/agent --target agentcore   # agentcore | ecs | lambda

# Multi-skill orchestration (routes to appropriate specialist)
plato orchestrate "Review this repo and generate deployment configs"

# Interactive chat with optional skills
plato chat --skill design_advisor --skill code_review

# List available skill packs
plato list-skills
```

## Key References

- [Claude Agent SDK docs](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html)
- [AWS Well-Architected Framework — Security Pillar](https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/)
- Platform source: `https://github.com/aws-samples/sample-agent-greenhouse`
