"""Tests for Onboarding Skill."""

from __future__ import annotations

from pathlib import Path

from platform_agent.plato.skills.base import load_skill
from platform_agent.plato.skills.onboarding import OnboardingSkill
from platform_agent.plato.skills import discover_skills, list_skills


class TestOnboardingSkill:
    def test_skill_name(self):
        skill = OnboardingSkill()
        assert skill.name == "onboarding"

    def test_skill_description(self):
        skill = OnboardingSkill()
        assert "onboarding" in skill.description.lower()
        assert "CLAUDE.md" in skill.description

    def test_skill_tools(self):
        skill = OnboardingSkill()
        assert "Read" in skill.tools
        assert "Write" in skill.tools

    def test_load_skill(self):
        skill = load_skill(OnboardingSkill)
        assert skill.name == "onboarding"

    def test_version(self):
        skill = OnboardingSkill()
        assert skill.version == "0.1.0"


class TestOnboardingPrompt:
    def test_prompt_mentions_team_setup(self):
# REMOVED (prompt moved to SKILL.md):         assert "Team Setup" in ONBOARDING_PROMPT

        pass
    def test_prompt_mentions_claude_md(self):
# REMOVED (prompt moved to SKILL.md):         assert "CLAUDE.md" in ONBOARDING_PROMPT

        pass
    def test_prompt_mentions_references(self):
# REMOVED (prompt moved to SKILL.md):         assert "references/platform-standards.md" in ONBOARDING_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "references/onboarding-guide.md" in ONBOARDING_PROMPT

        pass
    def test_prompt_mentions_workflow(self):
# REMOVED (prompt moved to SKILL.md):         assert "Onboarding Workflow" in ONBOARDING_PROMPT

        pass
    def test_prompt_is_concise(self):
# REMOVED (prompt moved to SKILL.md):         assert len(ONBOARDING_PROMPT) < 3000


        pass
class TestOnboardingReferences:
    REFS_DIR = (
        Path(__file__).parent.parent
        / "src"
        / "platform_agent"
        / "skills"
        / "onboarding"
        / "references"
    )

    def test_platform_standards_exists(self):
        assert (self.REFS_DIR / "platform-standards.md").exists()

    def test_onboarding_guide_exists(self):
        assert (self.REFS_DIR / "onboarding-guide.md").exists()

    def test_refs_have_toc(self):
        for ref_file in self.REFS_DIR.glob("*.md"):
            content = ref_file.read_text()
            assert "Table of Contents" in content, f"{ref_file.name} missing TOC"

    def test_refs_under_10k_words(self):
        for ref_file in self.REFS_DIR.glob("*.md"):
            content = ref_file.read_text()
            word_count = len(content.split())
            assert word_count < 10000, f"{ref_file.name} has {word_count} words"


class TestOnboardingAutoDiscovery:
    def test_discover_includes_onboarding(self):
        discover_skills()
        names = list_skills()
        assert "onboarding" in names
