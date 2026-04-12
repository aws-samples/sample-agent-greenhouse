"""Tests for DomainHarness schema dataclasses."""

import tempfile
from pathlib import Path

import pytest

from platform_agent.foundation.harness import (
    DomainHarness,
    EvalRule,
    HookConfig,
    MemoryConfig,
    PersonaConfig,
    PolicyConfig,
    SkillRef,
)


def test_domain_harness_creation():
    harness = DomainHarness(
        name="test",
        description="A test harness",
        version="0.1.0",
    )
    assert harness.name == "test"
    assert harness.description == "A test harness"
    assert harness.version == "0.1.0"


def test_domain_harness_defaults():
    harness = DomainHarness(name="minimal")
    assert harness.description == ""
    assert harness.version == "0.1.0"
    assert harness.skills == []
    assert harness.tools == []
    assert harness.mcp_servers == {}
    assert harness.policies == PolicyConfig()
    assert harness.memory_config == MemoryConfig()
    assert harness.eval_criteria == []
    assert harness.hooks == []
    assert harness.persona is None


def test_policy_config_defaults():
    policy = PolicyConfig()
    assert policy.tool_allowlist == []
    assert policy.tool_denylist == []
    assert policy.cedar_policies == []
    assert policy.max_tool_calls_per_turn is None


def test_memory_config_defaults():
    mem = MemoryConfig()
    assert mem.namespace_template == ""
    assert mem.persist_types == []
    assert mem.ttl_days == 90
    assert mem.extraction_enabled is False
    assert mem.consolidation_enabled is False


def test_eval_rule_creation():
    rule = EvalRule(
        name="quality",
        description="Quality check",
        threshold=0.8,
        scorer="my_scorer.Score",
    )
    assert rule.name == "quality"
    assert rule.description == "Quality check"
    assert rule.threshold == 0.8
    assert rule.scorer == "my_scorer.Score"


def test_hook_config_creation():
    hook = HookConfig(hook="AuditHook", category="foundation")
    assert hook.hook == "AuditHook"
    assert hook.category == "foundation"
    assert hook.enabled_by is None
    assert hook.params == {}

    optional_hook = HookConfig(
        hook="ExtractionHook",
        category="optional",
        enabled_by="memory_config.extraction_enabled",
        params={"key": "value"},
    )
    assert optional_hook.enabled_by == "memory_config.extraction_enabled"
    assert optional_hook.params == {"key": "value"}


def test_persona_config_creation():
    persona = PersonaConfig(
        tone="formal",
        communication_style="verbose",
        role="assistant",
        constraints=["no code"],
    )
    assert persona.tone == "formal"
    assert persona.communication_style == "verbose"
    assert persona.role == "assistant"
    assert persona.constraints == ["no code"]


def test_skill_ref_creation():
    skill = SkillRef(name="debug", description="Debug skill", tools=["Read", "Bash"])
    assert skill.name == "debug"
    assert skill.description == "Debug skill"
    assert skill.tools == ["Read", "Bash"]

    skill_no_tools = SkillRef(name="empty", description="No tools")
    assert skill_no_tools.tools == []


def test_domain_harness_to_dict_roundtrip():
    original = DomainHarness(
        name="roundtrip",
        description="Roundtrip test",
        version="2.0.0",
        skills=[SkillRef(name="s1", description="Skill 1", tools=["Read"])],
        tools=["tool_a"],
        mcp_servers={"server1": {"url": "http://localhost"}},
        policies=PolicyConfig(tool_allowlist=["Read"], max_tool_calls_per_turn=10),
        memory_config=MemoryConfig(
            namespace_template="/test/{id}/",
            persist_types=["report"],
            ttl_days=30,
            extraction_enabled=True,
        ),
        eval_criteria=[
            EvalRule(name="q", description="Quality", threshold=0.9, scorer="s.S")
        ],
        hooks=[
            HookConfig(hook="H1", category="foundation"),
            HookConfig(
                hook="H2", category="optional", enabled_by="flag", params={"x": 1}
            ),
        ],
        persona=PersonaConfig(
            tone="casual",
            communication_style="brief",
            role="helper",
            constraints=["be nice"],
        ),
    )
    d = original.to_dict()
    restored = DomainHarness.from_dict(d)
    assert restored.to_dict() == d


def test_domain_harness_yaml_roundtrip():
    original = DomainHarness(
        name="yaml-test",
        description="YAML roundtrip",
        version="1.0.0",
        skills=[SkillRef(name="s1", description="Skill 1", tools=["Read", "Write"])],
        tools=["tool_x"],
        policies=PolicyConfig(tool_denylist=["Dangerous"]),
        memory_config=MemoryConfig(namespace_template="/ns/", ttl_days=60),
        eval_criteria=[
            EvalRule(name="e1", description="Eval 1", threshold=0.75, scorer="e.E")
        ],
        hooks=[HookConfig(hook="TestHook", category="domain", params={"a": "b"})],
        persona=PersonaConfig(
            tone="neutral",
            communication_style="direct",
            role="tester",
        ),
    )
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        tmp_path = Path(f.name)
    try:
        original.to_yaml(tmp_path)
        restored = DomainHarness.from_yaml(tmp_path)
        assert restored.to_dict() == original.to_dict()
    finally:
        tmp_path.unlink(missing_ok=True)


def test_domain_harness_validation_missing_name():
    with pytest.raises(ValueError, match="name"):
        DomainHarness(name="")
