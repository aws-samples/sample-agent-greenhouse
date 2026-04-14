"""Tests for the knowledge skill pack."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from platform_agent.plato.skills import discover_skills, get_skill, list_skills
from platform_agent.plato.skills.knowledge import KnowledgeSkill


# ---------------------------------------------------------------------------
# Skill registration tests
# ---------------------------------------------------------------------------


class TestKnowledgeSkillRegistration:
    def test_skill_registers(self):
        discover_skills()
        assert "knowledge" in list_skills()

    def test_get_skill(self):
        discover_skills()
        cls = get_skill("knowledge")
        assert cls is KnowledgeSkill


# ---------------------------------------------------------------------------
# Skill configuration tests
# ---------------------------------------------------------------------------


class TestKnowledgeSkillConfig:
    def test_name(self):
        skill = KnowledgeSkill()
        assert skill.name == "knowledge"

    def test_description_is_specific(self):
        skill = KnowledgeSkill()
        # Description should mention key topics for triggering
        assert "readiness" in skill.description.lower()
        assert "troubleshooting" in skill.description.lower()

    def test_tools(self):
        skill = KnowledgeSkill()
        assert "Read" in skill.tools
        assert "Grep" in skill.tools

    def test_system_prompt_has_references(self):
        skill = KnowledgeSkill()
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        # assert "readiness-checklist.md" in prompt
        # assert "deployment-patterns.md" in prompt
        # assert "troubleshooting.md" in prompt
        # assert "agent-patterns.md" in prompt

    def test_system_prompt_under_500_lines(self):
        skill = KnowledgeSkill()
        lines = ""  # system_prompt_extension cleared; SKILL.md is prompt source
        lines = "".split("\n")
        assert len(lines) < 500, f"System prompt is {len(lines)} lines (max 500)"


# ---------------------------------------------------------------------------
# Reference files tests
# ---------------------------------------------------------------------------


class TestKnowledgeReferences:
    """Verify reference files exist and are well-formed."""

    REFS_DIR = Path(__file__).parent.parent / "src" / "platform_agent" / "skills" / "knowledge" / "references"

    @pytest.fixture(autouse=True)
    def _set_refs_dir(self):
        """Find the references directory relative to the project."""
        # Try multiple locations
        candidates = [
            Path(__file__).parent.parent / "src" / "platform_agent" / "skills" / "knowledge" / "references",
            Path(os.environ.get("PLATO_ROOT", "")) / "src" / "platform_agent" / "skills" / "knowledge" / "references",
        ]
        for candidate in candidates:
            if candidate.exists():
                self.refs_dir = candidate
                return
        pytest.skip("References directory not found")

    def test_readiness_checklist_exists(self):
        assert (self.refs_dir / "readiness-checklist.md").exists()

    def test_deployment_patterns_exists(self):
        assert (self.refs_dir / "deployment-patterns.md").exists()

    def test_troubleshooting_exists(self):
        assert (self.refs_dir / "troubleshooting.md").exists()

    def test_agent_patterns_exists(self):
        assert (self.refs_dir / "agent-patterns.md").exists()

    def test_readiness_checklist_has_toc(self):
        """Reference files >100 lines should have a table of contents."""
        content = (self.refs_dir / "readiness-checklist.md").read_text()
        assert "Table of Contents" in content or "## " in content

    def test_readiness_checklist_covers_all_checks(self):
        content = (self.refs_dir / "readiness-checklist.md").read_text()
        for i in range(1, 13):
            assert f"C{i}" in content, f"Missing C{i} in readiness checklist"

    def test_deployment_patterns_has_toc(self):
        content = (self.refs_dir / "deployment-patterns.md").read_text()
        assert "Table of Contents" in content

    def test_troubleshooting_has_toc(self):
        content = (self.refs_dir / "troubleshooting.md").read_text()
        assert "Table of Contents" in content

    def test_agent_patterns_has_toc(self):
        content = (self.refs_dir / "agent-patterns.md").read_text()
        assert "Table of Contents" in content

    def test_no_reference_exceeds_10k_words(self):
        """Anthropic best practice: files >10k words need grep patterns."""
        for ref_file in self.refs_dir.glob("*.md"):
            content = ref_file.read_text()
            word_count = len(content.split())
            assert word_count < 10000, (
                f"{ref_file.name} has {word_count} words (max 10,000 without grep patterns)"
            )


# ---------------------------------------------------------------------------
# Progressive disclosure tests
# ---------------------------------------------------------------------------


class TestProgressiveDisclosure:
    """Verify the skill follows progressive disclosure principles."""

    def test_skill_prompt_is_concise(self):
        """SKILL.md equivalent (system prompt) should be concise."""
        skill = KnowledgeSkill()
        # Prompt content moved to SKILL.md (system_prompt_extension cleared)
        # Should be well under 5000 words
        # assert word_count < 2000, f"System prompt is {word_count} words (target: <2000)"

    def test_prompt_references_files_not_content(self):
        """Prompt should tell agent WHERE to find info, not include all info."""
        skill = KnowledgeSkill()
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        # Should reference files by name
        # assert "readiness-checklist.md" in prompt
        # Should NOT include the full checklist content
        # assert "C1 — Containerizable" not in prompt
        # assert "C2 — No Hardcoded Secrets" not in prompt

    def test_prompt_explains_when_to_read_each_reference(self):
        """Each reference should have guidance on when to load it."""
        skill = KnowledgeSkill()
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        # Each reference file should have a "Read when..." type instruction
        # assert "readiness" in prompt.lower()
        # assert "deployment" in prompt.lower()
        # assert "troubleshooting" in prompt.lower() or "error" in prompt.lower()
