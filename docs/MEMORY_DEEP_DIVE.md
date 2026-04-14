# Memory Deep Dive: Agent Memory Architecture

## Why Agent Memory Matters

Large Language Models are stateless: every request starts from scratch. Without memory, an agent forgets preferences, repeats mistakes, and asks the same questions session after session. Memory transforms a stateless model into a persistent collaborator.

But memory for agents is not just "save and load text." The design choices—what to remember, how to organize it, who can access it, and when to forget—define the agent's personality, reliability, and scalability.

This document compares three real-world memory architectures, explores the key differences between personal assistants and multi-tenant platform agents, and describes Plato's approach in detail.

---

## Three Memory Architectures Compared

### 1. Hermes Agent (NousResearch) — File-Based, Agent-Curated

Hermes is NousResearch's open-source coding agent. Its memory system is deceptively simple: a single `MEMORY.md` file with a hard token cap.

**How it works:**
- Memory is a plain-text file in the agent's workspace
- Hard cap of ~2,200 characters (roughly 550 tokens)
- The agent itself decides what to save, update, and delete
- A periodic "nudge" prompt reminds the agent to review and curate its memory
- Memory is loaded into the system prompt at session start

**Key design choices:**
- *Agent-as-curator*: The model decides what's worth remembering. No backend extraction, no embeddings, no retrieval pipeline.
- *Bounded by design*: The hard cap forces the agent to prioritize. Old, low-value memories get evicted to make room for new ones.
- *Single-user*: One agent, one human, one memory file. No multi-tenancy concerns.

**Strengths:**
- Zero infrastructure beyond file storage
- The agent develops genuine "judgment" about what matters
- Natural distillation over time: only high-value memories survive
- Simple to debug (just read the file)

**Weaknesses:**
- No semantic search; everything is loaded every time
- Capacity is tiny; complex projects can exhaust the budget quickly
- No separation between types of memory (facts vs. preferences vs. episodes)
- Memory quality depends entirely on the model's curation ability

### 2. OpenClaw — Git-Synced Workspace

OpenClaw is an open-source personal AI assistant that runs 24/7. Its memory is a git-managed workspace with multiple files.

**How it works:**
- `MEMORY.md` for curated long-term knowledge
- `memory/YYYY-MM-DD.md` for daily logs
- `SOUL.md`, `USER.md` for identity and user context
- Git provides version control, branching, and multi-device sync
- Heartbeat checks periodically trigger memory maintenance (distill daily notes to MEMORY.md)
- Memory search via semantic embedding of markdown files

**Key design choices:**
- *File-per-concern*: Different files for different purposes (identity, user profile, daily logs, long-term memory)
- *Agent-as-curator with structure*: The agent writes daily notes freely, then periodically consolidates
- *Git as shared brain*: Multiple agent instances can sync via git push/pull
- *No hard cap*: Memory grows over time; periodic maintenance keeps it manageable

**Strengths:**
- Rich context; the agent can maintain detailed project histories
- Multi-instance sync through git (multiple agents sharing one workspace)
- Human-readable and human-editable
- Version history; nothing is permanently lost

**Weaknesses:**
- Memory grows without bound if maintenance is skipped
- No native semantic search (relies on loading files into context)
- git conflicts can occur with multiple writers
- Single-user by design; multi-tenancy would require workspace-per-user

### 3. Plato (Platform Agent for AgentCore) — STM/LTM Pipeline

Plato is a multi-tenant platform agent running on Amazon Bedrock AgentCore. Its memory uses AgentCore's managed memory service with a STM-to-LTM extraction pipeline.

**How it works:**
- Every conversation turn writes to Short-Term Memory (STM) via `create_event`
- AgentCore asynchronously extracts STM events into four Long-Term Memory strategies
- At session start, `_load_ltm_context()` queries all four strategies with semantic matching
- Results are scored, deduplicated, budget-capped (6,000 chars), and injected into context
- Agent can also explicitly save/recall memories via tools

**Key design choices:**
- *Backend-driven extraction*: AgentCore decides what's significant and categorizes it automatically
- *Agent-assisted curation*: Prompt instructions encourage the agent to save important info proactively
- *Multi-tenant by default*: Each user gets their own namespace (`/strategies/{id}/actors/{actorId}/`)
- *Score-based retrieval*: Relevance scores drive what makes it into context, not recency alone

**Strengths:**
- Managed infrastructure; no file system to maintain
- Four specialized strategies capture different memory types naturally
- Multi-tenant isolation built into the namespace model
- Semantic search matches the current conversation, not just keyword overlap

**Weaknesses:**
- Extraction latency (~60s before LTM is available)
- No team-level memory sharing (yet)
- Less transparent than file-based systems; harder to debug
- Capacity management depends on backend strategy quality

---

## Comparison Matrix

