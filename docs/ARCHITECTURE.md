# Plato Agent — Architecture Design Document

> **Version**: 1.0.0 · **Last updated**: 2026-04-14
> **Codebase**: `platform-as-agent` · **Branch**: `main`

---

## 1. Executive Summary

**Plato** is a platform agent for Amazon Bedrock AgentCore that helps developers build, review, and deploy agent applications. It follows a **Foundation Agent + Domain Harness** pattern: a reusable Foundation layer (hooks, memory, tools, soul) is configured by a declarative `DomainHarness` frozen dataclass to produce the Plato specialist.

### Key Numbers

| Metric | Count |
|--------|-------|
| Hook middleware | 10 active, 5 optional/deprecated |
| Skill packs | 22 total: 16 domain + 6 knowledge-only |
| Domain tools | 33+ (7 AIDLC + 13 GitHub + 2 memory + 3 workspace + Claude Code + domain-specific) |
| Test files | 87 |
| Test functions | 1,868+ |
| Source files | 108 Python modules |
| Evaluation rubrics | 3 (spec quality, code review coverage, readiness checklist) |

### Design Principles

- **Harness-as-data**: All domain configuration lives in `DomainHarness` (frozen dataclass, YAML-serializable) — no runtime logic in config.
- **Hook middleware over inheritance**: Behavior composed via lifecycle hooks, not class hierarchies.
- *FileSessionManager + STM dual-write*: Conversation persistence via Strands SDK's `FileSessionManager` (for agent replay) AND AgentCore STM `create_event` (to feed 4 LTM strategies: semantic, summary, preferences, episodic).
- **Prompt cache awareness**: Static system prompt kept stable across invocations for Bedrock prompt cache hits.
- **Session isolation**: Each `session_id` gets its own agent instance with separate conversation history.

---

## 2. High-Level Architecture

```
                           ┌────────────────┐
                           │    Slack App    │
                           └───────┬────────┘
                                   │ HTTP POST (Events API)
                                   ▼
                    ┌──────────────────────────────┐
                    │  API Gateway → Lambda (ack)   │  ← returns 200 within 3s
                    │  plato-slack-ack               │
                    └──────────────┬───────────────┘
                                   │ SQS FIFO
                                   │ (MessageDeduplicationId = channel-ts)
                                   │ (MessageGroupId = channel-thread_ts)
                                   ▼
                    ┌──────────────────────────────┐
                    │  Lambda (worker)              │
                    │  plato-slack-worker            │
                    └──────────────┬───────────────┘
                                   │ HTTP or WebSocket
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AgentCore Runtime (BedrockAgentCoreApp)                            │
│                                                                     │
│  ┌──────────────────┐    ┌─────────────────────────────────────┐   │
│  │  @app.entrypoint  │    │  @app.websocket                     │   │
│  │  invoke()          │    │  ws_handler()                       │   │
│  └────────┬─────────┘    └─────────────┬───────────────────────┘   │
│           │                             │                           │
│           └──────────┬──────────────────┘                           │
│                      ▼                                              │
│           ┌─────────────────────┐                                   │
│           │     AgentPool       │  ← per-session isolation          │
│           │  (LRU, max=100)     │     concurrency locks             │
│           └────────┬────────────┘                                   │
│                    ▼                                                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  FoundationAgent (Strands SDK wrapper)                        │  │
│  │                                                               │  │
│  │  ┌───────────┐  ┌──────────────┐  ┌───────────────────────┐  │  │
│  │  │ SoulSystem │  │ 10 Hooks     │  │ AgentSkills plugin    │  │  │
│  │  │ (5 .md)    │  │ (middleware)  │  │ (22 skills)           │  │  │
│  │  └───────────┘  └──────────────┘  └───────────────────────┘  │  │
│  │                                                               │  │
│  │  ┌────────────────────────────────────────────────────────┐   │  │
│  │  │  Tools: workspace · GitHub (13) · AIDLC (7)            │   │  │
│  │  │         memory (save/recall) · Claude Code CLI          │   │  │
│  │  └────────────────────────────────────────────────────────┘   │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                             ▼                                       │
│                   Amazon Bedrock (Claude)                            │
│                   global.anthropic.claude-opus-4-6-v1                 │
└─────────────────────────────────────────────────────────────────────┘

Memory Architecture:
  Layer 1: FileSessionManager → /mnt/workspace/.sessions/{session_id}.json
  Layer 2: STM → LTM pipeline:
           _ingest_to_stm() → create_event (user + assistant msgs)
           → AgentCore async extraction → 4 strategies:
              ├─ semanticKnowledge   (facts, decisions, concepts)
              ├─ userPreferences     (working style, tool preferences)
              ├─ conversationSummary (per-session summaries)
              └─ episodicMemory      (past interactions, events)
           _load_ltm_context() → queries all 4 with current_message
  Layer 3: Workspace files → /mnt/workspace/projects/

WebSocket Streaming Path:
  ws_handler → _WSCallbackHandler → queue.Queue → async loop → websocket.send_text
  Events: {"type": "delta"|"tool_start"|"complete"|"error", ...}
```

---

## 3. Code Structure

