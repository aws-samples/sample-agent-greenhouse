"""Tests for skill registration, discovery, and compose validation."""

from __future__ import annotations

import sys

import pytest

from platform_agent.plato.skills.base import SkillPack, load_skill, compose
from platform_agent.plato.skills import _registry, register_skill, get_skill, list_skills, discover_skills


# -- Concrete test skill -------------------------------------------------------


class _TestSkill(SkillPack):
    name = "test_skill"
    description = "A test skill"
    system_prompt_extension = "You are a test skill."
    tools = ["Read", "Glob"]

    def configure(self) -> None:
        pass


class _AnotherSkill(SkillPack):
    name = "another_skill"
    description = "Another test skill"
    system_prompt_extension = "Another skill."
    tools = ["Write"]

    def configure(self) -> None:
        pass


class _McpSkillA(SkillPack):
    name = "mcp_a"
    description = "MCP skill A"
    system_prompt_extension = ""
    mcp_servers = {"shared_server": {"command": "a"}}

    def configure(self) -> None:
        pass


class _McpSkillB(SkillPack):
    name = "mcp_b"
    description = "MCP skill B"
    system_prompt_extension = ""
    mcp_servers = {"shared_server": {"command": "b"}}

    def configure(self) -> None:
        pass


# -- Registration tests ---------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the skill registry before each test."""
    saved = dict(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


def test_register_and_get_skill() -> None:
    register_skill("test_skill", _TestSkill)
    cls = get_skill("test_skill")
    assert cls is _TestSkill


def test_get_skill_not_found() -> None:
    with pytest.raises(KeyError, match="not found"):
        get_skill("nonexistent")


def test_list_skills_empty() -> None:
    assert list_skills() == []


def test_list_skills_populated() -> None:
    register_skill("alpha", _TestSkill)
    register_skill("beta", _AnotherSkill)
    names = list_skills()
    assert "alpha" in names
    assert "beta" in names
    assert len(names) == 2


def test_register_overwrites() -> None:
    register_skill("skill", _TestSkill)
    register_skill("skill", _AnotherSkill)
    assert get_skill("skill") is _AnotherSkill


# -- load_skill tests -----------------------------------------------------------


def test_load_skill_creates_instance() -> None:
    skill = load_skill(_TestSkill)
    assert isinstance(skill, _TestSkill)
    assert skill.name == "test_skill"
    assert skill.tools == ["Read", "Glob"]


def test_load_skill_with_overrides() -> None:
    skill = load_skill(_TestSkill, name="custom_name", version="2.0.0")
    assert skill.name == "custom_name"
    assert skill.version == "2.0.0"


# -- compose tests ---------------------------------------------------------------


def test_compose_no_conflicts() -> None:
    s1 = load_skill(_TestSkill)
    s2 = load_skill(_AnotherSkill)
    result = compose(s1, s2)
    assert len(result) == 2
    assert result[0] is s1
    assert result[1] is s2


def test_compose_mcp_conflict_raises() -> None:
    s_a = load_skill(_McpSkillA)
    s_b = load_skill(_McpSkillB)
    with pytest.raises(ValueError, match="shared_server"):
        compose(s_a, s_b)


def test_compose_empty() -> None:
    result = compose()
    assert result == []


# -- discover_skills tests -------------------------------------------------------


def test_discover_skills_populates_registry() -> None:
    """discover_skills should find the built-in skill packs."""
    _registry.clear()
    # Remove cached skill modules so re-import triggers register_skill() calls
    to_remove = [k for k in sys.modules if k.startswith("platform_agent.plato.skills.") and k != "platform_agent.plato.skills.base"]
    for k in to_remove:
        del sys.modules[k]
    discover_skills()
    names = list_skills()
    assert "design-advisor" in names
    assert "scaffold" in names
    assert "code-review" in names
    assert "deployment-config" in names