| Dimension | Hermes | OpenClaw | Plato |
|-----------|--------|----------|-------|
| **Who curates** | Agent only | Agent + periodic maintenance | Backend extraction + agent assist |
| **Storage** | Single file | Git workspace (multiple files) | AgentCore Memory API |
| **Capacity management** | Hard cap (2,200 chars) | Periodic distillation | Score-based pruning (6,000 chars) |
| **Retrieval** | Load entire file | Load relevant files | Semantic search across 4 strategies |
| **Multi-user** | No | No (single workspace) | Yes (actor namespace isolation) |
| **Search** | None (full load) | File-level | Semantic per-strategy |
| **Nudge/reminder** | Yes (periodic prompt) | Yes (heartbeat maintenance) | Yes (prompt curation instructions) |
| **Memory types** | Unstructured | File-per-concern | 4 strategies (preferences, summaries, knowledge, episodes) |
| **Transparency** | High (read the file) | High (read the files) | Medium (API queries) |
| **Latency** | Zero (file read) | Low (file read) | ~60s for STM→LTM extraction |
| **Infrastructure** | None | Git repository | AgentCore Memory service |

---

## Personal Assistant vs. Multi-Tenant Platform Agent

This is the fundamental architectural divide. A personal assistant (Hermes, OpenClaw) serves one human. A platform agent (Plato) serves many humans, potentially from different teams, with different access levels.

### What's the same

Both need:
- **Preference persistence**: "I prefer Python" should stick across sessions
- **Context continuity**: "We discussed X yesterday" should be retrievable
- **Capacity management**: Context windows are finite; not everything can be loaded
- **Quality over quantity**: Remembering 10 useful things beats remembering 1,000 noise entries

### What's different

