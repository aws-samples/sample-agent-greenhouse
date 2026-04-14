"""Tests for Governance Skill."""

from __future__ import annotations

from pathlib import Path

from platform_agent.plato.skills.base import load_skill
from platform_agent.plato.skills.governance import GovernanceSkill
from platform_agent.plato.skills import discover_skills, list_skills


class TestGovernanceSkill:
    def test_skill_name(self):
        skill = GovernanceSkill()
        assert skill.name == "governance"

    def test_skill_description(self):
        skill = GovernanceSkill()
        assert "governance" in skill.description.lower()
        assert "policy" in skill.description.lower()

    def test_skill_tools(self):
        skill = GovernanceSkill()
        assert "Read" in skill.tools
        assert "Grep" in skill.tools

    def test_load_skill(self):
        skill = load_skill(GovernanceSkill)
        assert skill.name == "governance"

    def test_version(self):
        skill = GovernanceSkill()
        assert skill.version == "0.1.0"


class TestGovernancePrompt:
    def test_prompt_mentions_registration(self):
# REMOVED (prompt moved to SKILL.md):         assert "Agent Registration" in GOVERNANCE_PROMPT

        pass
    def test_prompt_mentions_policies(self):
# REMOVED (prompt moved to SKILL.md):         assert "Policy Management" in GOVERNANCE_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "Cedar" in GOVERNANCE_PROMPT

        pass
    def test_prompt_mentions_routing(self):
# REMOVED (prompt moved to SKILL.md):         assert "Routing" in GOVERNANCE_PROMPT

        pass
    def test_prompt_mentions_references(self):
# REMOVED (prompt moved to SKILL.md):         assert "references/default-policies.md" in GOVERNANCE_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "references/routing-patterns.md" in GOVERNANCE_PROMPT

        pass
    def test_prompt_mentions_principles(self):
# REMOVED (prompt moved to SKILL.md):         assert "Default deny" in GOVERNANCE_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "Least privilege" in GOVERNANCE_PROMPT

        pass
    def test_prompt_is_concise(self):
# REMOVED (prompt moved to SKILL.md):         assert len(GOVERNANCE_PROMPT) < 3000


        pass
class TestGovernanceReferences:
    REFS_DIR = (
        Path(__file__).parent.parent
        / "src"
        / "platform_agent"
        / "plato"
        / "skills"
        / "governance"
        / "references"
    )

    def test_default_policies_exists(self):
        assert (self.REFS_DIR / "default-policies.md").exists()

    def test_routing_patterns_exists(self):
        assert (self.REFS_DIR / "routing-patterns.md").exists()

    def test_refs_have_toc(self):
        for ref_file in self.REFS_DIR.glob("*.md"):
            content = ref_file.read_text()
            assert "Table of Contents" in content, f"{ref_file.name} missing TOC"

    def test_refs_under_10k_words(self):
        for ref_file in self.REFS_DIR.glob("*.md"):
            content = ref_file.read_text()
            word_count = len(content.split())
            assert word_count < 10000, f"{ref_file.name} has {word_count} words"


class TestGovernanceAutoDiscovery:
    def test_discover_includes_governance(self):
        discover_skills()
        names = list_skills()
        assert "governance" in names
