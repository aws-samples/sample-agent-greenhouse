---
name: policy-compiler
description: Compile enterprise policies into project-level CLAUDE.md files. Use when onboarding a new project (Phase 1) or when the user asks about policy requirements, compliance, or CLAUDE.md generation.
---

# Policy Compiler

## What This Skill Does

Generates project-level artifacts from enterprise policy templates:
- **CLAUDE.md** — Developer guide with embedded policy requirements
- **.github/pull_request_template.md** — PR compliance checklist
- **Readiness checklist** — Pre-deploy verification items

## When to Use

- Phase 1 Kickoff: Developer says they want to build an agent
- Policy questions: "What security requirements apply to my agent?"
- CLAUDE.md updates: "Update my project's policies to latest version"
- Drift detection: Scanning repos for outdated policy versions

## Tier Classification

Ask the developer: **"What type of data will this agent handle?"**

| Answer | Tier | Policies |
|--------|------|----------|
| PII, financial, health data | Tier 1 | All 4 policies |
| Internal business data | Tier 2 | Security + Architecture + Testing |
| Public/non-sensitive | Tier 3 | Security basics only |

## Policy Templates

Located in `workspace/policies/`:
- `security-standards.md` (v1) — All tiers
- `agent-architecture.md` (v1) — Tier 1-2
- `compliance-requirements.md` (v1) — Tier 1 only
- `testing-standards.md` (v1) — Tier 1-2

## CLAUDE.md Structure

```markdown
<!-- plato-policy: security-v1[, architecture-v1][, compliance-v1][, testing-v1] -->
<!-- plato-tier: {1|2|3} -->
<!-- plato-generated: {date} -->

# {Project Name} — Development Guide

## Project Overview
{From kickoff conversation}

## Architecture Requirements
{From agent-architecture.md, if tier 1-2}

## Security Requirements
{From security-standards.md, always included}

## Compliance Requirements
{From compliance-requirements.md, if tier 1}

## Testing Requirements
{From testing-standards.md, if tier 1-2}

## Readiness Checklist
{Generated from applicable policies}
```

## Version Tags

Include policy versions in HTML comments at the top of CLAUDE.md.
This enables drift detection: Plato can scan repos and compare
the embedded version against the current policy version.

## Example

See `workspace/examples/acme-corp/CLAUDE.md` for a complete Tier 1 example
(fintech customer support agent with PII handling and refund approval workflow).