```
src/platform_agent/
├── __init__.py
├── _legacy_foundation.py          # DEPRECATED — imported by foundation/__init__.py for backward compat
├── bedrock_runtime.py             # Bedrock Converse API fallback (boto3 direct)
├── cli.py                         # CLI entry point
├── health.py                      # Health check endpoint
├── memory.py                      # Top-level memory store (AgentCore Memory API)
├── orchestrator.py                # Deprecated shim → plato.orchestrator (no active imports, safe to delete)
│
├── foundation/                    # ── FOUNDATION LAYER (reusable) ──
│   ├── agent.py                   # FoundationAgent — Strands SDK wrapper
│   ├── harness.py                 # DomainHarness + config dataclasses
│   ├── memory.py                  # SessionMemory + WorkspaceMemory
│   ├── soul.py                    # SoulSystem — personality file loader
│   ├── hooks/                     # 10 active lifecycle hook implementations
│   │   ├── base.py                # HookBase (extends Strands HookProvider)
│   │   ├── soul_hook.py           # Soul file loading
│   │   ├── memory_hook.py         # Session + workspace memory recording
│   │   ├── audit_hook.py          # Tool call audit logging
│   │   ├── guardrails_hook.py     # Input/output validation
│   │   ├── telemetry_hook.py      # Invocation + tool timing (EMF)
│   │   ├── model_metrics_hook.py  # LLM call latency tracking
│   │   ├── tool_policy_hook.py    # Tool allowlist/denylist enforcement
│   │   ├── business_metrics_hook.py  # DAU, skill usage, artifacts
│   │   ├── hallucination_detector_hook.py  # Output capture + consistency
│   │   ├── otel_span_hook.py      # OpenTelemetry tracing
│   │   ├── session_recording_hook.py  # Full session capture (S3)
│   │   ├── memory_extraction_hook.py  # Structured memory extraction
│   │   ├── consolidation_hook.py  # 3-gate memory consolidation
│   │   ├── compaction_hook.py     # DEPRECATED — log-only in v1
│   │   └── aidlc_telemetry_hook.py  # AIDLC workflow metrics
│   ├── skills/
│   │   └── registry.py            # SkillRegistry — lazy-loading discovery
│   ├── tools/
│   │   ├── workspace.py           # read_file, write_file, list_files
│   │   ├── github.py              # GitHub ops (pure urllib)
│   │   ├── github_tool.py         # GitHub ops (requests library, 13 tools)
│   │   ├── memory_tools.py        # save_memory, recall_memory (AgentCore)
│   │   └── claude_code.py         # Claude Code CLI wrapper
│   ├── protocols/
│   │   ├── a2a.py                 # Agent-to-Agent protocol adapter
│   │   └── mcp.py                 # Model Context Protocol adapter
│   ├── handoff/
│   │   └── agent.py               # Human escalation (HandoffAgent)
│   ├── deploy/
│   │   ├── agentcore.py           # AgentCore deployment config generator
│   │   └── dockerfile.py          # Dockerfile generator
│   └── guardrails/                # Cedar-based policy engine (293 lines)
│
├── plato/                         # ── PLATO DOMAIN LAYER ──
│   ├── harness.py                 # create_plato_harness() factory
│   ├── orchestrator.py            # Agent-as-tool routing pattern
│   ├── aidlc/                     # AI-Driven Lifecycle workflow engine
│   │   ├── workflow.py            # AIDLCWorkflow state machine
│   │   ├── state.py               # StageStatus, WorkflowState persistence
│   │   ├── stages.py              # 6 stage definitions
│   │   ├── questions.py           # Complexity-adapted question banks
│   │   ├── artifacts.py           # Markdown artifact compilers
│   │   └── spec_scoring.py        # Spec completeness rubric (0-100)
│   ├── control_plane/             # Multi-agent control plane
│   │   ├── registry.py            # Agent registry + state machine
│   │   ├── lifecycle.py           # Cold start, heartbeat, graceful shutdown
│   │   ├── policy_engine.py       # Cedar + platform policies
│   │   ├── task_manager.py        # Task queue + capability-based dispatch
│   │   ├── message_router.py      # Middleware pipeline for inter-agent msgs
│   │   ├── audit.py               # Audit store (16 action types)
│   │   └── dynamodb_store.py      # Single-table DynamoDB persistence
│   ├── evaluator/                 # Reflect-refine evaluation framework
│   │   ├── base.py                # EvaluatorAgent base + rubric engine
│   │   ├── code_review.py         # CodeReviewEvaluator (5 rubric items)
│   │   ├── design.py              # DesignEvaluator (C1-C12 checklist)
│   │   ├── deployment.py          # DeploymentEvaluator
│   │   └── scaffold.py            # ScaffoldEvaluator
│   └── skills/                    # 22 skills (16 domain + 6 knowledge-only)
│       ├── base.py                # SkillPack abstract base class
│       ├── aidlc_inception/       # Guided AIDLC inception workflow
│       ├── architecture-knowledge/  # Knowledge-only: architecture patterns
│       ├── code_review/           # Security and quality code review
│       ├── cost-optimization/     # Knowledge-only: cost optimization
│       ├── debug/                 # Troubleshooting
│       ├── deployment_config/     # Deployment configuration generation
│       ├── design_advisor/        # Platform readiness (C1-C12)
│       ├── fleet_ops/             # Fleet operations
│       ├── governance/            # Compliance checks
│       ├── issue_creator/         # GitHub issue creation
│       ├── knowledge/             # Reference lookup
│       ├── migration-guide/       # Knowledge-only: migration guidance
│       ├── monitoring/            # Monitoring setup
│       ├── observability/         # Instrumentation guidance
│       ├── onboarding/            # Developer onboarding
│       ├── policy-compiler/       # Knowledge-only: policy compilation
│       ├── pr_review/             # PR review with spec tracing
│       ├── scaffold/              # Project skeleton generation
│       ├── security-review/       # Knowledge-only: security review
│       ├── spec_compliance/       # Spec compliance verification
│       ├── test_case_generator/   # 1:1 AC-to-TC mapping
│       └── testing-strategy/      # Knowledge-only: testing strategy
│
├── slack/                         # Slack integration
│   ├── handler.py                 # SlackEventHandler + SlackConfig
│   └── lambda_function.py         # Two-Lambda pattern (ack + worker)
│
└── _legacy_foundation.py          # DEPRECATED — imported by foundation/__init__.py (backward compat alias), CLI + 7 test files depend on it
```

### Canonical Import Paths

| Component | Canonical path |
|-----------|---------------|
| FoundationAgent | `platform_agent.foundation.agent` |
| DomainHarness | `platform_agent.foundation.harness` |
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

## 4. Foundation Agent Layer

### 4.1 `FoundationAgent` — `src/platform_agent/foundation/agent.py`

The central class that wraps Strands SDK `Agent` with soul system, memory, hooks, skills, and tools.

```python
class FoundationAgent:
    def __init__(
        self,
        workspace_dir: str | None = None,
        model_id: str = "global.anthropic.claude-opus-4-6-v1",
        extra_tools: list[Callable] | None = None,
        enable_claude_code: bool = False,
        tool_allowlist: list[str] | None = None,
        tool_denylist: list[str] | None = None,
        enable_memory_extraction: bool = False,
        enable_consolidation: bool = False,
        session_id: str | None = None,
        skill_name: str | None = None,
        session_manager: Any | None = None,   # FileSessionManager
        harness: Any | None = None,            # DomainHarness
    )

    def build_system_prompt(self) -> str      # Assemble static prompt (soul + skills)
    def get_tools(self) -> list[Callable]     # Return all tool functions
    def invoke(self, prompt: str) -> str      # Run agent, return text
    def reset(self) -> None                   # Discard conversation history
```

**Build flow**:

1. Load `SoulSystem` (IDENTITY.md, SOUL.md, AGENTS.md, USER.md, MEMORY.md)
2. Initialize `SessionMemory` + `WorkspaceMemory`
3. Initialize AgentSkills plugin via `harness.skill_directories` or fallback `workspace/skills/`
4. Assemble hook registry (always-on + harness-driven)
5. Build tool list (workspace + GitHub + AIDLC + memory + Claude Code + extras)
6. Compute `_prompt_hash` (SHA256 of static system prompt for cache awareness)
7. On first `invoke()`: construct `strands.Agent` with all hooks and tools

**Prompt caching strategy**: The system prompt is built once from soul files and skill descriptions. Dynamic context (date/time, LTM) is injected via hooks or as user message content — never into the system prompt — so Bedrock can cache the static portion.

**Session manager integration**: When `session_manager` (a `FileSessionManager`) is provided, it's passed to Strands `Agent`, which handles conversation persistence automatically. This replaces manual `SessionMemory` management.

**Backward-compatible alias**: `FoundationStrandsAgent = FoundationAgent`

### 4.2 `SoulSystem` — `src/platform_agent/foundation/soul.py`

Loads and assembles workspace personality files for system prompt construction.

