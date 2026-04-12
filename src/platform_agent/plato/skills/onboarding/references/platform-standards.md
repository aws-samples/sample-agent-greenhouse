# Platform Standards

## Table of Contents
- [Naming Conventions](#naming-conventions)
- [Directory Structure](#directory-structure)
- [Code Patterns](#code-patterns)
- [Testing Requirements](#testing-requirements)
- [Deployment Practices](#deployment-practices)

## Naming Conventions

- **Agent IDs**: lowercase, hyphen-separated (e.g., `design-advisor`, `code-reviewer`)
- **Tenant IDs**: lowercase, hyphen-separated (e.g., `team-alpha`, `org-acme`)
- **Task IDs**: UUID v4 (auto-generated)
- **Policy IDs**: `{role}:{permission}` format (e.g., `developer:read-files`)
- **Skill names**: lowercase, underscore-separated (e.g., `fleet_ops`, `code_review`)

## Directory Structure

```
src/platform_agent/
  control_plane/        # Core control plane modules
    registry.py         # Agent registry
    policy_engine.py    # Platform policy engine
    task_manager.py     # Task system
    message_router.py   # Message routing
    lifecycle.py        # Lifecycle management
    audit.py           # Audit store
  skills/              # Skill packs
    base.py            # SkillPack base class
    {skill_name}/      # Each skill in its own directory
      __init__.py      # Skill implementation
      references/      # Reference documents
  guardrails/          # Cedar policy engine
tests/                 # Test files
```

## Code Patterns

- Use `dataclasses` with `field(default_factory=...)` for mutable defaults
- Type hints required on all function signatures
- Use `from __future__ import annotations` for forward references
- Use `X | None` instead of `Optional[X]`
- UUID generation: `str(uuid.uuid4())`
- Timestamps: `datetime.now(timezone.utc)`

## Testing Requirements

- Test classes named `TestXxx` with methods `test_xxx`
- Aim for comprehensive coverage of all public methods
- Test edge cases: empty inputs, invalid states, boundary conditions
- Integration tests for cross-module interactions

## Deployment Practices

- All agents must pass cold start protocol before serving requests
- Heartbeat monitoring must be configured for all production agents
- Graceful shutdown required before agent deregistration
- Audit logging must be enabled for all production deployments
