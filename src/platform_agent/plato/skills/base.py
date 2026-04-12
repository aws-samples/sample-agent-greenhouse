"""Base skill class for the Foundation Agent + Skills pattern.

A SkillPack encapsulates:
  - A system prompt extension (domain knowledge)
  - Additional tools (as tool names or MCP server configs)
  - Metadata (name, description, version)

Compose pattern: skills are loaded onto a FoundationAgent to create
a specialist agent. Multiple skills can be composed together.
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SkillPack(ABC):
    """Base class for all skill packs.

    Subclasses must define `name` and `system_prompt_extension` at minimum.
    Override `tools` and `mcp_servers` to add tool capabilities.

    Subclasses can set field defaults as plain class attributes without needing
    the ``@dataclass`` decorator — ``__post_init__`` resolves them automatically.

    Example:
        class DesignAdvisorSkill(SkillPack):
            name = "design_advisor"
            description = "Architecture and design guidance"
            system_prompt_extension = "You specialize in agent architectures..."
            tools = ["Read", "Glob", "Grep"]
    """

    name: str = ""
    description: str = ""
    version: str = "0.1.0"
    system_prompt_extension: str = ""
    tools: list[str] = field(default_factory=list)
    mcp_servers: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Resolve class-level field defaults from subclasses.

        This supports the common pattern where a non-@dataclass subclass
        overrides field values as plain class attributes (e.g.
        ``name = "design_advisor"``). Without this, the parent dataclass
        ``__init__`` would always use its own defaults.
        """
        for f_name in self.__dataclass_fields__:
            for cls in type(self).__mro__:
                if cls is SkillPack:
                    break
                if f_name in cls.__dict__:
                    value = cls.__dict__[f_name]
                    if isinstance(value, (list, dict)):
                        value = copy.copy(value)
                    object.__setattr__(self, f_name, value)
                    break

    @abstractmethod
    def configure(self) -> None:
        """Initialize skill-specific configuration.

        Called when the skill is loaded onto an agent. Use this to set up
        MCP servers, validate dependencies, or load external resources.
        """
        ...


def load_skill(skill_cls: type[SkillPack], **kwargs) -> SkillPack:
    """Instantiate and configure a skill pack.

    Args:
        skill_cls: The SkillPack subclass to instantiate.
        **kwargs: Override any SkillPack fields.

    Returns:
        A configured SkillPack instance ready to be loaded onto an agent.
    """
    skill = skill_cls()
    # Apply explicit overrides after __post_init__ resolved class defaults
    for key, value in kwargs.items():
        object.__setattr__(skill, key, value)
    skill.configure()
    return skill


def compose(*skills: SkillPack) -> list[SkillPack]:
    """Compose multiple skill packs for loading onto a single agent.

    Validates that there are no conflicting MCP server names across skills.

    Args:
        *skills: SkillPack instances to compose.

    Returns:
        List of validated, ready-to-load skill packs.

    Raises:
        ValueError: If two skills define the same MCP server name.
    """
    seen_servers: dict[str, str] = {}
    for skill in skills:
        for server_name in skill.mcp_servers:
            if server_name in seen_servers:
                raise ValueError(
                    f"MCP server '{server_name}' defined by both "
                    f"'{seen_servers[server_name]}' and '{skill.name}'"
                )
            seen_servers[server_name] = skill.name
    return list(skills)
