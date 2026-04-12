# Architecture Overview

## Package Structure

```
src/platform_agent/
├── foundation/          # Framework-generic, reusable across all agents
│   ├── agent.py         # FoundationAgent base class (Strands SDK wrapper)
│   ├── harness.py       # DomainHarness + config dataclasses
│   ├── memory.py        # Memory layer (AgentCore events + long-term records)
│   ├── soul.py          # Agent soul/persona definitions
│   ├── guardrails/      # Cedar-based policy engine
│   ├── handoff/         # Human escalation handler
│   ├── hooks/           # Lifecycle hooks (memory, telemetry, guardrails, etc.)
│   ├── protocols/       # A2A and MCP protocol adapters
│   ├── skills/          # Skill registry (foundation-level)
│   ├── tools/           # Shared tools (GitHub, Claude Code, memory tools)
│   └── deploy/          # AgentCore deployment helpers
│
├── plato/               # Plato domain — platform agent for Bedrock AgentCore
│   ├── harness.py       # create_plato_harness() factory
│   ├── orchestrator.py  # Plato orchestration entry point
│   ├── aidlc/           # AI-Driven Lifecycle (spec, stages, workflow)
│   ├── control_plane/   # Agent registry, lifecycle, task manager, policy engine
│   ├── evaluator/       # Code review, design, scaffold, deployment evaluators
│   └── skills/          # Plato skill packs (aidlc_inception, code_review, etc.)
│
├── memory.py            # Top-level memory store (AgentCore Memory API)
├── cli.py               # Command-line interface
├── health.py            # Health check endpoint
├── bedrock_runtime.py   # Bedrock converse API wrapper
│
# Deprecated shims (kept for external consumers, emit DeprecationWarning):
├── aidlc/               # → platform_agent.plato.aidlc
├── control_plane/       # → platform_agent.plato.control_plane
├── evaluator/           # → platform_agent.plato.evaluator
├── orchestrator.py      # → platform_agent.plato.orchestrator
├── skills/              # → platform_agent.plato.skills
├── guardrails/          # → platform_agent.foundation.guardrails
├── handoff/             # → platform_agent.foundation.handoff
├── protocols/           # → platform_agent.foundation.protocols
├── strands_foundation/  # → platform_agent.foundation
└── _legacy_foundation.py  # deprecated, do not use
```

### Canonical import paths

| Component | Canonical path |
|-----------|---------------|
| FoundationAgent | `platform_agent.foundation.agent` |
| DomainHarness | `platform_agent.foundation.harness` |
| Guardrails | `platform_agent.foundation.guardrails` |
| Handoff | `platform_agent.foundation.handoff` |
| Hooks | `platform_agent.foundation.hooks.*` |
| Protocols | `platform_agent.foundation.protocols.*` |
| Skills registry | `platform_agent.foundation.skills.registry` |
| Tools | `platform_agent.foundation.tools.*` |
| AIDLC | `platform_agent.plato.aidlc.*` |
| Control plane | `platform_agent.plato.control_plane.*` |
| Evaluators | `platform_agent.plato.evaluator.*` |
| Orchestrator | `platform_agent.plato.orchestrator` |
| Plato skills | `platform_agent.plato.skills.*` |

---

## DomainHarness Concept

A `DomainHarness` is a **frozen dataclass** that fully describes a specialist agent's
configuration as pure data — no runtime logic. It bundles:

| Field | Type | Purpose |
|-------|------|---------|
| `name` | `str` | Unique identifier for the domain |
| `description` | `str` | Human-readable purpose statement |
| `skills` | `list[SkillRef]` | Skills available to the agent |
| `tools` | `list[str]` | Tool names the agent may call |
| `mcp_servers` | `dict` | MCP server declarations |
| `policies` | `PolicyConfig` | Tool allow/deny lists and Cedar policies |
| `memory_config` | `MemoryConfig` | Memory namespace, TTL, extraction/consolidation toggles |
| `eval_criteria` | `list[EvalRule]` | Evaluation rules for quality gates |
| `hooks` | `list[HookConfig]` | Hooks to activate at runtime |

The harness is **serializable to/from YAML** via `DomainHarness.to_dict()` /
`DomainHarness.from_yaml()`, enabling configuration-as-code.

### Plato harness example

```python
from platform_agent.plato.harness import create_plato_harness

harness = create_plato_harness()
agent = FoundationAgent(harness=harness)
```

---

## Hook Loading Mechanism

Hooks are loaded by `FoundationAgent` at construction time using the `hooks`
list from the `DomainHarness`. Each entry is a `HookConfig`:

```python
@dataclass(frozen=True)
class HookConfig:
    hook: str                    # e.g. "MemoryHook"
    category: str                # "foundation" | "domain" | "optional"
    enabled_by: str | None = None  # dotted-path condition, e.g. "memory_config.extraction_enabled"
    params: dict[str, Any] = field(default_factory=dict)  # hook-specific parameters
```

