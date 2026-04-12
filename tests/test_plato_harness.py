"""Tests for Plato domain harness factory."""

from pathlib import Path

import yaml

from platform_agent.plato.harness import create_plato_harness

GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "plato_harness.yaml"


def test_plato_harness_has_all_skills():
    harness = create_plato_harness()
    assert len(harness.skills) == 16
    expected_names = [
        "aidlc_inception",
        "code_review",
        "debug",
        "deployment_config",
        "design_advisor",
        "fleet_ops",
        "governance",
        "issue_creator",
        "knowledge",
        "monitoring",
        "observability",
        "onboarding",
        "pr_review",
        "scaffold",
        "spec_compliance",
        "test_case_generator",
    ]
    actual_names = [s.name for s in harness.skills]
    assert actual_names == expected_names


def test_plato_harness_has_correct_hooks():
    harness = create_plato_harness()
    always_active = [h for h in harness.hooks if h.category != "optional"]
    optional = [h for h in harness.hooks if h.category == "optional"]
    assert len(always_active) == 12
    assert len(optional) == 2
    assert optional[0].hook == "MemoryExtractionHook"
    assert optional[1].hook == "ConsolidationHook"
    assert optional[0].enabled_by == "memory_config.extraction_enabled"
    assert optional[1].enabled_by == "memory_config.consolidation_enabled"


def test_plato_harness_policies_defaults():
    harness = create_plato_harness()
    assert harness.policies.tool_allowlist == []
    assert harness.policies.tool_denylist == []
    assert harness.policies.cedar_policies == []
    assert harness.policies.max_tool_calls_per_turn is None


def test_plato_harness_memory_config_has_namespace():
    harness = create_plato_harness()
    assert harness.memory_config.namespace_template == "/plato/{actorId}/"
    assert len(harness.memory_config.persist_types) == 5
    assert harness.memory_config.ttl_days == 90


def test_plato_harness_eval_criteria_defined():
    harness = create_plato_harness()
    assert len(harness.eval_criteria) == 3
    names = [e.name for e in harness.eval_criteria]
    assert names == ["spec_quality", "code_review_coverage", "readiness_checklist"]


def test_plato_harness_persona_defined():
    harness = create_plato_harness()
    assert harness.persona is not None
    assert harness.persona.tone == "technical"
    assert harness.persona.communication_style == "concise but thorough"
    assert len(harness.persona.constraints) == 2


def test_plato_harness_yaml_roundtrip_matches_ground_truth():
    with open(GROUND_TRUTH_PATH) as f:
        ground_truth = yaml.safe_load(f)

    harness_dict = create_plato_harness().to_dict()
    assert harness_dict == ground_truth