```python
class SoulSystem:
    def __init__(self, workspace_dir: str | None = None)
    def reload(self) -> None                    # Re-read all soul files
    def load_memory_files(self) -> None         # Load memory/*.md files
    def assemble_prompt(self) -> str            # Build system prompt from soul files
```

**Soul files** (loaded in order from `{workspace_dir}/`):

| File | Purpose |
|------|---------|
| `IDENTITY.md` | Agent name, emoji, vibe |
| `SOUL.md` | Personality, values, tone |
| `AGENTS.md` | Operating instructions, rules |
| `USER.md` | User profile |
| `MEMORY.md` | Long-term curated memory |

### 4.3 `SessionMemory` + `WorkspaceMemory` — `src/platform_agent/foundation/memory.py`

> **Note**: `FoundationAgent` no longer instantiates `SessionMemory` directly.
> `MemoryHook` maintains its own `SessionMemory` instance for message tracking.

```python
class SessionMemory:
    """In-memory conversation history for current session."""
    def add_message(self, role: str, content: str) -> None
    def get_history(self, limit: int | None = None) -> list[dict]
    def clear(self) -> None
    def estimate_tokens(self) -> int           # ~4 chars per token

class WorkspaceMemory:
    """File-based memory persisting across sessions."""
    def read_memory(self) -> str               # Read MEMORY.md
    def write_memory(self, content: str) -> None
    def append_memory(self, content: str) -> None
    def read_memory_file(self, name: str) -> str    # Read memory/{name}.md
    def write_memory_file(self, name: str, content: str) -> None
    def list_memory_files(self) -> list[str]
```

### 4.4 `DomainHarness` — `src/platform_agent/foundation/harness.py`

A **frozen dataclass** that fully describes a specialist agent's configuration as pure data.

```python
@dataclass(frozen=True)
class DomainHarness:
    name: str                                # Domain identifier
    description: str = ""                    # Human-readable purpose
    version: str = "0.1.0"
    skills: list[SkillRef]                   # Available skills
    tools: list[str]                         # Tool names
    mcp_servers: dict[str, Any]              # MCP server configs
    policies: PolicyConfig                   # Tool allow/deny + Cedar
    memory_config: MemoryConfig              # Namespace, TTL, extraction toggles
    eval_criteria: list[EvalRule]            # Quality gate rules
    hooks: list[HookConfig]                  # Hooks to activate
    persona: PersonaConfig | None = None     # Optional persona config
    skill_directories: list[str] = field(default_factory=list)  # AgentSkills plugin dirs

    def to_dict(self) -> dict                # Serialize to dict
    def from_dict(cls, data) -> DomainHarness  # Deserialize
    def to_yaml(self) -> str                 # Serialize to YAML
    def from_yaml(cls, path) -> DomainHarness  # Load from YAML file
```

**Sub-schemas** (all frozen dataclasses):

| Schema | Key Fields |
|--------|------------|
| `PolicyConfig` | `tool_allowlist`, `tool_denylist`, `cedar_policies`, `max_tool_calls_per_turn` |
| `MemoryConfig` | `namespace_template`, `persist_types`, `ttl_days`, `extraction_enabled`, `consolidation_enabled` |
| `EvalRule` | `name`, `description`, `threshold`, `scorer` |
| `HookConfig` | `hook`, `category`, `enabled_by`, `params` |
| `PersonaConfig` | `tone`, `communication_style`, `role`, `constraints` |
| `SkillRef` | `name`, `description`, `tools` |

### 4.5 `SkillRegistry` — `src/platform_agent/foundation/skills/registry.py`

> **DEPRECATED**: `AgentSkills` plugin is the production path for skill loading. `SkillRegistry` is kept as fallback only. `discover()` is no longer called eagerly on init.

Workspace-level skill discovery with lazy loading.

```python
@dataclass
class SkillMetadata:
    name: str
    description: str
    full_content: str              # Skill body (lazy-loaded)
    skill_dir: Path
    @classmethod
    def from_skill_md(cls, path) -> SkillMetadata
    @classmethod
    def from_discovery(cls, ...) -> SkillMetadata

class SkillRegistry:
    def __init__(self, workspace_dir: str | None = None)
    def discover(self) -> None                 # Scan skills/ directory
    def list_skills(self) -> list[SkillMetadata]
    def get_skill(self, name: str) -> SkillMetadata
    def get_prompt_summary(self) -> str        # For system prompt injection
```

**Discovery**: Scans `{workspace_dir}/skills/` for `SKILL.md` files with YAML frontmatter. Only frontmatter is parsed on discovery; full content is lazy-loaded on `get_skill()`.

### 4.6 Tools — `src/platform_agent/foundation/tools/`

| File | Tools | Purpose |
|------|-------|---------|
| `workspace.py` | `read_workspace_file`, `write_workspace_file`, `list_workspace_files` | Workspace file I/O |
| `github.py` | 13 tools (`github_create_repo`, `github_push_file`, `github_get_file`, etc.) | GitHub API (pure urllib) |
| `github_tool.py` | 12 tools (`github_get_repo`, `github_list_prs`, `github_create_issue`, etc.) | GitHub API (requests library) |
| `memory_tools.py` | `save_memory`, `recall_memory` | AgentCore Memory LTM |
| `claude_code.py` | `claude_code` | Claude Code CLI integration |

**Memory tools category mapping** (in `memory_tools.py`):

| Category | AgentCore Strategy ID |
|----------|-----------------------|
| fact | semanticKnowledge |
| preference | userPreferences |
| decision | semanticKnowledge |
| lesson | episodicMemory |
| todo | semanticKnowledge |

---

## 5. Hook Middleware

### 5.1 Hook Base — `src/platform_agent/foundation/hooks/base.py`

```python
class HookBase(_StrandsHookProvider):
    """Base class for all Foundation Agent hooks."""
    def pre_invoke(self, event) -> None
    def post_invoke(self, event) -> None
    def pre_tool_call(self, event) -> None
    def post_tool_call(self, event) -> None
```

All hooks extend `HookBase`, which wraps Strands SDK `HookProvider`. Hooks register for specific lifecycle events via `register_hooks(registry)` and fire on those events. Non-Strands hooks (e.g., `AIDLCTelemetryHook`) use alternative registration mechanisms.

### 5.2 Hook Lifecycle

```
BeforeInvocationEvent     ← Soul, Memory, Guardrails, Telemetry, Consolidation,
                            SessionRecording, BusinessMetrics, OTELSpan, Compaction

  ├── BeforeModelCallEvent    ← ModelMetrics, OTELSpan
  ├── AfterModelCallEvent     ← ModelMetrics, OTELSpan

  ├── BeforeToolCallEvent     ← ToolPolicy, Telemetry, OTELSpan, SessionRecording, Audit
  ├── AfterToolCallEvent      ← Audit, Telemetry, BusinessMetrics, Hallucination,
  │                              OTELSpan, SessionRecording

  ├── MessageAddedEvent       ← Memory

AfterInvocationEvent      ← Guardrails, Telemetry, MemoryExtraction,
                            SessionRecording, BusinessMetrics, OTELSpan
```

