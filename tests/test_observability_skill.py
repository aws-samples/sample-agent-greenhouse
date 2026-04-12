"""Tests for Observability Skill."""

from __future__ import annotations

from platform_agent.plato.skills.base import load_skill
from platform_agent.plato.skills.observability import ObservabilitySkill, OBSERVABILITY_PROMPT
from platform_agent.plato.skills import discover_skills, list_skills


class TestObservabilitySkill:
    def test_skill_name(self):
        skill = ObservabilitySkill()
        assert skill.name == "observability"

    def test_skill_description(self):
        skill = ObservabilitySkill()
        assert "observability" in skill.description.lower()
        assert "monitoring" in skill.description.lower()

    def test_skill_tools(self):
        skill = ObservabilitySkill()
        assert "Read" in skill.tools
        assert "Bash" in skill.tools

    def test_load_skill(self):
        skill = load_skill(ObservabilitySkill)
        assert skill.name == "observability"

    def test_version(self):
        skill = ObservabilitySkill()
        assert skill.version == "0.1.0"


class TestObservabilityPrompt:
    def test_prompt_mentions_agent_status(self):
        assert "Agent Status" in OBSERVABILITY_PROMPT

    def test_prompt_mentions_violations(self):
        assert "Violation" in OBSERVABILITY_PROMPT

    def test_prompt_mentions_audit(self):
        assert "Audit" in OBSERVABILITY_PROMPT

    def test_prompt_mentions_metrics(self):
        assert "Key Metrics" in OBSERVABILITY_PROMPT

    def test_prompt_mentions_reporting(self):
        assert "Report" in OBSERVABILITY_PROMPT

    def test_prompt_is_concise(self):
        assert len(OBSERVABILITY_PROMPT) < 3000


class TestObservabilityAutoDiscovery:
    def test_discover_includes_observability(self):
        discover_skills()
        names = list_skills()
        assert "observability" in names
