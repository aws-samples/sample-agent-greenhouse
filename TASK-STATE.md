# TASK-STATE.md — Skill Architecture Refactor

## Project
- **Name**: skill-architecture-refactor
- **Branch**: `feat/skill-architecture-refactor`
- **Repo**: `/Users/peiyaoli/Documents/projects/sample-agent-greenhouse`
- **Status**: in-progress
- **Started**: 2026-04-14T18:18:00+10:00
- **Notify**: `#C0AM065RFS6` (thread `1776146887.898799`)

## Tasks

### Phase 1: DomainHarness adds `skill_directories`
- **id**: phase1
- **status**: done
- **completed**: 2026-04-14T18:25:00+10:00
- **assigned_to**: gege
- **timeout**: 60
- **max_retries**: 1
- **subtasks**:
  1. Add `skill_directories: list[str]` to `DomainHarness` in `foundation/harness.py`
  2. Update `create_plato_harness()` in `plato/harness.py` to declare `skill_directories=[plato/skills/]`
  3. Refactor `FoundationAgent.__init__()` AgentSkills init: use `elif` pattern (harness.skill_directories → else fallback workspace/skills/)
  4. Update `plato_harness.yaml` to include `skill_directories` field
  5. Run tests to verify nothing breaks

### Phase 2: Merge workspace/skills/ into plato/skills/
- **id**: phase2
- **status**: done
- **completed**: 2026-04-14T18:28:00+10:00
- **assigned_to**: gege
- **depends_on**: [phase1]
- **timeout**: 60
- **max_retries**: 1
- **subtasks**:
  1. Move 6 knowledge-only skills from workspace/skills/ to plato/skills/ (architecture_knowledge, cost_optimization, migration_guide, security_review, testing_strategy, policy_compiler)
  2. Delete 4 overlapping workspace skills (code-review, debug, design-advisor, deployment-config)
  3. Delete code-helper (too thin, 3 lines)
  4. Update Dockerfile and Dockerfile.strands: remove `COPY workspace/skills/`
  5. Verify AgentSkills plugin still discovers all skills from plato/skills/

### Phase 3: Clean SkillPack hardcoded prompts
- **id**: phase3
- **status**: done
- **completed**: 2026-04-14T18:32:00+10:00
- **assigned_to**: gege
- **depends_on**: [phase2]
- **timeout**: 90
- **max_retries**: 1
- **subtasks**:
  1. For each of 16 domain skill __init__.py: remove `system_prompt_extension` / hardcoded prompt constants
  2. Ensure each domain skill has a complete SKILL.md (SKILL.md is sole prompt source)
  3. Keep `name`, `tools`, `configure()` in Python classes
  4. Update any code that references `skill.system_prompt_extension`

### Phase 5: Dead code cleanup
- **id**: phase5
- **status**: done
- **completed**: 2026-04-14T18:42:00+10:00
- **assigned_to**: gege
- **depends_on**: [phase3]
- **timeout**: 120
- **max_retries**: 1
- **subtasks**:
  1. Fix GuardrailsHook: change from log-only to actually blocking
  2. Delete deprecated `SkillRegistry` + related backward-compat tests
  3. Delete `_legacy_foundation.py` — update CLI imports to use FoundationAgent
  4. Merge `github.py` + `github_tool.py` into single module
  5. Delete `AgentCoreLTMStore` stub (`ltm_store.py`)
  6. Sync or delete `plato_harness.yaml` (Python factory is truth)
  7. Update `bedrock_runtime.py` default model to global inference profile
  8. Fix `pyproject.toml` core deps (remove claude-agent-sdk, add strands-agents)
  9. Fix CompactionHook threshold (50 → reasonable value)
  10. Run full test suite

### Review Gate: Bro reviews all phases
- **id**: review
- **status**: in-progress
- **started**: 2026-04-14T18:43:00+10:00
- **assigned_to**: didi
- **depends_on**: [phase5]
- **timeout**: 60
- **subtasks**:
  1. 弟弟 pulls branch, reviews all changes
  2. Verify AgentSkills plugin works end-to-end
  3. Verify harness.skill_directories is consumed correctly
  4. Verify no workspace/skills/ remnants
  5. Report findings

## Completion
- When all tasks done: notify thread + update daily memory
