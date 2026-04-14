# Agent Greenhouse 🌱

**Grow production-ready AI agents from seed to deployment.**

Agent Greenhouse is an opinionated framework for building specialist AI agents on Amazon Bedrock. It provides a **Foundation Agent** with batteries-included infrastructure — memory, hooks, guardrails, observability, deployment — so you can focus on what makes your agent unique: its domain expertise.

Think of it as a greenhouse: the structure (foundation) provides the right environment, and each plant (domain agent) grows differently based on its **Domain Harness** configuration.

[![Tests](https://img.shields.io/badge/tests-1868%2B%20passing-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.11+-blue)]()
[![License](https://img.shields.io/badge/license-MIT--0-lightgrey)]()
[![Strands](https://img.shields.io/badge/built%20with-Strands%20Agents%20SDK-orange)](https://strandsagents.com/)

## Why Agent Greenhouse?

Building a single AI agent is straightforward. Building *multiple* specialist agents that share infrastructure, memory patterns, hook middleware, and deployment pipelines — without copy-pasting boilerplate — is hard.

Agent Greenhouse solves this with two key concepts:

| Concept | What It Is | Analogy |
|---------|-----------|---------|
| **Foundation Agent** | Shared runtime: memory, hooks, guardrails, tools, soul system, deployment | The greenhouse structure |
| **Domain Harness** | Pure-data config defining a specialist agent's skills, policies, persona, memory layout | The plant's growth instructions |

You write a Domain Harness (a frozen dataclass, serializable to YAML). The Foundation Agent reads it and assembles everything — hooks, memory namespaces, tool policies, evaluation criteria — at construction time. Zero boilerplate.

## What's Inside

```
Agent Greenhouse
│
├── 🏗️ Foundation Agent (generic, reusable)
│   ├── Hook middleware (16 hooks: 13 active, 3 deprecated)
│   ├── Three-layer memory (session history + STM→LTM pipeline + workspace)
│   ├── Soul/persona system
│   ├── AgentSkills plugin (progressive loading via Strands SDK)
│   ├── Cedar policy guardrails
│   ├── Shared tools (GitHub, Claude Code, memory, workspace)
│   ├── A2A / MCP protocol adapters
│   └── AgentCore deployment helpers
│
└── 🌿 Domain Agents (your specialist agents)
    │
    └── 🏛️ Plato (included example — platform agent for Bedrock AgentCore)
        ├── 22 skill packs (16 domain + 6 knowledge-only, code review, scaffolding, AIDLC, ...)
        ├── Evaluator agents (reflect-refine quality gates)
        ├── Orchestrator (multi-skill routing)
        └── Control plane (registry, lifecycle, task manager)
```

### Plato: The First Domain Agent

This project started as **"Platform as Agent" (Plato)** — an agent that helps developers build, review, and deploy agent applications on Amazon Bedrock AgentCore. As it grew, we extracted the reusable infrastructure into Foundation Agent and kept Plato as the first (and most complete) domain example.

Plato is included as `platform_agent.plato` and demonstrates everything the framework can do: 22 skill packs, AIDLC workflows, evaluators, control plane, and a full CLI.

## Quick Start

### Installation

```bash
git clone https://github.com/aws-samples/sample-agent-greenhouse.git
cd sample-agent-greenhouse
pip install -e ".[dev]"
```

### Create Your Own Domain Agent (5 minutes)

**Step 1: Define a Domain Harness**

```python
# src/platform_agent/my_agent/harness.py
from platform_agent.foundation.harness import (
    DomainHarness, HookConfig, MemoryConfig, PersonaConfig, SkillRef,
)

def create_my_harness() -> DomainHarness:
    return DomainHarness(
        name="my_agent",
        description="A specialist agent for [your domain]",
        skill_directories=["src/platform_agent/my_agent/skills"],
        skills=[
            SkillRef(name="my_skill", description="Does X", tools=["Read", "Bash"]),
        ],
        hooks=[
            HookConfig(hook="SoulSystemHook", category="foundation"),
            HookConfig(hook="MemoryHook", category="domain"),
            HookConfig(hook="AuditHook", category="foundation"),
        ],
        memory_config=MemoryConfig(
            namespace_template="/my_agent/{session_id}/",
            persist_types=["conversation"],
            ttl_days=30,
        ),
        persona=PersonaConfig(
            tone="friendly",
            communication_style="concise",
            role="domain expert",
        ),
    )
```

**Step 2: Wire it up**

```python
from platform_agent.foundation.agent import FoundationAgent
from platform_agent.my_agent.harness import create_my_harness

agent = FoundationAgent(harness=create_my_harness())
response = agent("Hello! What can you help me with?")
```

That's it. You get memory, hooks, guardrails, telemetry — all configured by your harness.

Or define it as YAML:

```yaml
# my_agent_harness.yaml
name: my_agent
description: A specialist agent for [your domain]
version: 1.0.0
skill_directories:
  - src/platform_agent/my_agent/skills
skills:
  - name: my_skill
    description: Does X
    tools: [Read, Bash]
hooks:
  - hook: SoulSystemHook
    category: foundation
  - hook: MemoryHook
    category: domain
memory_config:
  namespace_template: "/my_agent/{session_id}/"
  ttl_days: 30
persona:
  tone: friendly
  communication_style: concise
  role: domain expert
```

```python
harness = DomainHarness.from_yaml("my_agent_harness.yaml")
agent = FoundationAgent(harness=harness)
```

### Use Plato (the included domain agent)

```bash
# Check if your agent app is platform-ready (12-item checklist)
plato readiness /path/to/your-agent

# Review code for security, quality, and agent patterns
plato review /path/to/your-agent

# Scaffold a new agent project
plato scaffold "A customer support agent with RAG" --template basic-agent

# Generate deployment configuration
plato deploy-config /path/to/your-agent --target agentcore

# AIDLC Inception — guided project inception workflow
plato inception org/my-agent

# Spec compliance check
plato compliance org/my-agent

# Multi-skill orchestration
plato orchestrate "Review this repo and then generate deployment configs"
```

## Architecture

![Agent Greenhouse Architecture](docs/images/architecture.png)

### Foundation Agent

The core runtime that all domain agents share. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for a quick overview, or [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design document.

| Component | Location | Purpose |
|-----------|----------|---------|
| `FoundationAgent` | `foundation/agent.py` | Base agent class wrapping Strands SDK |
| `DomainHarness` | `foundation/harness.py` | Pure-data config schema (frozen dataclass → YAML) |
| `SoulSystem` | `foundation/soul.py` | Agent persona/personality injection |
| Memory | `foundation/memory.py`, `memory.py` | Three-layer memory (session replay + STM→LTM pipeline + workspace) |
| Hook System | `foundation/hooks/` | 16 lifecycle hooks (13 active, 3 deprecated) |
| Guardrails | `foundation/guardrails/` | Cedar-based tool-level policy engine |
| Tools | `foundation/tools/` | GitHub, Claude Code, memory, workspace tools |
| Deploy | `foundation/deploy/` | AgentCore + Dockerfile generation |

### Domain Harness

A `DomainHarness` is a **frozen dataclass** that fully describes a specialist agent as pure data — no runtime logic. It configures:

- **Skills** — what the agent can do
- **Hooks** — middleware activated at runtime (foundation always-on + domain + optional)
- **Memory** — namespace templates, TTL, extraction/consolidation toggles, STM→LTM strategy config
- **Policies** — tool allow/deny lists, Cedar policies
- **Persona** — tone, style, role, constraints
- **Eval criteria** — quality gate thresholds

### Hook System

Hooks fire on lifecycle events (`before_tool`, `after_tool`, `before_model`, `after_model`, `on_error`). The harness declares which hooks to load; the Foundation Agent assembles them at construction time.

| Category | Behavior | Examples |
|----------|----------|---------|
| **Foundation** (always-on) | Loaded regardless of harness config | `AuditHook`, `TelemetryHook`, `GuardrailsHook`, `SoulSystemHook` |
| **Domain** | Loaded when listed in harness | `MemoryHook`, `ModelMetricsHook`, `ToolPolicyHook`, `OTELSpanHook` |
| **Optional** | Loaded when `enabled_by` condition is true | `MemoryExtractionHook`, `ConsolidationHook` |

### Plato Domain

The included reference implementation with 22 skill packs (16 domain + 6 knowledge-only):

| Skill | Purpose |
|-------|---------|
| `design-advisor` | Platform readiness assessment (C1–C12 checklist) |
| `code-review` | Security & quality review |
| `scaffold` | Project skeleton generator |
| `deployment-config` | IAM, Dockerfile, CDK, CI/CD generation |
| `aidlc-inception` | Guided AIDLC inception workflow |
| `spec-compliance` | Spec compliance verification |
| `pr-review` | PR review with spec tracing |
| `issue-creator` | Structured GitHub issue creation |
| `test-case-generator` | Spec-to-test-case (1:1 AC→TC) |
| `debug` | Troubleshooting and debugging |
| `fleet-ops` | Fleet operations management |
| `governance` | Compliance and governance checks |
| `knowledge` | Knowledge base and reference lookup |
| `monitoring` | Monitoring and alerting setup |
| `observability` | Observability instrumentation |
| `onboarding` | Developer onboarding guidance |
| `architecture-knowledge` | Architecture patterns and decisions (knowledge-only) |
| `cost-optimization` | Cost optimization guidance (knowledge-only) |
| `migration-guide` | Migration strategies and patterns (knowledge-only) |
| `policy-compiler` | Policy compilation reference (knowledge-only) |
| `security-review` | Security review checklist (knowledge-only) |
| `testing-strategy` | Testing strategy guidance (knowledge-only) |

## Project Structure

```
agent-greenhouse/
├── src/platform_agent/
│   ├── foundation/              # 🏗️ Generic framework (reuse for any agent)
│   │   ├── agent.py             # FoundationAgent base class
│   │   ├── harness.py           # DomainHarness schema
│   │   ├── memory.py            # Memory (STM→LTM pipeline + workspace)
│   │   ├── soul.py              # Persona system
│   │   ├── hooks/               # 16 lifecycle hooks (13 active, 3 deprecated)
│   │   ├── guardrails/          # Cedar policy engine
│   │   ├── handoff/             # Human escalation
│   │   ├── protocols/           # A2A + MCP adapters
│   │   ├── skills/              # AgentSkills plugin (progressive loading)
│   │   ├── tools/               # Shared tools
│   │   └── deploy/              # Deployment helpers
│   │
│   ├── plato/                   # 🏛️ Plato domain (reference implementation)
│   │   ├── harness.py           # create_plato_harness() factory
│   │   ├── orchestrator.py      # Multi-skill router
│   │   ├── aidlc/               # AIDLC workflow engine
│   │   ├── control_plane/       # Registry, lifecycle, tasks, policies
│   │   ├── evaluator/           # Quality gate evaluators
│   │   └── skills/              # 22 Plato skill packs (16 domain + 6 knowledge-only)
│   │
│   ├── cli.py                   # CLI entry point
│   ├── memory.py                # Top-level memory store
│   ├── health.py                # Health check endpoint
│   └── bedrock_runtime.py       # Bedrock converse API wrapper
│
├── tests/                       # 87 test files, 1868+ test functions
├── ARCHITECTURE.md              # Detailed architecture docs
├── docs/
│   ├── ARCHITECTURE.md          # Full design document
│   ├── MEMORY_DEEP_DIVE.md     # Memory architecture comparison
│   ├── deploy/                  # Deployment guides
│   └── observability/           # CloudWatch dashboards & tracing
├── docs/design/                 # Design documents
└── pyproject.toml
```

## Runtime Modes

| Mode | How | When |
|------|-----|------|
| **AgentCore** (production) | Deployed as hosted agent on AgentCore | Production, team access via API or Slack |
| **Local CLI** (development) | Runs locally via `plato` CLI | Local dev, prototyping, demos |

Both modes use the same Foundation Agent + Domain Harness architecture.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent Framework | Strands Agents SDK |
| Runtime (production) | Amazon Bedrock AgentCore |
| Runtime (local) | Bedrock Converse API (boto3) |
| Memory | AgentCore Memory (4 strategies: semantic, summary, preferences, episodic) |
| CLI | Click |
| Testing | pytest + pytest-asyncio |

### Memory System

Cross-session memory via the AgentCore STM → LTM pipeline:

- **4 memory strategies**: semantic knowledge, user preferences, conversation summaries, episodic memory
- **Score-based context injection**: Results ranked by relevance, preferences boosted (+0.1), deduplicated across strategies, budget-capped at 6000 chars (~1500 tokens)
- **Active memory curation**: Agent proactively saves important corrections, preferences, decisions, and action items via `save_memory` tool (configured in `workspace/AGENTS.md`)
- **Multi-tenant isolation**: All memory scoped by `actor_id` (JWT Cognito sub claim)
- **E2E verification**: `scripts/e2e_memory_test.py` (basic recall) and `scripts/e2e_memory_multiturn.py` (5-scenario suite covering cross-session recall, preference override, user isolation, active curation, and token cap)

See [`docs/ARCHITECTURE.md` §7](docs/ARCHITECTURE.md#7-three-layer-memory-architecture) for the full design, or [`docs/MEMORY_DEEP_DIVE.md`](docs/MEMORY_DEEP_DIVE.md) for a comparison with other agent memory systems.

### Observability

Built-in instrumentation for production monitoring:

- **OpenTelemetry tracing**: `OTELSpanHook` creates spans for every invocation and tool call, exported via ADOT sidecar to AWS X-Ray
- **CloudWatch EMF metrics**: `TelemetryHook` emits structured metrics — `ModelCallLatency`, `ModelCallCount`, `ToolCallCount`, `ToolCallDuration`, `ToolErrorCount`, `SkillInvocationCount`, `SkillInvocationDuration`
- **Audit logging**: `AuditHook` records all tool calls with inputs/outputs in CloudWatch Logs and optionally DynamoDB
- **AgentCore native**: Enable observability at deploy time by setting `observability.enabled: true` in `.bedrock_agentcore.yaml` (see [`.bedrock_agentcore.yaml.example`](.bedrock_agentcore.yaml.example)). X-Ray traces can be verified in the [AWS X-Ray console](https://console.aws.amazon.com/xray/home).

See [`docs/observability/`](docs/observability/) for CloudWatch dashboard design documents (provision scripts coming soon), SLO alarms, composite alarms, and ADOT configuration.

## Running Tests

```bash
pip install -e ".[dev]"
python -m pytest          # all tests
python -m pytest -v       # verbose
python -m pytest -q       # quick summary
```

## Deploy to Production

For production deployment on AgentCore with Slack integration:

1. **Deploy agent**: Follow the [AgentCore Deployment Guide](docs/deploy/AGENTCORE_DEPLOY.md) to deploy, configure memory, and set up the JWT authorizer
2. **Set up memory**: Run `python3 scripts/setup_memory.py --memory-id "$MEMORY_ID" --verify` to create the 4 memory strategies
3. **Connect Slack**: Follow the [Slack Integration Guide](docs/deploy/SLACK_INTEGRATION.md) to create a Cognito user pool, Slack app, and handler Lambdas
4. **Verify**: Run `bash scripts/deploy.sh` for an automated 11-point checklist covering agent health, auth, memory, and observability

**Prerequisites:**

- AWS account with Bedrock model access — enable **Claude Opus 4.6** (`global.anthropic.claude-opus-4-6-v1`) in the [Bedrock model access console](https://console.aws.amazon.com/bedrock/home#/modelaccess), or set the `MODEL_ID` env var to use a different model
- Amazon Cognito User Pool (for JWT authentication)
- Slack workspace (for the chat interface)

## Roadmap

- [x] Foundation Agent + DomainHarness schema
- [x] Hook middleware system (16 hooks: 13 active, 3 deprecated)
- [x] Three-layer memory architecture
- [x] Plato domain: 22 skill packs + evaluators + AIDLC
- [x] Deprecation files for backward compatibility
- [x] AgentCore Memory integration (4-strategy cross-session LTM)
- [x] Score-based LTM token cap + active memory curation
- [x] E2E memory verification suite
- [ ] A2A multi-agent communication
- [ ] Production monitoring agent
- [ ] Cedar policy guardrails (full)
- [x] AgentSkills plugin (progressive skill loading via Strands SDK)
- [ ] Additional domain examples

## Built With

- [Strands Agents SDK](https://strandsagents.com/) — Agent framework with tool use, hooks, and session management
- [Amazon Bedrock](https://aws.amazon.com/bedrock/) — Foundation models (Claude, Nova, etc.)
- [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/) — Serverless agent runtime, memory, and deployment

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Quick architecture overview
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Full design document (package structure, DomainHarness, hooks, memory, creating new agents)
- [`docs/MEMORY_DEEP_DIVE.md`](docs/MEMORY_DEEP_DIVE.md) — Memory architecture deep dive (Hermes vs OpenClaw vs Plato comparison, multi-tenant design)
- [`docs/deploy/AGENTCORE_DEPLOY.md`](docs/deploy/AGENTCORE_DEPLOY.md) — AgentCore deployment, memory setup, and JWT authorizer
- [`docs/deploy/SLACK_INTEGRATION.md`](docs/deploy/SLACK_INTEGRATION.md) — End-to-end Slack bot integration (Cognito, Lambda, SQS)
- [`docs/observability/`](docs/observability/) — CloudWatch dashboards, alarms, and ADOT tracing

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and how to add new skills or domain agents.

## License

[MIT-0](LICENSE)
