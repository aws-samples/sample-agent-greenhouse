"""Domain Harness schema — pure data definitions + serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PolicyConfig:
    """Tool-level access policies."""

    tool_allowlist: list[str] = field(default_factory=list)
    tool_denylist: list[str] = field(default_factory=list)
    cedar_policies: list[str] = field(default_factory=list)
    max_tool_calls_per_turn: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_allowlist": list(self.tool_allowlist),
            "tool_denylist": list(self.tool_denylist),
            "cedar_policies": list(self.cedar_policies),
            "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyConfig:
        return cls(
            tool_allowlist=data.get("tool_allowlist", []),
            tool_denylist=data.get("tool_denylist", []),
            cedar_policies=data.get("cedar_policies", []),
            max_tool_calls_per_turn=data.get("max_tool_calls_per_turn"),
        )


@dataclass(frozen=True)
class MemoryConfig:
    """Memory layer configuration."""

    namespace_template: str = ""
    persist_types: list[str] = field(default_factory=list)
    ttl_days: int = 90
    extraction_enabled: bool = False
    consolidation_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace_template": self.namespace_template,
            "persist_types": list(self.persist_types),
            "ttl_days": self.ttl_days,
            "extraction_enabled": self.extraction_enabled,
            "consolidation_enabled": self.consolidation_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryConfig:
        return cls(
            namespace_template=data.get("namespace_template", ""),
            persist_types=data.get("persist_types", []),
            ttl_days=data.get("ttl_days", 90),
            extraction_enabled=data.get("extraction_enabled", False),
            consolidation_enabled=data.get("consolidation_enabled", False),
        )


@dataclass(frozen=True)
class EvalRule:
    """Single evaluation criterion."""

    name: str
    description: str
    threshold: float | int
    scorer: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "threshold": self.threshold,
            "scorer": self.scorer,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalRule:
        return cls(
            name=data["name"],
            description=data["description"],
            threshold=data["threshold"],
            scorer=data["scorer"],
        )


@dataclass(frozen=True)
class HookConfig:
    """Hook registration entry."""

    hook: str
    category: str  # "foundation" | "domain" | "optional"
    enabled_by: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "hook": self.hook,
            "category": self.category,
        }
        if self.enabled_by is not None:
            result["enabled_by"] = self.enabled_by
        result["params"] = dict(self.params)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HookConfig:
        return cls(
            hook=data["hook"],
            category=data["category"],
            enabled_by=data.get("enabled_by"),
            params=data.get("params", {}),
        )


@dataclass(frozen=True)
class PersonaConfig:
    """Agent persona definition."""

    tone: str
    communication_style: str
    role: str
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tone": self.tone,
            "communication_style": self.communication_style,
            "role": self.role,
            "constraints": list(self.constraints),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersonaConfig:
        return cls(
            tone=data["tone"],
            communication_style=data["communication_style"],
            role=data["role"],
            constraints=data.get("constraints", []),
        )


@dataclass(frozen=True)
class SkillRef:
    """Lightweight skill reference (not the full SkillPack)."""

    name: str
    description: str
    tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tools": list(self.tools),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillRef:
        return cls(
            name=data["name"],
            description=data["description"],
            tools=data.get("tools", []),
        )


@dataclass(frozen=True)
class DomainHarness:
    """Complete domain harness configuration."""

    name: str
    description: str = ""
    version: str = "0.1.0"
    skills: list[SkillRef] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    policies: PolicyConfig = field(default_factory=PolicyConfig)
    memory_config: MemoryConfig = field(default_factory=MemoryConfig)
    eval_criteria: list[EvalRule] = field(default_factory=list)
    hooks: list[HookConfig] = field(default_factory=list)
    persona: PersonaConfig | None = None
    workspace_context_enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("DomainHarness.name must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "skills": [s.to_dict() for s in self.skills],
            "tools": list(self.tools),
            "mcp_servers": dict(self.mcp_servers),
            "policies": self.policies.to_dict(),
            "memory_config": self.memory_config.to_dict(),
            "eval_criteria": [e.to_dict() for e in self.eval_criteria],
            "hooks": [h.to_dict() for h in self.hooks],
        }
        if self.persona is not None:
            result["persona"] = self.persona.to_dict()
        result["workspace_context_enabled"] = self.workspace_context_enabled
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainHarness:
        persona_data = data.get("persona")
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "0.1.0"),
            skills=[SkillRef.from_dict(s) for s in data.get("skills", [])],
            tools=data.get("tools", []),
            mcp_servers=data.get("mcp_servers", {}),
            policies=PolicyConfig.from_dict(data.get("policies", {})),
            memory_config=MemoryConfig.from_dict(data.get("memory_config", {})),
            eval_criteria=[EvalRule.from_dict(e) for e in data.get("eval_criteria", [])],
            hooks=[HookConfig.from_dict(h) for h in data.get("hooks", [])],
            persona=PersonaConfig.from_dict(persona_data) if persona_data else None,
            workspace_context_enabled=data.get("workspace_context_enabled", True),
        )

    def to_yaml(self, path: str | Path) -> None:
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, path: str | Path) -> DomainHarness:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)
