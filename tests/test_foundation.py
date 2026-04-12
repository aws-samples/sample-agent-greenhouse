"""Tests for FoundationAgent system prompt and tool building."""

from __future__ import annotations

from platform_agent._legacy_foundation import FoundationAgent
from platform_agent.memory import InMemoryStore
from platform_agent.plato.skills.base import SkillPack, load_skill


# -- Test skill fixtures --------------------------------------------------------


class _ReadOnlySkill(SkillPack):
    name = "reader"
    description = "Read-only skill"
    system_prompt_extension = "You can only read files."
    tools = ["Read", "Glob"]

    def configure(self) -> None:
        pass


class _WriterSkill(SkillPack):
    name = "writer"
    description = "Writer skill"
    system_prompt_extension = "You can write files."
    tools = ["Write", "Edit"]

    def configure(self) -> None:
        pass


class _McpSkill(SkillPack):
    name = "mcp_skill"
    description = "Skill with MCP servers"
    system_prompt_extension = "MCP-enabled."
    mcp_servers = {"my_server": {"command": "serve"}}

    def configure(self) -> None:
        pass


# -- System prompt tests --------------------------------------------------------


def test_base_prompt_without_skills() -> None:
    agent = FoundationAgent()
    prompt = agent._build_system_prompt()
    assert "Plato" in prompt
    assert "CLAUDE.md" in prompt


def test_prompt_includes_skill_extensions() -> None:
    agent = FoundationAgent()
    agent.load_skill(load_skill(_ReadOnlySkill))
    prompt = agent._build_system_prompt()
    assert "## reader Capabilities" in prompt
    assert "You can only read files." in prompt


def test_prompt_includes_multiple_skills() -> None:
    agent = FoundationAgent()
    agent.load_skill(load_skill(_ReadOnlySkill))
    agent.load_skill(load_skill(_WriterSkill))
    prompt = agent._build_system_prompt()
    assert "## reader Capabilities" in prompt
    assert "## writer Capabilities" in prompt


def test_prompt_includes_memory_section() -> None:
    store = InMemoryStore()
    agent = FoundationAgent(memory_store=store)
    prompt = agent._build_system_prompt()
    assert "## Memory" in prompt
    assert "persistent memory store" in prompt


def test_prompt_no_memory_section_without_store() -> None:
    agent = FoundationAgent()
    prompt = agent._build_system_prompt()
    assert "## Memory" not in prompt


# -- Tool building tests --------------------------------------------------------


def test_base_tools() -> None:
    agent = FoundationAgent()
    tools = agent._build_tools()
    assert "Read" in tools
    assert "Write" in tools
    assert "Edit" in tools
    assert "Bash" in tools
    assert "Glob" in tools
    assert "Grep" in tools


def test_tools_include_skill_tools() -> None:
    agent = FoundationAgent()
    agent.load_skill(load_skill(_ReadOnlySkill))
    tools = agent._build_tools()
    assert "Read" in tools
    assert "Glob" in tools


def test_tools_accumulate_across_skills() -> None:
    agent = FoundationAgent()
    agent.load_skill(load_skill(_ReadOnlySkill))
    agent.load_skill(load_skill(_WriterSkill))
    tools = agent._build_tools()
    assert "Read" in tools
    assert "Glob" in tools
    assert "Write" in tools
    assert "Edit" in tools


# -- MCP server tests -----------------------------------------------------------


def test_no_mcp_servers_by_default() -> None:
    agent = FoundationAgent()
    servers = agent._build_mcp_servers()
    assert servers == {}


def test_mcp_servers_from_skill() -> None:
    agent = FoundationAgent()
    agent.load_skill(load_skill(_McpSkill))
    servers = agent._build_mcp_servers()
    assert "my_server" in servers
    assert servers["my_server"] == {"command": "serve"}


# -- Configuration tests --------------------------------------------------------


def test_default_model() -> None:
    agent = FoundationAgent()
    assert agent.model == "claude-sonnet-4-20250514"


def test_custom_model() -> None:
    agent = FoundationAgent(model="claude-sonnet-4-20250514")
    assert agent.model == "claude-sonnet-4-20250514"


def test_load_skill_appends() -> None:
    agent = FoundationAgent()
    assert len(agent.skills) == 0
    agent.load_skill(load_skill(_ReadOnlySkill))
    assert len(agent.skills) == 1
    agent.load_skill(load_skill(_WriterSkill))
    assert len(agent.skills) == 2


def test_memory_store_default_none() -> None:
    agent = FoundationAgent()
    assert agent.memory_store is None


def test_memory_store_can_be_set() -> None:
    store = InMemoryStore()
    agent = FoundationAgent(memory_store=store)
    assert agent.memory_store is store