### 5.3 All Hooks (10 active)

| # | Hook | Category | Events | Purpose |
|---|------|----------|--------|---------|
| 1 | **SoulSystemHook** | always-on | BeforeInvocation | Reloads soul files from workspace before each invocation |
| 2 | **AuditHook** | always-on | BeforeTool, AfterTool | Logs all tool calls; DynamoDB + CloudWatch format |
| 3 | **TelemetryHook** | always-on | Full lifecycle | Invocation + tool span timing; CloudWatch EMF |
| 4 | **GuardrailsHook** | always-on | BeforeInv, AfterInv | Input/output validation (pluggable validators) |
| 5 | **MemoryHook** | domain | MessageAdded, BeforeInv | Records messages to session memory; enriches with workspace memory |
| 6 | **ModelMetricsHook** | domain | BeforeModel, AfterModel | LLM call latency and stop_reason tracking |
| 7 | **ToolPolicyHook** | domain | BeforeTool | Enforces tool allowlist/denylist; sets `event.cancel_tool` to block |
| 8 | **BusinessMetricsHook** | domain | Full lifecycle | Skill usage, DAU, session depth, artifact counts |
| 9 | **HallucinationDetectorHook** | domain | AfterTool | Captures tool outputs for offline consistency analysis |
| 10 | **SessionRecordingHook** | domain | Full lifecycle | Full session capture for S3 (`sessions/{tenant}/{date}/{session}.json`) |
| — | **OTELSpanHook** | not in default registry | Full lifecycle | OpenTelemetry spans (`plato.invoke`, `plato.tool.*`, `plato.model.invoke`) |
| — | **MemoryExtractionHook** | optional | AfterInvocation | Extracts structured memories; persists to `memory/extracted/` |
| — | **ConsolidationHook** | optional | BeforeInvocation | 3-gate consolidation (time + count + lock) → `memory/consolidated/` |
| — | **CompactionHook** | REMOVED from active hooks | BeforeInvocation | Log-only in v1; 9-section compaction prompt retained for reference |
| — | **AIDLCTelemetryHook** | domain (non-Strands) | Workflow events | AIDLC stage transition metrics; registered via `workflow.on_event()` |

### 5.4 Loading Paths

**Harness-driven loading** (when `harness` is provided):

1. Four always-on hooks are instantiated unconditionally: `SoulSystemHook`, `AuditHook`, `TelemetryHook`, `GuardrailsHook`
2. Iterate `harness.hooks` list — for each `HookConfig`:
   - Skip if already in always-on set
   - Evaluate `enabled_by` condition via `_is_hook_enabled()` (dotted-path resolution on harness)
   - Instantiate via `_make_hook()` factory method
3. All hooks passed to `strands.Agent(hooks=self.hook_registry)`

**Legacy loading** (when `harness=None`): All 11+ hooks active with sensible defaults.

**Conditional loading example** (`enabled_by`):
```yaml
- hook: MemoryExtractionHook
  category: optional
  enabled_by: memory_config.extraction_enabled  # resolves harness.memory_config.extraction_enabled
```

### 5.5 Zero Network I/O Principle

All hooks store data in-memory only. The entrypoint / Lambda is responsible for persisting to external stores (DynamoDB, S3, CloudWatch). This keeps hooks fast and testable.

---

## 6. Plato Domain Layer

### 6.1 Orchestrator — `src/platform_agent/plato/orchestrator.py`

Uses the **agent-as-tool routing pattern**: the orchestrator is itself a FoundationAgent that delegates to specialist agents built dynamically from the SkillPack registry.

```python
@dataclass
class AgentDefinition:
    description: str = ""
    prompt: str = ""
    tools: list[str] = field(default_factory=list)

def skillpack_to_agent_definition(skill: SkillPack) -> AgentDefinition
def build_agents_from_skills(skill_names: list[str] | None = None) -> dict[str, AgentDefinition]
def build_orchestrator_prompt(agents: dict[str, AgentDefinition]) -> str
async def run_orchestrator(prompt: str, cwd: str | None = None, ...) -> str
def run_orchestrator_sync(prompt: str, ...) -> str
```

**"NEVER DELEGATE UNDERSTANDING" principle**: Before routing any request, the orchestrator must (1) understand the full requirements itself, (2) decompose into a concrete spec, (3) pass spec AND original request to the specialist, (4) review the result before returning to the user.

**Specialist safety**: The `Task` tool is denied to specialists (`_SPECIALIST_DENIED_TOOLS`) to prevent unbounded delegation chains.

**Execution model**: Prefers Strands Agent; falls back to Bedrock Converse API (`bedrock_runtime.py`) when Strands is unavailable.

### 6.2 Skill Packs — `src/platform_agent/plato/skills/`

> All skill names now use kebab-case per the AgentSkills spec. `system_prompt_extension` is now empty string — `SKILL.md` is the sole prompt source.

| # | Skill Pack | Description | Key Tools |
|---|-----------|-------------|-----------|
| 1 | `aidlc_inception` | Guided AIDLC inception workflow | 7 aidlc_* tools |
| 2 | `code_review` | Security and quality code reviewer | Read, Glob, Grep |
| 3 | `debug` | Troubleshooting | Read, Glob, Grep, Bash |
| 4 | `deployment_config` | Deployment configuration generator | Read, Write, Edit, Bash, Glob, Grep |
| 5 | `design_advisor` | Platform readiness assessor (C1-C12) | Read, Glob, Grep |
| 6 | `fleet_ops` | Fleet operations management | Read, Glob, Grep, Bash |
| 7 | `governance` | Compliance checks | Read, Glob, Grep |
| 8 | `issue_creator` | Structured GitHub issue creator | create_spec_violation_issue, create_issues_from_review |
| 9 | `knowledge` | Reference lookup | Read, Glob, Grep |
| 10 | `monitoring` | Monitoring and alerting setup | Read, Glob, Grep, Bash |
| 11 | `observability` | Instrumentation guidance | Read, Glob, Grep, Bash |
| 12 | `onboarding` | Developer onboarding | Read, Write, Glob, Grep |
| 13 | `pr_review` | PR review with spec tracing | review_pull_request |
| 14 | `scaffold` | Project skeleton generator | Read, Write, Edit, Bash, Glob |
| 15 | `spec_compliance` | Spec compliance verification | check_spec_compliance, check_single_ac |
| 16 | `test_case_generator` | Spec-to-test-case (1:1 AC-to-TC) | generate_test_cases_from_spec |
| 17 | `architecture-knowledge` | Architecture patterns reference | Knowledge-only (no tools) |
| 18 | `cost-optimization` | Cost optimization guidance | Knowledge-only (no tools) |
| 19 | `migration-guide` | Migration guidance reference | Knowledge-only (no tools) |
| 20 | `policy-compiler` | Policy compilation reference | Knowledge-only (no tools) |
| 21 | `security-review` | Security review guidance | Knowledge-only (no tools) |
| 22 | `testing-strategy` | Testing strategy reference | Knowledge-only (no tools) |

