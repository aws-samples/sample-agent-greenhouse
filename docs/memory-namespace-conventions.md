# Memory Namespace Conventions

## Production Strategy Namespace Templates

Production memory (`plato_container_mem-PLACEHOLDER`) has per-strategy namespace
templates that are loaded at runtime via `get_memory`. There is no single common
prefix across all strategies:

| Strategy | Namespace Template |
|---|---|
| SemanticFacts | `/users/{actorId}/facts/` |
| SessionSummaries | `/summaries/{actorId}/{sessionId}/` |
| UserPreferences | `/users/{actorId}/preferences/` |
| episodicMemory | `/strategies/{memoryStrategyId}/actors/{actorId}/` |

## How `search_long_term` Works (Post-Fix)

1. **actor_id is required** — empty string or `"default"` is rejected.
2. Strategy templates are lazily loaded from AgentCore via
   `bedrock-agentcore-control:get_memory` and cached per instance.
3. One `retrieve_memory_records` call is issued per strategy, with
   `{actorId}`, `{memoryStrategyId}`, and `{sessionId}` substituted.
4. When `session_id` is not provided, the `{sessionId}/` segment is dropped
   to enable cross-session (actor-level) search.
5. A defensive **prefix-match post-filter** drops any record whose namespace
   does not match a known actor-substituted template. Dropped records are
   logged at ERROR level (`MEMORY LEAK BLOCKED`).
6. Results are deduplicated by `record_id`, sorted by score, and truncated
   to `top_k`.

The root namespace `"/"` is **never** passed to `retrieve_memory_records`.

## `setup_memory.py` is Stale

`scripts/setup_memory.py` uses a uniform namespace template
(`/strategies/{memoryStrategyId}/actors/{actorId}/`) for all strategies, which
does not match production. **Do not run `setup_memory.py` against the production
memory resource** — it would overwrite the correct per-strategy templates.

## Contract Summary

- `actor_id` is always required for long-term search.
- No root namespace searches. Ever.
- Post-filter is defense-in-depth — the primary isolation is the per-strategy
  namespace prefix passed to the API.
