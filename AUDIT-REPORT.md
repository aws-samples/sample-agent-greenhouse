# Code Audit Report — sample-agent-greenhouse

**Date**: 2026-04-14
**Auditor**: 大鳌哥哥 (OpenClaw)
**Scope**: Full codebase audit — dead code, ARCHITECTURE.md accuracy, MD loading, skill system, code quality

---

## 🔴 CRITICAL — Must Fix

### C1. ARCHITECTURE.md (root) claims deprecated shim directories exist — they don't

**File**: `ARCHITECTURE.md` (root, 237 lines)

The root ARCHITECTURE.md states:

```
# Deprecated shims (kept for external consumers, emit DeprecationWarning):
├── aidlc/               → platform_agent.plato.aidlc
├── control_plane/       → platform_agent.plato.control_plane
├── evaluator/           → platform_agent.plato.evaluator
├── skills/              → platform_agent.plato.skills
├── guardrails/          → platform_agent.foundation.guardrails
├── handoff/             → platform_agent.foundation.handoff
├── protocols/           → platform_agent.foundation.protocols
├── strands_foundation/  → platform_agent.foundation
```

**NONE of these directories exist.** They were never created or were deleted. The only actual deprecated shim is `orchestrator.py` (a thin redirect) and `_legacy_foundation.py`. The doc misleads anyone reading it.

**Fix**: Remove the entire "Deprecated shims" section from root ARCHITECTURE.md, or reduce it to mention only `orchestrator.py` and `_legacy_foundation.py` which actually exist.

### C2. Two ARCHITECTURE.md files with different content

- `ARCHITECTURE.md` (root): 237 lines, simplified overview
- `docs/ARCHITECTURE.md`: 1224 lines, detailed design document

They describe the same system but with different levels of detail. The root file is a summary (and has the shim lie above). The docs version is more thorough and more accurate.

**Fix**: Root ARCHITECTURE.md should clearly link to docs/ARCHITECTURE.md as the source of truth. Remove stale claims.

### C3. Dual GitHub tool implementations — confusing and redundant

- `foundation/tools/github.py` (868 lines, urllib-based) — imported by 13 files (PR review, issue creator, spec compliance, etc.)
- `foundation/tools/github_tool.py` (561 lines, requests-based) — imported ONLY by `entrypoint.py`

Both implement GitHub operations (get_repo, list_prs, create_issue, etc.) with slightly different APIs. `github.py` uses urllib; `github_tool.py` uses `requests`. The entrypoint imports ALL tools from `github_tool.py`, but all domain skills import from `github.py`.

**Impact**: If someone uses the deployed agent via entrypoint, they get `github_tool.py` functions. If they use the orchestrator/skills directly, they get `github.py` functions. Different implementations, potential behavior differences.

**Fix**: Consolidate into one. Since `github.py` has more importers and is used by the skill layer, it should be the canonical one. Update `entrypoint.py` to import from `github.py`.

### C4. Workspace SOUL.md loaded but IDENTITY.md path isn't propagated to workspace_context

The `WorkspaceContextLoader` only scans for: `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md`.

**It does NOT load SOUL.md or IDENTITY.md.** Those are loaded separately by `SoulSystemHook` (via `soul.py`), which scans `workspace/` for `IDENTITY.md`, `SOUL.md`, and `AGENTS.md`.

So effectively:
- `AGENTS.md` is loaded TWICE (by both `WorkspaceContextLoader` AND `SoulSystemHook`)
- `SOUL.md` and `IDENTITY.md` are loaded only by `SoulSystemHook` ✅
- Potential double-injection of AGENTS.md content into the system prompt

**Fix**: Either remove AGENTS.md from `WorkspaceContextLoader.KNOWN_FILES` (let `SoulSystemHook` handle it), or remove it from `SoulSystemHook`. Don't load it twice.

---

## 🟡 CLEANUP — Dead Code to Remove

### D1. `_legacy_foundation.py` (354 lines) — legacy cruft