**Base class** (`base.py`):
```python
class SkillPack:
    name: str
    description: str
    version: str
    system_prompt_extension: str = ""  # Empty — SKILL.md is sole prompt source
    tools: list                     # @tool-decorated functions
    mcp_servers: dict
```

**Discovery**: `discover_skills()` auto-imports all skill `__init__.py` modules, each of which calls `register_skill(name, SkillClass)` to populate the global registry.

### 6.3 AIDLC Workflow Engine — `src/platform_agent/plato/aidlc/`

The AI-Driven Lifecycle (AIDLC) engine guides users through structured inception, producing specification artifacts at each stage.

#### State Machine

```
IDLE → WORKSPACE_DETECTION → REQUIREMENTS → [USER_STORIES] →
       WORKFLOW_PLANNING → [APP_DESIGN] → [UNITS] → complete
```

Stages in brackets are **conditional** — skipped for SIMPLE complexity.

#### Stage Definitions — `stages.py`

| Stage | Conditional | Output Artifact | Gate |
|-------|-------------|----------------|------|
| WORKSPACE_DETECTION | No | — | Brownfield vs greenfield |
| REQUIREMENTS | No | `aidlc-docs/requirements.md` | Target users, capabilities, compliance |
| USER_STORIES | Yes | `aidlc-docs/user-stories.md` | Actors, journeys, edge cases |
| WORKFLOW_PLANNING | No | `aidlc-docs/workflow-plan.md` | Construction stages, strategy |
| APP_DESIGN | Yes | `aidlc-docs/app-design.md` | Components, APIs, data flow |
| UNITS | Yes | `aidlc-docs/units.md` | Work decomposition, dependencies |

#### Workflow — `workflow.py`

```python
class AIDLCWorkflow:
    def start(self) -> None                     # Initialize first stage
    def get_questions(self) -> list[Question]    # Complexity-adapted questions
    def submit_answers(self, answers) -> str     # Generate artifact, → AWAITING_APPROVAL
    def approve_stage(self, note: str) -> None   # Advance to next stage
    def reject_stage(self, reason: str) -> None  # Return to IN_PROGRESS
    def skip_stage(self) -> None                 # Skip conditional stage
    def assess_complexity(self) -> Complexity    # SIMPLE / STANDARD / COMPLEX
    def save(self) -> None                       # Persist to aidlc-docs/aidlc-state.json
    def load(self) -> None                       # Resume from persisted state
```

#### Complexity Scoring — `spec_scoring.py`

Heuristic scoring of Requirements answers:

- Multiple user types: +2
- Multi-channel (per extra): +1
- Compliance (weighted): +1–4
- Multiple data sources: +1 per extra
- Hybrid deployment: +1
- Multiple capabilities: +1 per extra

**Thresholds**: 0–2 → SIMPLE, 3–5 → STANDARD, 6+ → COMPLEX

#### Question Banks — `questions.py`

Each stage has BASE questions + COMPLEX_EXTRA questions. Question types: `MULTIPLE_CHOICE`, `FREE_TEXT`, `YES_NO`. SIMPLE/STANDARD get base only; COMPLEX gets base + extras.

#### Artifact Compilers — `artifacts.py`

Functions compile stage answers to markdown: `compile_requirements()`, `compile_user_stories()`, `compile_workflow_plan()`, `compile_app_design()`, `compile_units()`. Each includes a standard header (project name, repo, timestamp).

### 6.4 Control Plane — `src/platform_agent/plato/control_plane/`

Multi-agent orchestration infrastructure with tenant isolation.

#### Registry — `registry.py`

```python
class AgentState(Enum):
    BOOT, INITIALIZING, READY, BUSY, DEGRADED, TERMINATED

class AgentRecord:
    agent_id, tenant_id, role, capabilities, state, tools, config, last_heartbeat

class AgentRegistry:
    def register(self, ...) -> AgentRecord
    def deregister(self, agent_id) -> None
    def update_state(self, agent_id, new_state) -> None
    def find_by_capability(self, capability) -> list[AgentRecord]
```

**Valid state transitions**:
```
BOOT → INITIALIZING | TERMINATED
INITIALIZING → READY | DEGRADED | TERMINATED
READY → BUSY | DEGRADED | TERMINATED
BUSY → READY | DEGRADED | TERMINATED
DEGRADED → READY | TERMINATED
TERMINATED → (terminal)
```

#### Lifecycle — `lifecycle.py`

| Component | Purpose |
|-----------|---------|
| `ColdStartProtocol` | Boot → Initialize → Self-check → READY or DEGRADED |
| `HeartbeatManager` | Tracks heartbeats; marks DEGRADED on miss; auto-restart |
| `GracefulShutdown` | Drains tasks → deregisters → audit log |

#### Policy Engine — `policy_engine.py`

Extends Cedar guardrails with platform-level policies:

- **Cold-start denial**: Agent must be READY to act
- **Cross-boundary denial**: Tenant isolation enforcement
- **Rate limiting**: Configurable per agent/action (`RateLimitConfig`)
- **Content filtering**: Strips thinking/reasoning leak patterns

#### Task Manager — `task_manager.py`

```python
class TaskStatus(Enum):
    PENDING, ASSIGNED, CLAIMED, IN_PROGRESS, COMPLETED, FAILED, CANCELLED, RETRYING

class Task:
    task_id, tenant_id, intent, payload, required_capabilities, priority, deadline, retry_count

class TaskManager:
    def create_task(self, ...) -> Task
    def claim_task(self, task_id, agent_id) -> Task    # Atomic claim
    def assign_task(self, task_id, agent_id) -> Task
    def release_expired_claims(self, lease_seconds=300) -> list[Task]
    def retry_or_fail(self, task_id) -> Task

class TaskDispatcher:
    def dispatch(self, task) -> str | None    # Capability-based routing to best agent
```

#### Message Router — `message_router.py`

Middleware pipeline for inter-agent communication:

```
Message → AuthenticateMiddleware → PolicyCheckMiddleware →
          ContentFilterMiddleware → AuditLogMiddleware → CircuitBreaker → Deliver
```

Supports broadcast (target_agent = `"*"`) and point-to-point messaging.

#### Audit Store — `audit.py`

16 action types: `AGENT_REGISTERED`, `STATE_CHANGE`, `TASK_CREATED`, `TASK_CLAIMED`, `MESSAGE_SENT`, `POLICY_VIOLATION`, `CONTENT_FILTERED`, `CIRCUIT_BROKEN`, `HEARTBEAT_MISSED`, `COLD_START`, `GRACEFUL_SHUTDOWN`, etc.

#### DynamoDB Persistence — `dynamodb_store.py`

**Single-table design** (`plato-control-plane`):

| Access Pattern | PK | SK |
|---------------|----|----|
| Agent by tenant | `TENANT#{tenant_id}` | `AGENT#{agent_id}` |
| Task by tenant | `TENANT#{tenant_id}` | `TASK#{task_id}` |
| Audit by tenant | `TENANT#{tenant_id}` | `AUDIT#{ts}#{uuid}` |

