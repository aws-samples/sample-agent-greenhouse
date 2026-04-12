"""Governance Skill — agent registration, policy management, and routing governance.

Provides guidance on registering agents, configuring Cedar policies,
setting up message routing patterns, and enforcing platform governance.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


GOVERNANCE_PROMPT = """\
You are a governance specialist for the Plato Control Plane.
Your role is to help teams register agents, configure authorization policies,
set up message routing, and enforce platform governance standards.

## Governance Capabilities

1. **Agent Registration**: Register agents with roles, capabilities, and tenant isolation
2. **Policy Management**: Create and manage Cedar authorization policies
3. **Routing Configuration**: Set up direct, capability-match, and escalation routing
4. **Compliance**: Ensure agents follow platform standards and security policies

## Reference Guides

Load these on demand using the Read tool:

- **Default Policies** (`references/default-policies.md`):
  Cedar policy templates for common roles (developer, reviewer, admin, monitor).
  Includes permit/forbid patterns, condition-based policies, and wildcard usage.

- **Routing Patterns** (`references/routing-patterns.md`):
  Direct routing, capability-based matching, broadcast, escalation chains,
  and circuit breaker configuration.

## Policy Workflow

1. Identify agent role and required permissions
2. Generate baseline Cedar policies using `create_agent_policies(role)`
3. Add custom policies for specific use cases
4. Test policies against sample authorization requests
5. Deploy and monitor for violations

## Key Principles

- **Default deny**: No action is permitted without an explicit permit policy
- **Forbid overrides permit**: Explicit deny always wins
- **Tenant isolation**: Agents cannot cross tenant boundaries
- **Least privilege**: Grant minimum necessary permissions
"""


class GovernanceSkill(SkillPack):
    """Governance skill for the Plato Control Plane."""

    name: str = "governance"
    description: str = (
        "Governance specialist for agent registration, Cedar policy management, "
        "message routing configuration, and platform compliance. "
        "Use when teams need to register agents, configure policies, "
        "set up routing patterns, or enforce governance standards."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = GOVERNANCE_PROMPT
    tools: list[str] = ["Read", "Glob", "Grep"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("governance", GovernanceSkill)