This file implements a pre-Strands `FoundationAgent` using `claude_agent_sdk` (which doesn't exist in dependencies). It's imported by:
- `foundation/__init__.py` — try-import with fallback to None
- `cli.py` lines 91 and 452 — two CLI commands that fall back to legacy agent

`claude_agent_sdk` is not in `requirements.txt` or `pyproject.toml`. The import will always fail in production. The CLI paths that use it are dead ends.

**Fix**: Delete `_legacy_foundation.py`. Remove `LegacyFoundationAgent` from `foundation/__init__.py`. Update `cli.py` to remove legacy fallback paths.

### D2. `bedrock_runtime.py` (only imported by legacy code)

Only imported by:
- `_legacy_foundation.py` line 323
- `plato/orchestrator.py` line 211 (in a method that only runs in legacy bedrock mode)

Since `_legacy_foundation.py` should be deleted, and `orchestrator.py`'s legacy path is unreachable in production (Strands is always available), this file is dead.

**Fix**: Delete `bedrock_runtime.py`. Remove the legacy fallback in `orchestrator.py`.

### D3. `orchestrator.py` (top-level shim) — zero importers

`src/platform_agent/orchestrator.py` is a deprecated shim that redirects to `plato.orchestrator`. **Nobody imports it.** Zero references outside of itself.

**Fix**: Delete it.

### D4. CompactionHook — deprecated, still imported but never enabled

`CompactionHook` is:
- Marked DEPRECATED in its own docstring
- Imported by `agent.py` (line 39) and referenced in hook loading (line 424-427)
- BUT its loading path has a comment: "CompactionHook is deprecated"
- NOT listed in `plato_harness.yaml` or `create_plato_harness()` hooks
- Has a no-op `on_event` that does nothing

**Fix**: Delete `compaction_hook.py`. Remove imports from `agent.py` and `hooks/__init__.py`.

### D5. MemoryExtractionHook — disabled, should be marked for removal

Listed in harness as `optional` with `enabled_by="memory_config.extraction_enabled"`, which is set to `False` in `create_plato_harness()`. The hook writes to local workspace files (not AgentCore), which was identified as wrong on 4/12.

The hook still exists and is importable but functionally dead for the Plato domain.

**Fix**: Delete `memory_extraction_hook.py` or at minimum add a clear DEPRECATED header. Its approach (writing to local files) is fundamentally wrong for containerized deployment.

### D6. ConsolidationHook — disabled, same pattern

Also `optional` with `enabled_by="memory_config.consolidation_enabled"` = `False`.

**Fix**: Same as D5 — mark deprecated or delete.

### D7. `foundation/memory.py` — `SessionMemory` has zero live callers

`SessionMemory` class in `foundation/memory.py` is only imported by:
- `compaction_hook.py` (deprecated)
- `memory_hook.py` — imports it but `get_session_history()` was removed (confirmed in 4/12 audit)

`WorkspaceMemory` in the same file is imported by `consolidation_hook.py` (disabled), `memory_extraction_hook.py` (disabled), `memory_hook.py`, and `agent.py`.

**Fix**: When deprecated hooks are deleted, check if `SessionMemory` and `WorkspaceMemory` still have callers.

### D8. Duplicate Dockerfiles

- `Dockerfile` — uses `public.ecr.aws/docker/library/python:3.11-slim`, has maintainer labels
- `Dockerfile.strands` — uses `python:3.11-slim`, different structure

Both target the same application. Unclear which is canonical.

**Fix**: Keep one (likely `Dockerfile` since it uses ECR-based images appropriate for AWS deployment). Delete or rename the other with a clear purpose comment.

### D9. `demo_user_journey.py` — imports control plane classes directly

This demo script imports `AgentRegistry`, `PlatformPolicyEngine`, `TaskManager`, etc. It's a standalone demo, not dead code per se, but it should be in `examples/` not root. Also, it imports `from platform_agent.foundation.guardrails import Policy` which is a real import path.

**Fix**: Move to `examples/` directory.

### D10. `skills/plato-platform-guide.md` — orphan file

A standalone Markdown file in `skills/` (not inside a skill directory, no SKILL.md frontmatter). Not discoverable by either skill system.

**Fix**: Move into a proper skill directory structure or delete.

---

## 🟠 IMPROVEMENT — Code Quality & Consistency

### I1. Dual Skill Systems — confusing but functional

The codebase has two skill systems running simultaneously:

1. **SkillPack class-based** (Python): `plato/skills/*/` — 16 skills with `register_skill()` calls, `SkillPack` subclasses, `configure()` methods, loaded by `orchestrator.py` and `cli.py`
2. **AgentSkills/SKILL.md-based** (Strands plugin): Same directories + `workspace/skills/` — discovers `SKILL.md` files for system prompt injection

They are NOT duplicated — they serve different purposes:
- SkillPack: provides Python tool functions + system prompt extensions (loaded imperatively)
- AgentSkills/SKILL.md: provides skill discovery for system prompt listing + lazy content loading

The `agent.py` code (line 223-241) discovers domain SKILL.md files from `plato/skills/*/` via the AgentSkills plugin. This is correct — Phase 2 added SKILL.md files alongside the SkillPack `__init__.py` files.

**However**: `workspace/skills/` has 11 SKILL.md-only skills (no Python), and 4 of them overlap with plato skills:
- `workspace/skills/code-review/` ↔ `plato/skills/code_review/`
- `workspace/skills/debug/` ↔ `plato/skills/debug/`
- `workspace/skills/deployment-config/` ↔ `plato/skills/deployment_config/`
- `workspace/skills/design-advisor/` ↔ `plato/skills/design_advisor/`

The workspace versions are simpler (user-facing guidance). The plato versions are detailed (implementation + tools). Both get discovered by AgentSkills, meaning the system prompt lists them twice under different names.

**Fix**: Either deduplicate the 4 overlapping workspace skills, or make workspace skills have clearly different scope.

### I2. SkillRegistry.discover() and get_prompt_summary() are deprecated

Both methods emit `DeprecationWarning` but are still called in `agent.py`:
- Line 215-217: `self.skill_registry = SkillRegistry(...)` + `discover()`
- Line 516: `skills_summary = self.skill_registry.get_prompt_summary()`

The AgentSkills plugin (line 222-241) replaces this when available. But the SkillRegistry is always initialized as fallback.

**Fix**: Check if `_AgentSkills` is available and skip SkillRegistry entirely when it is. Current code initializes both always.

### I3. `scaffold/templates.py` line 333 redefines `register_skill`

This file defines its own `register_skill(name, cls)` function that shadows the import from `plato.skills`. Not harmful (it's a standalone function) but confusing.

### I4. `health.py` — check if it's used

**File**: `src/platform_agent/health.py`

Needs verification that `entrypoint.py` or something actually registers the health endpoint.

### I5. `slack/cognito_exchange.py` — Cognito token exchange utility

Should verify this is still needed or if it's from an earlier architecture.

### I6. `evaluation/.gitkeep` and `examples/sample-apps/.gitkeep` — empty directories

Standard practice but `examples/sample-apps/` has actual content (good-weather-agent, needs-refactor-agent). The `.gitkeep` is unnecessary.

---

## ✅ VERIFIED OK

### V1. SOUL.md, IDENTITY.md, AGENTS.md loading ✅

`SoulSystemHook` → `soul.py` → reads 3 files from workspace dir → injects into system prompt at agent build time. Chain is:
1. `SoulSystemHook.on_agent_invocation()` reloads soul files
2. `SoulSystem.load()` reads `IDENTITY.md`, `SOUL.md`, `AGENTS.md` from workspace
3. `FoundationAgent._build_system_prompt()` calls `self.soul_system.assemble_prompt()` to inject

Loading works correctly ✅ (with the caveat in C4 about AGENTS.md double-loading).

### V2. Memory flow — STM → LTM pipeline ✅

Fixed in 4/12. `_ingest_to_stm()` writes to AgentCore STM after each turn. `_load_ltm_context()` only runs on first turn (optimized). Token cap at 6000 chars. All working as designed.

### V3. Hook loading from DomainHarness ✅

`create_plato_harness()` defines hook configs. `FoundationAgent._load_hooks()` iterates and imports by name. Foundation hooks always load. Domain hooks load when listed. Optional hooks check `enabled_by` condition. Pattern works correctly.

### V4. Previously identified dead code (4/12) — context_manager.py, parallel_evaluator.py, storage_router.py ✅ DELETED

Confirmed deleted. Their test files also deleted.

### V5. AgentSkills plugin integration ✅

When `strands.AgentSkills` is importable, `agent.py` creates the plugin with skill sources from both workspace and plato skill directories. SKILL.md files in plato skill dirs were added in Phase 2. Discovery works.

### V6. FileSessionManager for conversation persistence ✅

Properly configured in `entrypoint.py` with fallback chain: `/mnt/workspace/.sessions/` → S3 → `/tmp`.

### V7. Plato harness YAML serialization ✅

`DomainHarness.to_dict()` and `DomainHarness.from_yaml()` work for the `plato_harness.yaml` config-as-code pattern.

---

## Summary

| Severity | Count | Items |
|----------|-------|-------|
| 🔴 CRITICAL | 4 | C1-C4 |
| 🟡 CLEANUP | 10 | D1-D10 |
| 🟠 IMPROVEMENT | 6 | I1-I6 |
| ✅ VERIFIED OK | 7 | V1-V7 |

**Estimated dead code to remove**: ~1800+ lines (legacy_foundation 354 + bedrock_runtime ~200 + orchestrator shim ~20 + compaction_hook ~170 + consolidation ~similar + extraction ~similar + redundant github_tool 561)

**Top priority**: Fix C1 (ARCHITECTURE.md lying) and C3 (dual GitHub tools) as these actively confuse developers. D1-D3 are safe deletes with no behavioral impact.