**GSIs**:
- **GSI-1** (state-index): `GSI1PK = STATE#{state}`, `GSI1SK = TENANT#...#AGENT#...`
- **GSI-2** (capability-index): `GSI2PK = CAP#{capability}`, `GSI2SK = {confidence}#{agent_id}`

### 6.5 Evaluator Framework — `src/platform_agent/plato/evaluator/`

Implements a **reflect-refine loop** with deterministic checks grounding LLM scores.

#### Base — `base.py`

```python
class EvaluatorAgent:
    def deterministic_checks(self, output) -> list[ItemScore]  # Non-LLM checks (override)
    def build_evaluation_prompt(self, output, rubric) -> str
    def evaluate_once(self, output) -> EvaluationResult
    def evaluate_with_refinement(self, output, max_iterations) -> EvaluationSession
```

**Reflect-refine loop**:
```
for i in 1..max_iterations:
    1. Evaluate specialist output → EvaluationResult
    2. If passed → status: approved
    3. If not passed and i < max_iter:
       - Provide feedback_for_revision
       - Specialist revises
       - Continue loop
    4. If i == max_iter → status: escalated (handoff)
```

**Score merging**: Deterministic checks run first, then LLM evaluation. **Deterministic results override LLM scores** for the same rubric items. This prevents false-positive evaluation claims.

**Honesty preamble** (prepended to ALL evaluation prompts):
> "You are an independent evaluator. Your job is to find real problems, not to validate or approve. If the output is bad, say it is bad."

#### Specialist Evaluators

| Evaluator | Rubric Items | Key Thresholds |
|-----------|-------------|----------------|
| `CodeReviewEvaluator` | coverage (1.5), accuracy (2.0), security_depth (1.5), fix_quality (1.0), prioritization (1.0) | accuracy ≥ 0.8 |
| `DesignEvaluator` | C1-C12 readiness checklist | all 12 items pass |
| `DeploymentEvaluator` | Deployment configuration quality | — |
| `ScaffoldEvaluator` | Scaffold completeness | — |

---

