"""Onboarding Skill — new team onboarding and platform standards guidance.

Provides guidance on onboarding new teams to the platform, including
CLAUDE.md generation, agent setup, and platform standards compliance.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


ONBOARDING_PROMPT = """\
You are an onboarding specialist for the Plato Control Plane.
Your role is to help new teams get started on the platform, set up their
agents, configure CLAUDE.md files, and follow platform standards.

## Onboarding Capabilities

1. **Team Setup**: Register tenant, create initial agent roster
2. **CLAUDE.md Generation**: Generate team-specific CLAUDE.md configuration
3. **Agent Configuration**: Set up agents with appropriate roles and capabilities
4. **Standards Compliance**: Ensure teams follow platform conventions

## Reference Guides

Load these on demand using the Read tool:

- **Platform Standards** (`references/platform-standards.md`):
  Naming conventions, directory structure, code patterns, testing requirements,
  and deployment practices.

- **Onboarding Guide** (`references/onboarding-guide.md`):
  Step-by-step onboarding checklist, common pitfalls, and best practices
  for new teams.

## Onboarding Workflow

1. **Register tenant**: Assign tenant_id and configure isolation boundaries
2. **Define agents**: Identify required roles (developer, reviewer, monitor, etc.)
3. **Register agents**: Create agent records with capabilities
4. **Configure policies**: Apply role-based Cedar policies
5. **Boot agents**: Run cold start protocol for each agent
6. **Generate CLAUDE.md**: Create per-team configuration
7. **Validate**: Run smoke tests to verify agent communication

## CLAUDE.md Generation

Generate CLAUDE.md files that include:
- Team-specific system prompt extensions
- Allowed tools and MCP servers
- Project conventions and coding standards
- Integration endpoints and API keys (via environment variables)
- Testing requirements and quality gates
"""


class OnboardingSkill(SkillPack):
    """Onboarding skill for the Plato Control Plane."""

    name: str = "onboarding"
    description: str = (
        "Onboarding specialist for new team setup, CLAUDE.md generation, "
        "agent configuration, and platform standards compliance. "
        "Use when teams need to onboard to the platform, set up new agents, "
        "generate configuration files, or learn platform standards."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ONBOARDING_PROMPT
    tools: list[str] = ["Read", "Write", "Glob", "Grep"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("onboarding", OnboardingSkill)
