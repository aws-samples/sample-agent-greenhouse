# Onboarding Guide

## Table of Contents
- [Prerequisites](#prerequisites)
- [Step-by-Step Onboarding](#step-by-step-onboarding)
- [Common Pitfalls](#common-pitfalls)
- [Best Practices](#best-practices)

## Prerequisites

Before onboarding a new team:
1. Tenant ID allocated and approved
2. Team lead identified as admin contact
3. Agent roles and capabilities defined
4. Cedar policies reviewed by security team

## Step-by-Step Onboarding

### Step 1: Register Tenant

```python
tenant_id = "team-alpha"
```

### Step 2: Register Agents

```python
from platform_agent.control_plane.registry import AgentRegistry, Capability

registry = AgentRegistry()

# Register a developer agent
dev_agent = registry.register(
    tenant_id=tenant_id,
    role="developer",
    capabilities=[
        Capability(name="code_generation", confidence=0.9),
        Capability(name="debugging", confidence=0.8),
    ],
    tools=["Read", "Write", "Bash"],
)
```

### Step 3: Configure Policies

```python
from platform_agent.control_plane.policy_engine import (
    PlatformPolicyEngine,
    create_agent_policies,
)

engine = PlatformPolicyEngine()
policies = create_agent_policies("developer")
for policy in policies:
    engine.store.add_policy(policy)
```

### Step 4: Boot Agents

```python
from platform_agent.control_plane.lifecycle import ColdStartProtocol

cold_start = ColdStartProtocol(registry, engine)
success = cold_start.boot(tenant_id, dev_agent.agent_id)
assert success, "Agent failed to reach READY state"
```

### Step 5: Generate CLAUDE.md

Create a CLAUDE.md file tailored to the team's needs:
- Include team-specific conventions
- List approved tools and integrations
- Define quality gates and review requirements

### Step 6: Validate

Run smoke tests:
- Agent can send and receive messages
- Policies are enforced correctly
- Heartbeat is updating
- Audit logs are recording

## Common Pitfalls

1. **Forgetting cold start**: Agents in BOOT state cannot perform actions
2. **Missing tenant isolation**: Always verify tenant_id on all operations
3. **Overly permissive policies**: Start restrictive, add permissions as needed
4. **No heartbeat monitoring**: Set up HeartbeatManager immediately

## Best Practices

1. Use role-based policies as a starting point
2. Enable audit logging from day one
3. Set up heartbeat monitoring with appropriate timeouts
4. Document agent capabilities accurately with realistic confidence scores
5. Plan for graceful shutdown in all deployment scenarios
