# Memory namespace conventions

The Plato runtime stores conversation events in **AgentCore Memory**, then
relies on per-strategy *namespace templates* to decide which records each
caller is allowed to see.

This doc explains how the production memory is laid out, why
`scripts/setup_memory.py` is **stale**, and the contract that the runtime
honours when calling `retrieve_memory_records`.

## Production memory

* **Memory ID**: `your_memory-XXXXXXXXXX` (us-west-2)

The memory has four strategies. Templates are loaded at runtime by
`AgentCoreMemory._load_strategy_templates()` via
`bedrock-agentcore-control:get_memory`:

| Strategy | strategyId | namespace template |
|---|---|---|
| SemanticFacts | `SemanticFacts-4BpYKz51rk` | `/users/{actorId}/facts/` |
| SessionSummaries | `SessionSummaries-CP05VmBYB3` | `/summaries/{actorId}/{sessionId}/` |
| UserPreferences | `UserPreferences-s23CZM64Lw` | `/users/{actorId}/preferences/` |
| episodicMemory | `episodicMemory-1QD9JE5IHs` | `/strategies/{memoryStrategyId}/actors/{actorId}/` |

There is no single prefix that covers all four. Do **not** hardcode
`/users/{actorId}/`. The runtime substitutes `{actorId}`,
`{memoryStrategyId}`, and `{sessionId}` per call.

## actor_id canonicalisation (2026-05)

Pre-2026-05: `actor_id` = Slack user ID (`U0EXAMPLE000`).
2026-05 (interim): `actor_id` = Cognito `sub` UUID
(`2801b300-9081-702c-…`).
2026-05 (current): `actor_id` = Cognito `cognito:username` (`melanie`,
`roger`, `frank`).

Switching to `cognito:username` because it is:

* stable (does not regenerate when a Cognito user is recreated),
* human-readable in CloudWatch and namespaces,
* identical for JWT and SigV4 callers (the Slack handler now passes
  `user_name` set to the Cognito username).

`scripts/migrate_actor_namespace.py` replays old Slack-ID-keyed events
under the new username namespace. After applying, the SemanticFacts /
UserPreferences / SessionSummaries / episodicMemory strategies
re-extract records under the new actor_id, typically within 1\u20135 min.

## `setup_memory.py` is stale

`scripts/setup_memory.py` declares
`/strategies/{memoryStrategyId}/actors/{actorId}/` for **all** strategies.
Production was provisioned via the AWS console or an earlier code path
and does not match. Re-running `setup_memory.py` against
`your_memory-XXXXXXXXXX` would clobber the real templates and
make every strategy invisible.

Until the script is rewritten to match production, **do not run it
against the production memory**. Tests use ephemeral memories created in
fixture setup.

## `search_long_term` contract

`AgentCoreMemory.search_long_term(actor_id=...)`:

1. **Refuses** any call where `actor_id` is empty or the literal sentinel
   `"default"`. This makes \u201croot\u201d searches (`namespace="/"`) impossible.
2. Calls `_load_strategy_templates()` lazily and caches the result for
   the lifetime of the instance.
3. Issues one `retrieve_memory_records` call per strategy template,
   substituting `{actorId}`, `{memoryStrategyId}`, and `{sessionId}` if
   present. When `session_id` is missing, the `{sessionId}/` segment is
   dropped to keep actor-level isolation but go cross-session.
4. Merges results, applies a defensive `startswith` post-filter against
   the resolved-actor prefix list, dedups by `record_id`, sorts by
   score, returns top-k.
5. Logs `MEMORY LEAK BLOCKED` at ERROR level any time the post-filter
   actually drops a record. Investigate every such log line.

`LocalMemory.search_long_term` keeps the legacy `project=...` shortcut
working for tests; production uses `AgentCoreMemory`.

## Defence-in-depth

* `foundation/memory_access_guard.py` rejects `namespace=="/"` outright
  so that even a code regression in `_actor_namespace`-style helpers
  cannot drop the per-actor scope.
* `entrypoint.py::_extract_identity` requires the JWT path or a
  non-`default` payload identity. Calls without a real identity arrive
  at `search_long_term` with `actor_id="default"` and are refused.
* CloudWatch metric `MemoryLeakBlocked` (planned) will alert on
  post-filter drops in production. Until that lands, search the runtime
  log group for `MEMORY LEAK BLOCKED` daily.

---
Last updated: 2026-05-18 (Plato actor_id canonicalisation work).
