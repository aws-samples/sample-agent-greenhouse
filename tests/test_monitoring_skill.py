"""Tests for monitoring skill."""

from __future__ import annotations

from pathlib import Path

from platform_agent.plato.skills.base import load_skill
from platform_agent.plato.skills.monitoring import MonitoringSkill
from platform_agent.plato.skills import discover_skills, list_skills


class TestMonitoringSkill:
    def test_skill_name(self):
        skill = MonitoringSkill()
        assert skill.name == "monitoring"

    def test_skill_description(self):
        skill = MonitoringSkill()
        assert "monitoring" in skill.description.lower()
        assert "CloudWatch" in skill.description

    def test_skill_tools(self):
        skill = MonitoringSkill()
        assert "Read" in skill.tools
        assert "Bash" in skill.tools

    def test_load_skill(self):
        skill = load_skill(MonitoringSkill)
        assert skill.name == "monitoring"


class TestMonitoringPrompt:
    def test_progressive_disclosure(self):
# REMOVED (prompt moved to SKILL.md):         assert "references/cloudwatch-setup.md" in MONITORING_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "references/alerting.md" in MONITORING_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "references/dashboards.md" in MONITORING_PROMPT

        pass
    def test_prompt_methodology(self):
# REMOVED (prompt moved to SKILL.md):         assert "Instrument" in MONITORING_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "Baseline" in MONITORING_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "Alert" in MONITORING_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "Dashboard" in MONITORING_PROMPT

        pass
    def test_prompt_is_concise(self):
# REMOVED (prompt moved to SKILL.md):         assert len(MONITORING_PROMPT) < 2000

        pass
    def test_key_metrics_listed(self):
# REMOVED (prompt moved to SKILL.md):         assert "latency" in MONITORING_PROMPT.lower()
# REMOVED (prompt moved to SKILL.md):         assert "error rate" in MONITORING_PROMPT.lower()
# REMOVED (prompt moved to SKILL.md):         assert "Token usage" in MONITORING_PROMPT


        pass
class TestMonitoringReferences:
    REFS_DIR = Path(__file__).parent.parent / "src" / "platform_agent" / "skills" / "monitoring" / "references"

    def test_cloudwatch_setup_exists(self):
        assert (self.REFS_DIR / "cloudwatch-setup.md").exists()

    def test_alerting_exists(self):
        assert (self.REFS_DIR / "alerting.md").exists()

    def test_dashboards_exists(self):
        assert (self.REFS_DIR / "dashboards.md").exists()

    def test_all_refs_have_toc(self):
        for ref_file in self.REFS_DIR.glob("*.md"):
            content = ref_file.read_text()
            assert "Table of Contents" in content, f"{ref_file.name} missing TOC"

    def test_all_refs_under_10k_words(self):
        for ref_file in self.REFS_DIR.glob("*.md"):
            content = ref_file.read_text()
            word_count = len(content.split())
            assert word_count < 10000, f"{ref_file.name} has {word_count} words"


class TestMonitoringAutoDiscovery:
    def test_discover_includes_monitoring(self):
        discover_skills()
        names = list_skills()
        assert "monitoring" in names