| Concern | Personal Assistant | Platform Agent |
|---------|-------------------|----------------|
| **User isolation** | Not applicable (one user) | Critical. User A's preferences must never leak to User B. |
| **Team knowledge** | Not applicable | Needed. A team shares conventions (coding standards, deployment patterns) that all members benefit from. |
| **Write conflicts** | Rare (one writer) | Common. Two users on the same team might teach the agent conflicting things simultaneously. |
| **Scale** | Hundreds of memories | Thousands to millions of memories across all users. STM ingest volume scales linearly with user count. |
| **Quality degradation** | Slow (one user's noise) | Fast. N users × M turns/day = many low-value memories competing for limited retrieval slots. |
| **Compliance** | Optional | Required. GDPR right-to-deletion, data retention policies, audit trails. |
| **Content safety** | Low risk (trusted user) | High risk. Users might save sensitive data (credentials, PII) that shouldn't propagate to team-level memory. |
| **Memory "personality"** | One voice, one style | Must adapt to each user's style while maintaining team consistency. |

### The three-scope model

For a multi-tenant agent, memory naturally falls into three scopes:

```
┌─────────────────────────────────────┐
│  Global (all users)                 │
│  • Product documentation            │
│  • System-wide policies             │
│  • Common tool configurations       │
├─────────────────────────────────────┤
│  Team (shared within a team)        │
│  • Team coding standards            │
│  • Deployment patterns              │
│  • Shared project context           │
│  • "We always use staging before prod" │
├─────────────────────────────────────┤
│  Personal (per user)                │
│  • "I prefer verbose logging"       │
│  • "Call me Alex"                   │
│  • Past session summaries           │
│  • Individual work history          │
└─────────────────────────────────────┘
```

Write permissions flow downward (global is read-only for users, team is write-by-members, personal is write-by-owner). Content safety filters should prevent PII from flowing upward (personal → team → global).

---

## Plato's Memory Architecture in Detail

### Write Path

```
User message + Agent response
         │
         ▼
  _ingest_to_stm(actor_id, session_id, user_msg, assistant_msg)
         │
         ▼  fire-and-forget (non-blocking)
  AgentCore STM: create_event()
         │
         ▼  async extraction (~60s)
  ┌──────┴──────────────────────────────┐
  │  4 LTM Strategies (AgentCore)       │
  │  ├─ userPreferences                 │
  │  ├─ conversationSummary             │
  │  ├─ semanticKnowledge               │
  │  └─ episodicMemory                  │
  └─────────────────────────────────────┘
```

Additionally, `FileSessionManager` (Strands SDK) persists the full conversation to `/mnt/workspace/.sessions/{session_id}.json` for same-session replay. This is complementary—FileSessionManager handles conversation continuity, STM feeds cross-session memory.

### Read Path

```
New session starts
         │
         ▼
  _load_ltm_context(actor_id, current_message)
         │
         ├─ Query userPreferences      → score + 0.1 boost
         ├─ Query conversationSummary   → score as-is
         ├─ Query semanticKnowledge     → score as-is
         └─ Query episodicMemory        → score as-is
         │
         ▼
  Global ranking by score (all results combined)
         │
         ▼
  Deduplication (normalized text, keep highest score)
         │
         ▼
  Budget assembly (MAX_LTM_CHARS = 6000)
  Add records by score until budget exhausted
         │
         ▼
  Format as labeled sections:
  [User Preferences] → [Previous Conversations]
  → [Relevant Knowledge] → [Past Interactions]
         │
         ▼
  Inject into first user message as <long-term-memory> block
```

### Agent-Initiated Memory

The workspace `AGENTS.md` includes curation instructions that prompt the agent to actively save memories when it detects:

1. **Corrections**: User corrects the agent → save to avoid repeating
2. **Preferences**: Explicit or implicit preferences → save as preference
3. **Decisions**: "Let's use X instead of Y" → save as decision
4. **Environment**: Technical setup details → save as fact
5. **Action items**: Commitments → save as todo

This hybrid approach (backend extraction + agent initiative) captures both the implicit patterns that backend strategies find and the explicit importance signals that only the agent-in-conversation can recognize.

### Namespace and Isolation

All memory operations are scoped by `actor_id`, derived from JWT claims (Cognito `sub`):

```
/strategies/userPreferences/actors/{actor_id}/
/strategies/conversationSummary/actors/{actor_id}/
/strategies/semanticKnowledge/actors/{actor_id}/
/strategies/episodicMemory/actors/{actor_id}/
```

A `MemoryAccessGuard` validates namespace access before any retrieval to prevent cross-user data exposure. The guard blocks:
- Root namespace `/` (would search all users)
- Empty namespace (no scoping)
- Namespaces that don't contain the requesting `actor_id`

### Score-Based Pruning

Not all memories are equal. The retrieval pipeline uses relevance scores from AgentCore's semantic search to prioritize what enters the context window:

1. **Preferences get a boost**: +0.1 to relevance score, because user preferences are almost always relevant regardless of the current query
2. **Deduplication**: When the same fact appears in multiple strategies (e.g., both as a preference and as semantic knowledge), only the highest-scored copy survives
3. **Budget cap**: 6,000 characters (~1,500 tokens). Records are added in score order until the budget is exhausted. A single record that exceeds the remaining budget is still included if it's the first record (prevents empty context on large memories)
4. **Section ordering**: Even within the budget, memories are grouped by type for readability

---

## Lessons from Building This

### 1. "Designed but not connected" is worse than "not designed"

We had STM ingestion, LTM strategies, memory tools, extraction hooks, and consolidation hooks. On paper, a complete memory system. In practice, the STM→LTM pipeline was accidentally severed during a refactor (the `create_event` call was removed when `FileSessionManager` was added, conflating conversation replay with memory extraction). The system appeared to work (conversations were maintained within sessions) but cross-session memory was silently broken.

**Takeaway**: End-to-end tests that verify the complete chain (write in session A → wait → read in session B) are not optional. Unit tests on individual components cannot catch integration failures.

### 2. Backend extraction is necessary but not sufficient

AgentCore's four strategies do a good job of automatically categorizing and extracting patterns from conversations. But they miss explicit importance signals. When a user says "Remember: always use staging before prod," that's a high-priority preference that should be saved immediately, not left to async extraction that might or might not capture it.

**Takeaway**: The hybrid model (backend extraction + agent-initiated saves + prompt-based curation nudges) captures more signal than any single approach alone.

### 3. Capacity management is the hardest problem

With multiple users generating STM events continuously, LTM grows without bound. Semantic search helps (only relevant memories are retrieved), but as the corpus grows, the noise floor rises. Marginally relevant memories crowd out genuinely important ones.

Hermes solved this with a brutal 2,200-character cap and forced curation. OpenClaw uses periodic maintenance runs. Plato uses score-based pruning with a 6,000-character cap. All three approaches are different answers to the same question: how do you keep memory useful as it grows?

**Takeaway**: No memory system should grow without bound. Whether the cap is enforced by file size, maintenance cron, or retrieval budget, something must prevent unbounded accumulation.

### 4. Multi-tenant isolation must be verified, not assumed

Namespace-based isolation looks correct in architecture diagrams. But the actual isolation depends on every code path correctly passing the `actor_id` through the entire chain: JWT extraction → entrypoint → memory client → namespace parameter. A single code path that defaults to "default" instead of the real actor ID breaks isolation silently.

**Takeaway**: E2E tests with multiple actors running concurrently are the only way to verify isolation. Code review alone is insufficient.

---

## Roadmap

### P0 — Done (current release)
- [x] STM→LTM pipeline restored
- [x] Multi-strategy LTM retrieval (4 strategies)
- [x] Score-based pruning with token cap
- [x] Active memory curation prompt
- [x] E2E test suite (5 scenarios)

### P1 — Next
- [ ] Team-level memory namespace (`/strategies/{id}/teams/{teamId}/`)
- [ ] MemoryHook namespace cleanup (remove dead code, fix warning noise)
- [ ] LTM query parallelization (ThreadPoolExecutor for 4 strategies)
- [ ] Memory admin API (list/delete memories per actor)

### P2 — Future
- [ ] Content safety classification (prevent PII upward propagation)
- [ ] GDPR compliance (right-to-deletion API)
- [ ] Memory quality metrics dashboard
- [ ] Consolidation strategy (merge redundant memories)
- [ ] Memory versioning (track how memories evolve over time)

---

*Last updated: 2026-04-14*