## 7. Three-Layer Memory Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1: FileSessionManager (Strands SDK)                       │
│  ─────────────────────────────────────────                       │
│  • Conversation persistence per session_id                       │
│  • Storage: /mnt/workspace/.sessions/{session_id}.json           │
│  • Automatic: Strands Agent handles read/write                   │
│  • Complementary to STM (session replay vs. LTM extraction)     │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 2: AgentCore Memory (STM → LTM pipeline)                  │
│  ──────────────────────────────────────────────                  │
│  • STM: _ingest_to_stm() writes user+assistant messages per turn │
│  • AgentCore async extraction (~60s) promotes STM → 4 strategies │
│  • LTM: _load_ltm_context() queries all 4 strategies:           │
│    - userPreferences  (+0.1 score boost)                         │
│    - conversationSummary                                         │
│    - semanticKnowledge                                           │
│    - episodicMemory                                              │
│  • Cross-strategy deduplication (normalized text, keep highest)  │
│  • Budget-capped: MAX_LTM_CHARS = 6000 (~1500 English tokens)   │
│  • Injected as <long-term-memory> with section labels            │
│  • Tools: save_memory (persist) + recall_memory (query)          │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  Layer 3: Workspace Files (agent work products)                  │
│  ──────────────────────────────────────────                      │
│  • MEMORY.md + memory/*.md (WorkspaceMemory)                     │
│  • aidlc-docs/ (AIDLC workflow artifacts)                        │
│  • /mnt/workspace/projects/ (agent work products)                │
│  • DEPRECATED: memory/extracted/, memory/consolidated/           │
└──────────────────────────────────────────────────────────────────┘
```

### Write Path (per conversation turn)

1. `_ingest_to_stm(actor_id, session_id, user_msg, assistant_msg)` — fire-and-forget
2. AgentCore async extraction (~60s) promotes STM events → 4 LTM strategies
3. `FileSessionManager` auto-persists conversation for Strands replay

### Read Path (first turn of new session)

1. `_load_ltm_context()` queries all 4 strategies with semantic matching against `current_message`
2. Results globally ranked by relevance score
3. Preferences get +0.1 score boost
4. Cross-strategy deduplication (normalized text, highest score wins)
5. Budget-capped at `MAX_LTM_CHARS = 6000` chars
6. Formatted by section: `[User Preferences]` → `[Previous Conversations]` → `[Relevant Knowledge]` → `[Past Interactions]`

### Agent-Initiated Memory

- `save_memory` tool with categories: fact, preference, decision, lesson, todo
- `recall_memory` tool for explicit search
- Active memory curation instructions in `workspace/AGENTS.md` prompt (agent proactively saves corrections, preferences, decisions, environments, action items)

### Memory Tools — `src/platform_agent/foundation/tools/memory_tools.py`

```python
def create_memory_tools(memory_backend, actor_id, session_id) -> list:
    """Factory: returns [save_memory, recall_memory] bound to backend."""

@tool
def save_memory(content: str, category: str) -> str:
    """Save a memory. Categories: fact, preference, decision, lesson, todo."""

@tool
def recall_memory(query: str, category: str | None = None) -> str:
    """Search long-term memory with optional category filter."""
```

### Memory Backend — `src/platform_agent/memory.py`

| Class | Backend | Use Case |
|-------|---------|----------|
| `AgentCoreMemory` | Bedrock AgentCore API | Production (STM ingest + LTM retrieval) |
| `LocalMemory` | In-memory dict | Development/testing |

STM `create_event`/`list_events` are **active** — `_ingest_to_stm()` calls `add_user_message()`/`add_assistant_message()` which feed the STM → LTM pipeline. FileSessionManager is complementary (conversation replay), not a replacement.

### Memory Hooks Status

| Hook | Status | Notes |
|------|--------|-------|
| `MemoryHook` | **ACTIVE** | Records messages to its own SessionMemory instance; workspace enrichment is no-op |
| `MemoryExtractionHook` | **DEPRECATED** | Disabled (`enable_memory_extraction=False`); replaced by AgentCore STM → LTM pipeline |
| `ConsolidationHook` | **DEPRECATED** | Never enabled in entrypoint; replaced by AgentCore strategies |
| `CompactionHook` | **DEPRECATED** | Removed from active hooks; Strands SDK handles context management |

### Multi-Tenant Isolation

- `actor_id` from JWT (Cognito sub claim) → namespace scoping
- All LTM queries scoped to `/strategies/{id}/actors/{actorId}/`
- Future: team-level namespace for shared knowledge

### Verification

- `scripts/e2e_memory_test.py` — basic cross-session recall (integrated into `deploy.sh`)
- `scripts/e2e_memory_multiturn.py` — 5 scenarios: cross-session, preference override, user isolation, active curation, token cap

> **Deep dive**: For a detailed comparison of Plato's memory system with Hermes and OpenClaw, including the personal-assistant vs. multi-tenant design tradeoffs, see [`docs/MEMORY_DEEP_DIVE.md`](MEMORY_DEEP_DIVE.md).

---

## 8. Deployment Architecture

### 8.1 AgentCore Runtime — `entrypoint.py`

```python
from bedrock_agentcore import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload, context=None) -> dict:
    """HTTP entry point. Returns {"result": response_text}."""

@app.websocket
async def ws_handler(websocket, context=None):
    """WebSocket entry point for real-time streaming."""

if __name__ == "__main__":
    app.run()
```

**Deployment**:
```bash
agentcore configure -e entrypoint.py -r us-west-2
agentcore deploy
agentcore invoke '{"prompt": "Hello!"}'
```

### 8.2 AgentPool — `entrypoint.py:185`

```python
class AgentPool:
    """Thread-safe pool of per-session FoundationStrandsAgent instances."""

    def __init__(self, max_size: int = 100)
    def get_or_create(self, session_id, actor_id) -> FoundationStrandsAgent
    def acquire_session(self, session_id, blocking=True) -> bool
    def release_session(self, session_id) -> None
```

| Feature | Implementation |
|---------|---------------|
| LRU tracking | `OrderedDict` with `move_to_end()` |
| Per-session locks | `dict[str, threading.Lock]` |
| Eviction | When pool > max_size, oldest popped |
| Concurrency | Blocking acquire (HTTP), non-blocking (WebSocket) |
| Lazy init | Agents created on first request, not startup |

### 8.3 Lazy Initialization

AgentCore Runtime requires initialization within 30 seconds. Heavy work is deferred to first `invoke()`:

```python
_initialized = False
_init_lock = threading.Lock()

def _ensure_initialized():
    """Runs once on first invoke."""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        # Initialize: GitHub tools, AIDLC tools, AgentPool, AgentCore Memory
        _initialized = True
```

### 8.4 Slack Integration — `src/platform_agent/slack/`

**Two-Lambda async pattern** with SQS FIFO:

```
Slack Events API
    │
    ▼
plato-slack-ack (lambda_handler)          ← returns 200 within 3s
    │  Verify signature (HMAC-SHA256)
    │  Enqueue to SQS FIFO
    │    MessageDeduplicationId = f"{channel}-{ts}"
    │    MessageGroupId = f"{channel}-{thread_ts}"
    ▼
SQS FIFO Queue
    │
    ▼
plato-slack-worker (sqs_worker)           ← processes messages
    │  Invoke AgentCore Runtime
    │  Post response to Slack (chat.postMessage / chat.update)
    ▼
Slack Channel
```

**Three-layer deduplication**:
1. **SQS FIFO**: `MessageDeduplicationId` (5-min window)
2. **Handler in-memory**: `_processed_events` dict (10-min TTL)
3. **Cross-container**: `conversations.replies` API (disabled)

**Session ID generation** (`SlackMessage.memory_session_id`):
```python
thread → f"plato-thread-{thread_ts}"     # Thread context
DM     → f"plato-dm-{user_id}"           # Persistent DM
channel → f"plato-chan-{channel}-{user}"  # Channel + user
# Padded to 33 chars (AgentCore minimum)
```

**Thinking indicator pattern**:
1. Post "Processing..." immediately (instant feedback)
2. Invoke agent (10-60s)
3. Update message with real response (`chat.update`)
4. On error: delete indicator for clean SQS retry

### 8.5 WebSocket Streaming — `entrypoint.py:466`

```python
@app.websocket
async def ws_handler(websocket, context=None):
    event_queue: queue.Queue = queue.Queue()  # Thread-safe
    _DONE = object()                          # Sentinel

    class _WSCallbackHandler:
        def __call__(self, **kwargs):
            # Push events to queue: delta, tool_start, complete, error

    # Sync-to-async bridge
    loop.run_in_executor(None, _run_agent)

    # Async loop: poll queue → send to WebSocket
    while True:
        evt = await loop.run_in_executor(None, lambda: event_queue.get(timeout=1.0))
        if evt is _DONE:
            break
        await websocket.send_text(json.dumps(evt))
```

**WebSocket protocol**:
```json
// Client sends
{"prompt": "...", "user_id": "...", "session_id": "..."}

// Server sends (streaming)
{"type": "delta", "content": "token"}
{"type": "tool_start", "name": "tool_name"}
{"type": "complete", "content": "full response"}
{"type": "error", "message": "..."}
```

---

## 9. Protocols & Integration

### 9.1 A2A Protocol — `src/platform_agent/foundation/protocols/a2a.py`

Agent-to-Agent communication protocol.

```python
class AgentCard:
    """Metadata describing agent capabilities."""
    agent_id, name, description, version, capabilities, input_schema, output_schema, endpoint

class A2AMessage:
    message_id, message_type, sender_id, receiver_id, task_id, payload, correlation_id
    def create_response(self, message_type, payload) -> A2AMessage

class A2AServer:
    def register_handler(self, message_type: MessageType, handler: Callable)
    async def handle(self, message: A2AMessage) -> A2AMessage

class A2AClient:
    def register_agent(self, card: AgentCard)
    async def discover(self, agent_id: str) -> AgentCard | None
    async def send_task(self, agent_id: str, payload: dict) -> A2AMessage
```

**Message types**: TASK, RESULT, STATUS, ERROR, DISCOVER, CARD.
**Task statuses**: PENDING, IN_PROGRESS, COMPLETED, FAILED, CANCELLED.

### 9.2 MCP Protocol — `src/platform_agent/foundation/protocols/mcp.py`

Model Context Protocol adapter for tool hosting and invocation.

```python
class MCPTool:
    name, description, input_schema, output_schema, metadata
    def validate_input(self, input_data) -> list[str]

class MCPServer:
    def register_tool(self, tool: MCPTool, handler: ToolHandler)
    def list_tools(self) -> list[MCPTool]
    async def execute(self, tool_name: str, input_data: dict) -> ToolResult

class MCPClient:
    def register_server(self, server: MCPServer)
    def list_tools(self, server_id: str | None = None) -> list[MCPTool]
    async def invoke(self, tool_name: str, input_data: dict, ...) -> ToolResult
```

### 9.3 Handoff Protocol — `src/platform_agent/foundation/handoff/agent.py`

Structured human escalation for when automated evaluation fails.

```python
class HandoffRequest:
    source_agent, reason, priority, summary, context, conversation_history
    evaluation_report, iteration_count, last_score, threshold
    @property
    def is_evaluator_escalation(self) -> bool

class HandoffResponse:
    request_id, status, decision, instructions, reviewer

class HandoffChannel(ABC):
    async def send(self, request: HandoffRequest) -> bool
    async def poll(self, request_id: str) -> HandoffResponse | None

class HandoffAgent:
    def create_request(self, source_agent, reason, summary, priority, ...) -> HandoffRequest
    def create_from_evaluation(self, session) -> HandoffRequest  # From EvaluationSession
    async def escalate(self, request: HandoffRequest) -> bool
```

**Statuses**: PENDING → ACKNOWLEDGED → RESOLVED | REJECTED | EXPIRED.
**Decisions**: approve, reject, revise, override.

**Evaluator integration**: When `evaluate_with_refinement()` exhausts max iterations without passing, it produces an `EvaluationSession` that `create_from_evaluation()` converts into a `HandoffRequest` with full evaluation context.

---

## 10. Testing

### Structure

```
tests/
├── conftest.py                   # Pre-import mocks (Strands SDK, AgentCore)
├── test_agent_behavior.py        # FoundationAgent integration
├── test_aidlc_workflow.py        # AIDLC state machine
├── test_aidlc_inception_skill.py # AIDLC skill pack
├── test_aidlc_telemetry.py       # AIDLC metrics hook
├── test_audit.py                 # Audit store
├── test_bedrock_runtime.py       # Bedrock Converse fallback
├── test_business_metrics.py      # BusinessMetricsHook
├── test_cc_tool.py               # Claude Code tool
├── test_chaos.py                 # Chaos/resilience tests
├── test_cli.py                   # CLI commands
├── test_concurrency.py           # Concurrent agent access
├── test_control_plane_*.py       # Registry, lifecycle, policy
├── test_e2e_*.py                 # End-to-end user journeys
├── test_evaluator*.py            # Evaluator framework
├── test_foundation*.py           # FoundationAgent unit tests
├── test_github_tools*.py         # GitHub tool tests
├── test_guardrails.py            # Guardrails hook
├── test_hallucination_detector.py # Hallucination hook
├── test_handoff.py               # Handoff protocol
├── test_harness_*.py             # DomainHarness schema + memory config
├── test_hook_middleware.py        # Hook loading + lifecycle
├── test_memory*.py               # Memory layer (4 test files)
├── test_orchestrator.py          # Orchestrator routing
├── test_protocols.py             # A2A + MCP adapters
├── test_session_*.py             # FileSessionManager integration
├── test_skill_system.py          # Skill registry
├── test_slack_integration.py     # Slack handler
├── test_soul_system.py           # Soul file loading
├── ... (87 files total)
└── test_tool_registration.py     # Tool registration
```

### Counts

| Metric | Value |
|--------|-------|
| Test files | 87 |
| Test functions | 1,868+ |
| Total test lines | ~25,550 |

### Configuration — `pyproject.toml`

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

### Mock Strategy — `tests/conftest.py`

All external dependencies are mocked before import:

- **Strands SDK**: `strands.Agent` → `_FakeAgent`, `strands.tool` → identity decorator, `BedrockModel` → `_FakeBedrockModel`, `FileSessionManager` → `_FakeFileSessionManager`
- **AgentCore SDK**: `bedrock_agentcore` → optional import with fallback
- **Hook events**: `BeforeInvocationEvent`, `AfterInvocationEvent`, etc. → mock dataclasses

### Key Test Categories

| Category | Files | Focus |
|----------|-------|-------|
| Foundation agent | 3 | Agent build, invoke, tool registration |
| Hook middleware | 6+ | Hook loading, lifecycle events, metrics |
| Memory | 4 | SessionMemory, WorkspaceMemory, FileSessionManager, tools |
| AIDLC workflow | 3 | State machine, questions, artifacts |
| Control plane | 7 | Registry, lifecycle, policy, tasks, messages, DynamoDB |
| Evaluators | 4 | Rubric scoring, reflect-refine loop |
| Skills | 12+ | One test file per skill pack |
| Integration/E2E | 5 | End-to-end flows, agent behavior |
| Protocols | 2 | A2A, MCP adapters |
| Slack | 1 | Handler, signature verification |

---

## 11. Key Design Decisions

### DomainHarness as Frozen Dataclass

**Decision**: All domain configuration expressed as a frozen (immutable) dataclass, YAML-serializable.

**Rationale**: Separates "what the agent is" (pure data) from "how it runs" (runtime logic). Enables configuration-as-code, version control, and instantiation from YAML files. Frozen prevents accidental mutation during agent lifecycle.

**Trade-off**: Cannot use computed fields — all values must be explicit at construction time.

### FileSessionManager over STM

**Decision**: Use Strands SDK's `FileSessionManager` for conversation persistence instead of AgentCore STM `create_event`/`list_events`.

**Rationale**: FileSessionManager integrates natively with Strands Agent's conversation loop, eliminating manual message tracking for conversation replay. STM `create_event()` is still called by `_ingest_to_stm()` to feed the STM → LTM extraction pipeline — this is complementary, not redundant.

**Note**: STM `create_event`/`list_events` are internal to `AgentCoreMemory`; they are NOT exposed as agent tools but are called automatically by the entrypoint after each conversation turn.

### Hook Middleware over Inheritance

**Decision**: Compose agent behavior via lifecycle hooks rather than class inheritance hierarchies.

**Rationale**: Hooks are independently testable, composable (mix-and-match via `HookConfig`), and configurable (enable/disable via `enabled_by` conditions). An inheritance-based approach would require creating subclasses for every combination of behaviors.

**Pattern**: Each hook subscribes to specific Strands lifecycle events. The `FoundationAgent` passes the hook registry to `strands.Agent(hooks=...)`, which calls each hook at the appropriate lifecycle point.

### Prompt Cache Awareness

**Decision**: Keep the system prompt static (soul + skills) and inject dynamic context (date, LTM) outside the system prompt.

**Rationale**: Bedrock's prompt caching hashes the system prompt. If dynamic values (date, LTM context) were embedded in the system prompt, every invocation would miss the cache. By injecting dynamic content as user messages or via hooks, the system prompt remains stable across invocations, enabling cache hits.

**Implementation**: `_prompt_hash` (SHA256) tracks system prompt stability. LTM is prepended to the first user message as `<long-term-memory>...</long-term-memory>`.

### Session Isolation via AgentPool

**Decision**: Each `session_id` gets its own `FoundationStrandsAgent` instance with separate conversation history and per-session lock.

**Rationale**: Strands Agent does not support concurrent `invoke()` on the same instance. Per-session locks prevent race conditions. LRU eviction (max 100 sessions) bounds memory usage.

**Trade-off**: Memory overhead of maintaining multiple agent instances. Mitigated by lazy initialization and LRU eviction.

### Two-Lambda Slack Pattern

**Decision**: Separate the Slack acknowledgment (3s response) from agent processing using SQS FIFO.

**Rationale**: Slack requires a 200 response within 3 seconds. Agent invocations take 10-60 seconds. SQS FIFO provides exactly-once delivery and per-thread ordering, ensuring messages in the same Slack thread are processed sequentially.

### Evaluator: Deterministic Checks Override LLM

**Decision**: Run deterministic (non-LLM) checks first, then LLM evaluation, with deterministic results overriding LLM scores for the same rubric items.

**Rationale**: LLM evaluators can produce false positives (claiming code passes checks when it doesn't). Deterministic checks (e.g., "is ruff available?", "are line numbers referenced?") provide ground truth that overrides potentially hallucinated LLM scores.

### "Never Delegate Understanding"

**Decision**: The orchestrator must understand the full request before delegating to specialists.

**Rationale**: A blind dispatcher produces poor results because specialists lack broader context. The orchestrator decomposes requests into concrete specs, delegates with precise instructions, and reviews results before returning to the user.
