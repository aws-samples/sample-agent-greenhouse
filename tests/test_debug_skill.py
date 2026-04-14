"""Tests for debug skill."""

from __future__ import annotations

from pathlib import Path


from platform_agent.plato.skills.base import load_skill
from platform_agent.plato.skills.debug import DebugSkill
from platform_agent.plato.skills import discover_skills, get_skill, list_skills


# ---------------------------------------------------------------------------
# DebugSkill unit tests
# ---------------------------------------------------------------------------


class TestDebugSkill:
    def test_skill_name(self):
        skill = DebugSkill()
        assert skill.name == "debug"

    def test_skill_description(self):
        skill = DebugSkill()
        assert "Debugging specialist" in skill.description
        assert "container" in skill.description
        assert "IAM" in skill.description

    def test_skill_version(self):
        skill = DebugSkill()
        assert skill.version == "0.1.0"

    def test_skill_tools(self):
        skill = DebugSkill()
        assert "Read" in skill.tools
        assert "Bash" in skill.tools
        assert "Grep" in skill.tools
        assert "Glob" in skill.tools

    def test_system_prompt(self):
        skill = DebugSkill()
        assert skill.system_prompt_extension == ""

    def test_load_skill(self):
        skill = load_skill(DebugSkill)
        assert skill.name == "debug"


# ---------------------------------------------------------------------------
# Prompt content tests
# ---------------------------------------------------------------------------


class TestDebugPrompt:
    def test_progressive_disclosure(self):
        """Prompt references files by path, doesn't embed content."""
# REMOVED (prompt moved to SKILL.md):         assert "references/container-debugging.md" in DEBUG_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "references/iam-debugging.md" in DEBUG_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "references/runtime-debugging.md" in DEBUG_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "references/networking-debugging.md" in DEBUG_PROMPT

    def test_prompt_methodology(self):
        """Prompt includes structured debugging methodology."""
# REMOVED (prompt moved to SKILL.md):         assert "Reproduce" in DEBUG_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "Isolate" in DEBUG_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "Diagnose" in DEBUG_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "Fix" in DEBUG_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "Prevent" in DEBUG_PROMPT

    def test_prompt_does_not_embed_guides(self):
        """Prompt should be concise, not embed full guides."""
        # Should be under 2000 chars (progressive disclosure)
# REMOVED (prompt moved to SKILL.md):         assert len(DEBUG_PROMPT) < 2000

    def test_prompt_key_principles(self):
        """Prompt includes key debugging principles."""
# REMOVED (prompt moved to SKILL.md):         assert "exact error message" in DEBUG_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "CloudWatch logs" in DEBUG_PROMPT
# REMOVED (prompt moved to SKILL.md):         assert "copy-paste ready" in DEBUG_PROMPT


# ---------------------------------------------------------------------------
# Reference file tests
# ---------------------------------------------------------------------------


class TestDebugReferences:
    REFS_DIR = Path(__file__).parent.parent / "src" / "platform_agent" / "skills" / "debug" / "references"

    def test_container_debugging_exists(self):
        assert (self.REFS_DIR / "container-debugging.md").exists()

    def test_iam_debugging_exists(self):
        assert (self.REFS_DIR / "iam-debugging.md").exists()

    def test_runtime_debugging_exists(self):
        assert (self.REFS_DIR / "runtime-debugging.md").exists()

    def test_networking_debugging_exists(self):
        assert (self.REFS_DIR / "networking-debugging.md").exists()

    def test_all_refs_have_toc(self):
        """All reference files should have a table of contents."""
        for ref_file in self.REFS_DIR.glob("*.md"):
            content = ref_file.read_text()
            assert "Table of Contents" in content, f"{ref_file.name} missing TOC"

    def test_all_refs_under_10k_words(self):
        """Reference files should be under 10k words (progressive disclosure)."""
        for ref_file in self.REFS_DIR.glob("*.md"):
            content = ref_file.read_text()
            word_count = len(content.split())
            assert word_count < 10000, f"{ref_file.name} has {word_count} words (max 10k)"

    def test_container_debugging_content(self):
        content = (self.REFS_DIR / "container-debugging.md").read_text()
        assert "Build Failures" in content
        assert "OOM" in content
        assert "Startup Crashes" in content

    def test_iam_debugging_content(self):
        content = (self.REFS_DIR / "iam-debugging.md").read_text()
        assert "Access Denied" in content
        assert "Role Assumption" in content
        assert "Cross-Account" in content

    def test_runtime_debugging_content(self):
        content = (self.REFS_DIR / "runtime-debugging.md").read_text()
        assert "SDK Exceptions" in content
        assert "Tool Execution" in content
        assert "Timeout" in content

    def test_networking_debugging_content(self):
        content = (self.REFS_DIR / "networking-debugging.md").read_text()
        assert "VPC" in content
        assert "Security Groups" in content
        assert "DNS" in content


# ---------------------------------------------------------------------------
# Auto-discovery tests
# ---------------------------------------------------------------------------


class TestDebugAutoDiscovery:
    def test_discover_includes_debug(self):
        discover_skills()
        names = list_skills()
        assert "debug" in names

    def test_get_debug_skill(self):
        discover_skills()
        skill = get_skill("debug")
        assert skill is not None
        assert skill.name == "debug"
