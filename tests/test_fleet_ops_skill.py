"""Tests for Fleet Ops Skill."""

from __future__ import annotations

from platform_agent.plato.skills.base import load_skill
from platform_agent.plato.skills.fleet_ops import FleetOpsSkill, FLEET_OPS_PROMPT
from platform_agent.plato.skills import discover_skills, list_skills


class TestFleetOpsSkill:
    def test_skill_name(self):
        skill = FleetOpsSkill()
        assert skill.name == "fleet_ops"

    def test_skill_description(self):
        skill = FleetOpsSkill()
        assert "fleet" in skill.description.lower()
        assert "restart" in skill.description.lower()

    def test_skill_tools(self):
        skill = FleetOpsSkill()
        assert "Read" in skill.tools
        assert "Bash" in skill.tools

    def test_load_skill(self):
        skill = load_skill(FleetOpsSkill)
        assert skill.name == "fleet_ops"

    def test_version(self):
        skill = FleetOpsSkill()
        assert skill.version == "0.1.0"


class TestFleetOpsPrompt:
    def test_prompt_mentions_restart(self):
        assert "Restart" in FLEET_OPS_PROMPT

    def test_prompt_mentions_scaling(self):
        assert "Scaling" in FLEET_OPS_PROMPT

    def test_prompt_mentions_draining(self):
        assert "Draining" in FLEET_OPS_PROMPT or "drain" in FLEET_OPS_PROMPT.lower()

    def test_prompt_mentions_shutdown(self):
        assert "Shutdown" in FLEET_OPS_PROMPT

    def test_prompt_mentions_health_checks(self):
        assert "Health" in FLEET_OPS_PROMPT

    def test_prompt_is_concise(self):
        assert len(FLEET_OPS_PROMPT) < 3000


class TestFleetOpsAutoDiscovery:
    def test_discover_includes_fleet_ops(self):
        discover_skills()
        names = list_skills()
        assert "fleet_ops" in names
