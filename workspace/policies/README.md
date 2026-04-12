# Enterprise Policy Framework

Plato maintains enterprise-level policies that govern how AI agents are built,
reviewed, and deployed. These policies are compiled into project-level artifacts
(CLAUDE.md, PR templates) so that developer tools automatically enforce standards.

## Policy Tiers

Agents are classified by risk level. Tier determines which policies apply.

| Tier | Risk Level | Data Sensitivity | Examples | Policies Applied |
|------|-----------|-----------------|----------|-----------------|
| 1 | High | PII, financial, health | Payment agents, HR bots, medical assistants | All policies (security + architecture + compliance + testing) |
| 2 | Medium | Internal business data | Customer support, internal tools, analytics agents | Security + Architecture + Testing |
| 3 | Low | Public/non-sensitive | Demos, prototypes, documentation helpers | Security basics only |

## Policy Files

| Policy | Applies To | Purpose |
|--------|-----------|---------|
| `security-standards.md` | All tiers | IAM, secrets, input validation, injection defense |
| `agent-architecture.md` | Tier 1-2 | Strands patterns, memory isolation, error handling |
| `compliance-requirements.md` | Tier 1 only | Audit logging, PII handling, data retention, approvals |
| `testing-standards.md` | Tier 1-2 | Coverage thresholds, required test types |

## How Policies Flow

```
Enterprise Policy Templates (this directory)
    │
    ├── Phase 1: Plato asks "What data will this agent handle?"
    │   → Determines tier → Selects applicable policies
    │
    ├── Generates CLAUDE.md with embedded policy requirements
    │   → Developer's CC reads CLAUDE.md → Code follows standards
    │
    ├── Generates .github/pull_request_template.md
    │   → Developer self-checks compliance before PR
    │
    └── Phase 3: Plato reviews PR against same policies
        → Ensures CC-written code actually meets standards
```

## Policy Versioning

Each policy file has a version header. CLAUDE.md includes a version tag:

```
<!-- plato-policy: security-v1, architecture-v1, compliance-v1, testing-v1 -->
```

Plato can detect policy drift by scanning managed repos and comparing versions.
Outdated projects get an automated PR to update CLAUDE.md.

## Mock Scenario

See `examples/acme-corp/` for a complete enterprise mock scenario
(Acme Corp — fintech company building a customer service agent).
