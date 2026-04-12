# Scaffold Skill — Design Document

## Purpose

The `scaffold` skill pack augments the Foundation Agent with project generation
capabilities. When loaded, the agent becomes a "Project Scaffolder" that can create
complete, runnable agent project skeletons following platform best practices.

**Core question this skill answers:** "Give me a working starting point for my agent
project that already follows all platform requirements."

## Developer Pain Points Addressed

1. **"How do I structure my agent project?"** — Developers shouldn't have to reverse-
   engineer project structure from documentation. The Scaffold skill generates it.
2. **"What boilerplate do I need?"** — Dockerfile, health checks, logging setup,
   graceful shutdown — all included from the start.
3. **"Will this pass platform checks?"** — Generated projects are designed to achieve
   a READY rating from the Design Advisor skill (0 blockers, ≤2 warnings).

## Template Types

The Scaffold skill supports four project templates, each targeting a different
agent architecture:

| Template | Description | Use Case |
|----------|-------------|----------|
| `basic-agent` | Single Foundation Agent with health check and HTTP server | Simple assistants, single-purpose agents |
| `multi-agent` | Orchestrator + specialist sub-agents with skill packs | Complex workflows, multi-domain tasks |
| `rag-agent` | Agent with retrieval-augmented generation pattern | Knowledge-base Q&A, document search |
| `tool-agent` | Agent with custom MCP tool server integration | External API integration, tool-heavy workflows |

## What Gets Generated

### All Templates (Common Files)

| File | Purpose | Platform Check |
|------|---------|----------------|
| `pyproject.toml` | Project metadata, dependencies with pinned versions | C9 |
| `Dockerfile` | Multi-stage container build with HEALTHCHECK | C1 |
| `src/{name}/agent.py` | Foundation Agent entry point with HTTP server | C10 |
| `src/{name}/health.py` | Stdlib HTTP health check on `/health` | C4 |
| `tests/test_agent.py` | Basic test scaffold | — |
| `README.md` | Project overview, setup, deployment instructions | — |
| `.gitignore` | Python + env file exclusions | C2 (prevents .env commits) |

### basic-agent Template

The minimal viable agent project. Generates:
- Foundation Agent with environment-based config (C3)
- Logging to stdout (C7)
- Graceful SIGTERM handling (C6)
- Proper error handling (C8)

### multi-agent Template (extends basic-agent)

Adds multi-agent orchestration:
- `src/{name}/orchestrator.py` — Supervisor that routes to specialists
- `src/{name}/skills/` — Skills directory with example skill pack
- `src/{name}/skills/__init__.py` — Skill registry
- `src/{name}/skills/example_skill.py` — Example skill following SkillPack pattern
- Agent-as-tool pattern for sub-agent delegation

### rag-agent Template (extends basic-agent)

Adds retrieval-augmented generation:
- `src/{name}/retriever.py` — Document retrieval interface
- `src/{name}/embeddings.py` — Embedding generation utilities
- Memory store integration for context persistence (C12)

### tool-agent Template (extends basic-agent)

Adds MCP tool integration:
- `src/{name}/tools/` — Custom tool directory
- `src/{name}/tools/server.py` — MCP tool server skeleton
- Input validation for tool arguments (C11)

## Platform Readiness Criteria

Generated projects must satisfy the Design Advisor checklist at a READY rating:

**BLOCKER checks (guaranteed pass):**
- C1 ✅ Containerizable — Dockerfile included with HEALTHCHECK
- C2 ✅ No hardcoded secrets — All secrets via env vars, .gitignore excludes .env

**WARNING checks (guaranteed pass):**
- C3 ✅ Environment-based config — All config via `os.getenv()`
- C4 ✅ Health check endpoint — `/health` endpoint returns `{"status": "healthy"}`
- C5 ✅ Stateless design — No local filesystem for persistent state
- C8 ✅ Error handling — Proper try/except with logging, no bare exceptions
- C9 ✅ Dependency management — pyproject.toml with pinned version ranges
- C11 ✅ MCP tool safety — Tool inputs validated (tool-agent template)

**INFO checks (guaranteed pass):**
- C6 ✅ Graceful shutdown — SIGTERM handler included
- C7 ✅ Logging to stdout — `logging.basicConfig(stream=sys.stdout)`
- C10 ✅ Agent framework — Uses Claude Agent SDK / Foundation Agent pattern
- C12 ✅ Memory pattern — AgentCore Memory compatible (where applicable)

## System Prompt Extension

The scaffold skill injects a comprehensive system prompt that teaches the agent:
1. What each template type includes and when to use it
2. The full file listing for each template
3. Platform requirements that generated code must satisfy
4. How to customize templates based on developer descriptions

See the implementation in `src/platform_agent/skills/scaffold/__init__.py` for the
complete prompt text.

## Template Implementation

Templates are implemented as Python string constants in
`src/platform_agent/skills/scaffold/templates.py`. Each template is a dictionary
mapping relative file paths to content strings with `{project_name}` placeholders.

This approach was chosen over external `.template` files for:
- **Simplicity** — No file I/O or path resolution needed
- **Testability** — Templates can be imported and validated in unit tests
- **Portability** — Skill is self-contained in a single package

## Evaluation Criteria

**Test cases** (5 minimum for MVP):

1. **Registration** — ScaffoldSkill registers correctly in skill registry
2. **System prompt** — Extension contains template type descriptions
3. **Template validity** — Template files are valid Python (where applicable)
4. **Dependencies** — Template pyproject.toml includes required dependencies
5. **Dockerfile compliance** — Template Dockerfile follows platform requirements

**Quality metrics:**
- Generated projects should pass `design_advisor` evaluation with READY rating
- All template Python files should be syntactically valid
- All template Dockerfiles should include HEALTHCHECK directive
- All template pyproject.toml files should pin dependency versions

## Integration with Other Skills

The scaffold skill works in concert with other platform skills:

- **design_advisor** — Run after scaffolding to verify READY rating
- **code_review** — Review generated code for quality
- **deployment_config** — Generate AgentCore deployment configs for scaffolded projects

Typical workflow:
```
plato scaffold "weather lookup agent with API integration"
→ Generates basic-agent project

plato review ./my-weather-agent
→ Design Advisor confirms READY rating

plato deploy-config ./my-weather-agent
→ Generates AgentCore deployment configuration
```