Categories control loading behavior:
- **foundation**: Always loaded regardless of harness config (e.g. `AuditHook`, `SoulSystemHook`)
- **domain**: Loaded when listed in the harness's `hooks` list
- **optional**: Loaded only when the `enabled_by` dotted-path resolves to a truthy value on the harness

At agent startup, `FoundationAgent` imports each enabled hook and registers
the hook callbacks with the Strands SDK event loop. Hooks fire on lifecycle events:
`before_tool`, `after_tool`, `before_model`, `after_model`, `on_error`.

Available hooks (all in `platform_agent.foundation.hooks`):

| Hook | Purpose |
|------|---------|
| `memory_hook` | Persist conversation turns via AgentCore Memory |
| `memory_extraction_hook` | Extract structured insights from conversation |
| `consolidation_hook` | Merge memory records to prevent duplication |
| `compaction_hook` | Compact long conversation histories |
| `session_recording_hook` | Record full session to file |
| `guardrails_hook` | Evaluate Cedar policies before each tool call |
| `hallucination_detector_hook` | Flag potential hallucinations |
| `otel_span_hook` | Emit OpenTelemetry spans for observability |
| `business_metrics_hook` | Record business-level metrics |
| `soul_hook` | Apply agent persona/soul constraints |
| `aidlc_telemetry_hook` | AIDLC stage transition telemetry |
| `audit_hook` | Audit trail for all tool calls |
| `tool_policy_hook` | Enforce tool-level policy rules |

---

## Memory Configuration

Memory is configured via `MemoryConfig` in the `DomainHarness`:

```python
MemoryConfig(
    namespace_template="/actors/{actorId}/",  # AgentCore namespace per actor
    persist_types=["conversation", "insight"],
    ttl_days=90,
    extraction_enabled=True,   # extract insights after each turn
    consolidation_enabled=True # merge duplicate memory records
)
```

The memory layer (`platform_agent.foundation.memory`) provides:
- **ConversationMemory** — short-term via AgentCore events (`create_event` feeds LTM strategies)
- **LongTermMemory** — semantic search via AgentCore memory records (4 strategies: semantic, summary, preferences, episodic)
- **InMemoryStore** — local development fallback (no AWS calls)

Conversation history is persisted by `FileSessionManager` (Layer 1). After each turn, `_ingest_to_stm()` writes user/assistant messages to AgentCore STM via `create_event()`. AgentCore asynchronously processes these events through 4 configured memory strategies to build LTM. On new sessions, `_load_ltm_context()` queries all 4 strategy namespaces with the current user message for semantic matching.

---

## Creating a New Specialist Agent

To create a new domain agent (e.g., `my_domain`):

### 1. Create the domain package

```
src/platform_agent/my_domain/
├── __init__.py
└── harness.py   # domain harness factory
```

### 2. Define the harness factory

```python
# src/platform_agent/my_domain/harness.py
from platform_agent.foundation.harness import (
    DomainHarness, HookConfig, MemoryConfig, PolicyConfig, SkillRef,
)

def create_my_domain_harness() -> DomainHarness:
    return DomainHarness(
        name="my_domain",
        description="My specialist agent description",
        version="1.0.0",
        skills=[
            SkillRef(name="my_skill", description="...", tools=["Read", "Bash"]),
        ],
        hooks=[
            HookConfig(hook="SoulSystemHook", category="foundation"),
            HookConfig(hook="AuditHook", category="foundation"),
            HookConfig(hook="MemoryHook", category="domain"),
        ],
        memory_config=MemoryConfig(
            namespace_template="/my_domain/{actorId}/",
            persist_types=["conversation"],
            ttl_days=30,
        ),
        policies=PolicyConfig(
            tool_allowlist=["Read", "Bash", "Glob", "Grep"],
        ),
    )
```

### 3. Add skill packs (optional)

```python
# src/platform_agent/my_domain/skills/my_skill/__init__.py
from platform_agent.plato.skills.base import SkillPack

class MySkill(SkillPack):
    system_prompt_extension = "You are an expert in..."
    tools = []  # list of @tool-decorated functions
```

### 4. Wire into FoundationAgent

```python
from platform_agent.foundation.agent import FoundationAgent
from platform_agent.my_domain.harness import create_my_domain_harness

harness = create_my_domain_harness()
agent = FoundationAgent(harness=harness)
response = agent("Hello!")
```

---

## Deprecated Shims

All paths under `platform_agent.{aidlc,control_plane,evaluator,orchestrator,skills,
guardrails,handoff,protocols,strands_foundation}` are **backward-compatibility shims**.
They re-export the canonical implementations and emit `DeprecationWarning` on import.

Do **not** use shim paths in new code. They will be removed in a future major version.
