"""Orchestrator - routes requests to specialist agents using agent-as-tool pattern.

The orchestrator is itself a FoundationAgent that uses subagents (via the Task tool)
to delegate work to specialist agents. Agent definitions are built dynamically
from the registered SkillPack system, eliminating duplication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from platform_agent.plato.skills import discover_skills, list_skills, get_skill
from platform_agent.plato.skills.base import load_skill

if TYPE_CHECKING:
    from platform_agent.plato.skills.base import SkillPack


@dataclass
class AgentDefinition:
    """Lightweight agent definition for the orchestrator.

    Replaces the former claude_agent_sdk.AgentDefinition with a simple
    dataclass that holds the same fields used by the orchestrator.
    """

    description: str = ""
    prompt: str = ""
    tools: list[str] = field(default_factory=list)


# Tools that specialists should NOT have — prevents sub-agent spawning.
_SPECIALIST_DENIED_TOOLS = {"Task"}


def skillpack_to_agent_definition(skill: SkillPack) -> AgentDefinition:
    """Convert a SkillPack instance into an AgentDefinition for the orchestrator.

    This bridges the SkillPack system with the agent-as-tool pattern used by
    the orchestrator, ensuring specialist agent definitions stay in sync with
    the skill packs rather than being hardcoded duplicates.

    Specialists are NOT allowed to spawn sub-agents (Task tool is removed)
    to prevent unbounded delegation chains.

    Args:
        skill: A configured SkillPack instance.

    Returns:
        An AgentDefinition suitable for use as a subagent.
    """
    # Filter out tools that specialists should not have
    filtered_tools = [
        t for t in skill.tools if t not in _SPECIALIST_DENIED_TOOLS
    ]
    return AgentDefinition(
        description=skill.description,
        prompt=skill.system_prompt_extension,
        tools=filtered_tools,
    )


def build_agents_from_skills(skill_names: list[str] | None = None) -> dict[str, AgentDefinition]:
    """Build a dict of AgentDefinitions from registered SkillPacks.

    Args:
        skill_names: Specific skill names to include. If None, all registered
                     skills are included.

    Returns:
        Mapping of skill name -> AgentDefinition for use in orchestrator config.
    """
    discover_skills()
    names = skill_names or list_skills()
    agents: dict[str, AgentDefinition] = {}
    for name in names:
        skill_cls = get_skill(name)
        skill = load_skill(skill_cls)
        agents[name] = skillpack_to_agent_definition(skill)
    return agents


# The "Never Delegate Understanding" principle — inspired by CC's orchestrator
# pattern. The orchestrator must understand before delegating.
_NEVER_DELEGATE_UNDERSTANDING = """\
## NEVER DELEGATE UNDERSTANDING

Before routing any request to a specialist:

1. You MUST understand the full requirements yourself.
2. Decompose into a concrete spec: what files to look at, what to produce,
   what constraints apply.
3. Pass the spec AND original request to the specialist.
4. After the specialist returns, review the result against your spec before
   returning to the user.

You are the architect, not a dispatcher. Do not blindly forward requests.
Understand first, then delegate with precise instructions."""


def build_orchestrator_prompt(agents: dict[str, AgentDefinition]) -> str:
    """Build the orchestrator system prompt dynamically from available agents.

    Includes agent descriptions, routing rules, and the NEVER DELEGATE
    UNDERSTANDING principle to ensure the orchestrator acts as an architect
    rather than a simple dispatcher.

    Args:
        agents: Mapping of agent name -> AgentDefinition.

    Returns:
        Formatted system prompt describing routing rules.
    """
    lines: list[str] = []
    for name in sorted(agents):
        desc = agents[name].description or "No description"
        lines.append(f"- **{name}**: {desc}")
    bullet_list = "\n".join(lines)
    return f"""\
You are the Platform Agent orchestrator. You route user requests to the
appropriate specialist agent.

{_NEVER_DELEGATE_UNDERSTANDING}

## Available Specialists

{bullet_list}

## Routing Guidelines

Analyze the user's request and delegate to the right specialist. You can
invoke multiple specialists if the request spans multiple concerns.
For example, a request to "review and prepare for deployment" would use
both code_review and deployment_config.

### AIDLC Routing Patterns

Use these patterns to route AIDLC-related requests:

