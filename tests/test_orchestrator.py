"""Tests for orchestrator skill-pack integration."""

from __future__ import annotations

import sys

import pytest

from platform_agent.plato.skills.base import SkillPack, load_skill
from platform_agent.plato.skills import _registry, register_skill, discover_skills
from platform_agent.plato.orchestrator import (
    skillpack_to_agent_definition,
    build_agents_from_skills,
    build_orchestrator_prompt,
)

from claude_agent_sdk import AgentDefinition


# -- Test skill fixtures --------------------------------------------------------


class _DesignSkill(SkillPack):
    name = "design-advisor"
    description = "Architecture and design guidance"
    system_prompt_extension = "You are a design expert."
    tools = ["Read", "Glob", "Grep"]

    def configure(self) -> None:
        pass


class _DeploySkill(SkillPack):
    name = "deployment-config"
    description = "Deployment configuration generation"
    system_prompt_extension = "You handle deployment configs."
    tools = ["Read", "Write", "Edit"]

    def configure(self) -> None:
        pass


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear and restore the skill registry around each test."""
    saved = dict(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


# -- skillpack_to_agent_definition tests ----------------------------------------


def test_converts_skill_to_agent_definition() -> None:
    skill = load_skill(_DesignSkill)
    agent_def = skillpack_to_agent_definition(skill)
    assert agent_def.description == "Architecture and design guidance"
    assert agent_def.prompt == "You are a design expert."
    assert agent_def.tools == ["Read", "Glob", "Grep"]


def test_agent_def_tools_are_copied() -> None:
    """Ensure tools list is a copy, not a reference."""
    skill = load_skill(_DesignSkill)
    agent_def = skillpack_to_agent_definition(skill)
    agent_def.tools.append("Write")
    assert "Write" not in skill.tools


# -- build_agents_from_skills tests ---------------------------------------------


def test_build_agents_from_specific_skills() -> None:
    register_skill("design-advisor", _DesignSkill)
    register_skill("deployment-config", _DeploySkill)
    agents = build_agents_from_skills(skill_names=["design-advisor", "deployment-config"])
    assert "design-advisor" in agents
    assert "deployment-config" in agents
    assert len(agents) == 2


def test_build_agents_uses_all_registered() -> None:
    register_skill("design-advisor", _DesignSkill)
    register_skill("deployment-config", _DeploySkill)
    agents = build_agents_from_skills()
    assert "design-advisor" in agents
    assert "deployment-config" in agents


def test_build_agents_preserves_skill_fields(monkeypatch) -> None:
    # Prevent discover_skills from overwriting our mock
    monkeypatch.setattr("platform_agent.plato.orchestrator.discover_skills", lambda: None)
    register_skill("design-advisor", _DesignSkill)
    agents = build_agents_from_skills(skill_names=["design-advisor"])
    agent_def = agents["design-advisor"]
    assert agent_def.description == "Architecture and design guidance"
    assert agent_def.prompt == "You are a design expert."
    assert agent_def.tools == ["Read", "Glob", "Grep"]


def test_build_agents_from_discovered_skills() -> None:
    """Integration test: discover real skills and build agents from them."""
    # Remove cached skill modules so re-import triggers register_skill() calls
    to_remove = [k for k in sys.modules if k.startswith("platform_agent.plato.skills.") and k != "platform_agent.plato.skills.base"]
    for k in to_remove:
        del sys.modules[k]
    discover_skills()
    agents = build_agents_from_skills()
    assert "design-advisor" in agents
    assert "scaffold" in agents
    assert "code-review" in agents
    assert "deployment-config" in agents


# -- build_orchestrator_prompt tests --------------------------------------------


def test_prompt_includes_agent_names_and_descriptions() -> None:
    agents = {
        "design-advisor": AgentDefinition(
            description="Architecture review", prompt="...", tools=[]
        ),
        "code-review": AgentDefinition(
            description="Code quality checks", prompt="...", tools=[]
        ),
    }
    prompt = build_orchestrator_prompt(agents)
    assert "design-advisor" in prompt
    assert "code-review" in prompt
    assert "Architecture review" in prompt
    assert "Code quality checks" in prompt


def test_prompt_contains_routing_instructions() -> None:
    agents = {
        "scaffold": AgentDefinition(description="Project gen", prompt="...", tools=[]),
    }
    prompt = build_orchestrator_prompt(agents)
    assert "orchestrator" in prompt.lower()
    assert "specialist" in prompt.lower()


def test_prompt_mentions_multi_specialist() -> None:
    agents = {
        "a": AgentDefinition(description="A desc", prompt="...", tools=[]),
        "b": AgentDefinition(description="B desc", prompt="...", tools=[]),
    }
    prompt = build_orchestrator_prompt(agents)
    assert "multiple specialists" in prompt
