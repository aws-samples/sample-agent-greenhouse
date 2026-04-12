# Changelog

All notable changes to Agent Greenhouse will be documented in this file.

## [1.2.0] - 2026-04-12

### Added
- *Score-based LTM token cap*: `_load_ltm_context()` caps total injected context at `MAX_LTM_CHARS = 6000` (~1500 English tokens). Results are globally ranked by relevance score with preference boost (+0.1), deduplicated across strategies, and budget-trimmed.
- *Active memory curation prompt*: `workspace/AGENTS.md` instructs the agent to proactively save corrections, preferences, decisions, environments, and action items via `save_memory` tool.
- *E2E memory test suite*: `scripts/e2e_memory_multiturn.py` covers 5 scenarios — cross-session recall, preference override, user isolation, active curation, and token cap verification. Basic test (`scripts/e2e_memory_test.py`) integrated into `deploy.sh`.

### Changed
- *Multi-strategy LTM context*: `_load_ltm_context()` queries all 4 AgentCore Memory strategies (userPreferences, conversationSummary, semanticKnowledge, episodicMemory) with cross-strategy deduplication and section-labeled output.
- *Deprecated hooks marked*: `MemoryExtractionHook` (`enable_memory_extraction=False`), `ConsolidationHook` (never enabled), and `CompactionHook` (removed from active hooks) are formally deprecated. AgentCore STM → LTM pipeline and Strands SDK replace their functionality.

### Removed
- *Dead code cleanup*: Removed ~1539 lines of unused code including deprecated hook logic, orphaned utilities, and stale test fixtures.

## [1.0.0] - 2026-04-11

### Added
- **Foundation Agent**: Generic, reusable agent runtime with hooks, memory, guardrails, soul system, and deployment helpers
- **Domain Harness**: Pure-data configuration (frozen dataclass, YAML-serializable) for specialist agents
- **Plato**: First domain agent — platform agent for Amazon Bedrock AgentCore
  - 16 skill packs (code review, scaffolding, AIDLC inception, compliance, deployment config, etc.)
  - Each skill pack includes SKILL.md for progressive loading via Strands AgentSkills plugin
  - Evaluator agents with reflect-refine quality gates
  - Orchestrator for multi-skill routing
  - Control plane (registry, lifecycle, task manager)
- **Hook Middleware**: 16 hooks including SoulSystem, Memory, Audit, Guardrails, Telemetry, OTEL, ToolPolicy, Compaction, Approval, and more
- **Three-layer Memory**: Conversation (STM) → Long-term (LTM) → Workspace memory with namespace isolation
- **Multi-strategy LTM context**: `_load_ltm_context()` queries all 4 AgentCore Memory strategies (userPreferences, conversationSummary, semanticKnowledge, episodicMemory) with semantic matching against the current user message and section-labeled output
- **STM ingestion**: `_ingest_to_stm()` writes user + assistant messages to AgentCore Memory STM after each turn (fire-and-forget), feeding the STM → LTM pipeline for automatic long-term insight extraction
- **AgentSkills Plugin Integration**: Strands SDK AgentSkills for progressive skill loading (metadata in prompt, full content on-demand)
- **Deployment**: Amazon Bedrock AgentCore deployment with containerized runtime
- **Slack Integration**: Real-time messaging with thread tracking, typing indicators, and multi-workspace support
- **1900+ Tests**: Comprehensive test suite covering unit, integration, and e2e scenarios
- **MCP Server Support**: AWS Documentation and Bedrock AgentCore MCP servers
- **Cedar Policy Guardrails**: Fine-grained access control via Cedar policies