- "I want to build an agent" / "start a project" / "begin inception" → **aidlc_inception**
- "review this PR" / "check PR #X" / "review pull request" → **pr_review**
- "check spec compliance" / "verify code against spec" / "run compliance" → **spec_compliance**
- "create issue" / "file a bug" / "report a problem" → **issue_creator**
- "generate test cases" / "create tests from spec" / "test cases for spec" → **test_case_generator**

### Multi-Step AIDLC Flows

Some requests require chaining multiple specialists:

- "review and create issues" → **pr_review** first, then **issue_creator** with review findings
- "check compliance and file issues" → **spec_compliance** first, then **issue_creator**
- "generate spec and test cases" → **aidlc_inception** (generates spec), then **test_case_generator**

### AIDLC Workflow Awareness

When an AIDLC Inception workflow is active (user is mid-Inception), route
follow-up messages to **aidlc_inception** unless the message clearly targets
a different specialist. Inception conversations are stateful — the user
expects continuity within their active workflow.

## Verification

After a specialist returns its result, review the output against your
initial spec. If the result is incomplete or incorrect, provide specific
feedback and re-delegate. Do not return partial results to the user.
"""


def _run_orchestrator_strands(
    prompt: str,
    system_prompt: str,
    tools: list[str],
) -> str:
    """Run the orchestrator via Strands Agent (preferred).

    Args:
        prompt: The user's request.
        system_prompt: The orchestrator system prompt.
        tools: List of tool names from skill definitions.

    Returns:
        The orchestrator's final response text.
    """
    from strands import Agent

    agent = Agent(system_prompt=system_prompt)
    result = agent(prompt)
    return str(result)


async def _run_orchestrator_bedrock(
    prompt: str,
    system_prompt: str,
    tools: list[str],
    cwd: str | None = None,
) -> str:
    """Run the orchestrator via Bedrock Converse API (fallback).

    Used when the Strands SDK is not available.

    Args:
        prompt: The user's request.
        system_prompt: The orchestrator system prompt.
        tools: List of tool names from skill definitions.
        cwd: Working directory for file operations.

    Returns:
        The orchestrator's final response text.
    """
    from platform_agent.bedrock_runtime import converse

    return await converse(
        prompt=prompt,
        system_prompt=system_prompt,
        tool_names=tools,
        cwd=cwd,
    )


def _collect_tools(agents: dict[str, AgentDefinition]) -> list[str]:
    """Collect deduplicated tool names from all agent definitions.

    Args:
        agents: Mapping of agent name -> AgentDefinition.

    Returns:
        Deduplicated list of tool names.
    """
    seen: set[str] = set()
    tools: list[str] = []
    for agent_def in agents.values():
        for tool in agent_def.tools:
            if tool not in seen:
                seen.add(tool)
                tools.append(tool)
    return tools


async def run_orchestrator(
    prompt: str,
    cwd: str | None = None,
    skill_names: list[str] | None = None,
) -> str:
    """Run the orchestrator agent, which delegates to specialist subagents.

    Agent definitions are built from the SkillPack registry, ensuring the
    orchestrator stays in sync with the skill system.

    Uses Strands Agent when available, falls back to Bedrock Converse API.

    Args:
        prompt: The user's request.
        cwd: Working directory for file operations.
        skill_names: Limit to specific skills. If None, uses all registered skills.

    Returns:
        The orchestrator's final response.
    """
    agents = build_agents_from_skills(skill_names)
    system_prompt = build_orchestrator_prompt(agents)
    tools = _collect_tools(agents)

    try:
        return _run_orchestrator_strands(prompt, system_prompt, tools)
    except ImportError:
        return await _run_orchestrator_bedrock(
            prompt, system_prompt, tools, cwd=cwd,
        )


def run_orchestrator_sync(
    prompt: str,
    cwd: str | None = None,
    skill_names: list[str] | None = None,
) -> str:
    """Synchronous wrapper for run_orchestrator.

    Convenience method for callers that don't have an event loop.

    Args:
        prompt: The user's request.
        cwd: Working directory for file operations.
        skill_names: Limit to specific skills. If None, uses all registered skills.

    Returns:
        The orchestrator's final response.
    """
    import asyncio

    return asyncio.run(run_orchestrator(prompt, cwd=cwd, skill_names=skill_names))
