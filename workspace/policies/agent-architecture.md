# Agent Architecture Standards — v1
<!-- plato-policy-version: architecture-v1 -->

## Applies To: Tier 1 and Tier 2

These standards ensure agents are built with production-quality patterns
that scale, maintain, and operate reliably.

## Framework Requirements

- Use Strands SDK as the agent framework (standardized across the organization)
- Register all tools via `@tool` decorator with proper docstrings and type hints
- Use hook middleware for cross-cutting concerns (not inline logic):
  - `SoulSystemHook` — personality and system prompt injection
  - `MemoryHook` — conversation context management
  - `AuditHook` — tool call logging
  - `GuardrailsHook` — input/output validation
  - `ToolPolicyHook` — tool access control
  - `CompactionHook` — conversation summarization for long sessions

## Memory Architecture

- Use AgentCore Memory for all persistent state (not local files or databases)
- **STM (Short-Term Memory)**: Automatic per-session conversation events
- **LTM (Long-Term Memory)**: Strategy extraction for cross-session knowledge
- Configure all 4 strategies: Semantic, UserPreference, Summary, Episodic
- Use namespace isolation for user separation: `/actors/{actorId}/`
- Never store user data in shared namespaces
- Use `save_memory` tool for explicit high-value fact persistence
- Implement memory context loading at session start (dual-layer: LTM + STM)

## Session Management

- Use UUID format for session IDs (minimum 33 characters for AgentCore)
- Design session IDs for cross-invocation continuity (e.g., thread-based)
- Implement agent pooling with LRU eviction for resource management
- Handle session timeout gracefully with context preservation

## Tool Design

- Each tool should do one thing well (single responsibility)
- Tools must return string output (not structured objects)
- Include comprehensive error handling in every tool
- Document expected inputs and outputs in tool docstrings
- Set appropriate timeouts for external service calls
- Tools that modify state must be idempotent where possible

## Configuration

- All configuration via environment variables (12-factor app principles)
- Provide sensible defaults for non-critical configuration
- Use `.bedrock_agentcore.yaml` for deployment configuration
- Never hardcode region, account ID, or resource ARNs in application code

## System Prompt Design

- Use Soul System pattern: separate identity (SOUL.md) from behavior (AGENTS.md)
- Platform files baked into container image (deployment artifacts)
- Keep system prompts focused and under 4000 tokens where possible
- Include skill summaries in system prompt, full skill content loaded lazily
