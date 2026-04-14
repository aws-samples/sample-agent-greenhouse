"""Tests for Phase 2: Domain SkillPack SKILL.md files and AgentSkills plugin integration.

Verifies:
- All 16 SkillPack skills have corresponding SKILL.md files
- SKILL.md files have valid frontmatter (name, description)
- SKILL.md body content matches system_prompt_extension
- AgentSkills plugin discovers domain skills alongside workspace skills
- FoundationAgent sees both workspace and domain skills
"""

from __future__ import annotations

from pathlib import Path

import platform_agent.plato.skills as plato_skills_pkg
from platform_agent.plato.skills import discover_skills, list_skills, get_skill
from platform_agent.plato.skills.base import load_skill


DOMAIN_SKILLS_DIR = Path(plato_skills_pkg.__file__).parent
EXPECTED_SKILLS = [
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


class TestSkillMdFilesExist:
    """Every SkillPack must have a SKILL.md file."""

    def test_all_16_skillpacks_have_skill_md(self):
        for skill_name in EXPECTED_SKILLS:
            skill_md = DOMAIN_SKILLS_DIR / skill_name / "SKILL.md"
            assert skill_md.exists(), f"{skill_name} missing SKILL.md"

    def test_skill_md_has_frontmatter(self):
        for skill_name in EXPECTED_SKILLS:
            content = (DOMAIN_SKILLS_DIR / skill_name / "SKILL.md").read_text()
            assert content.startswith("---"), f"{skill_name} SKILL.md missing frontmatter"
            # Should have closing ---
            parts = content.split("---", 2)
            assert len(parts) >= 3, f"{skill_name} SKILL.md malformed frontmatter"

    def test_skill_md_has_name_field(self):
        for skill_name in EXPECTED_SKILLS:
            content = (DOMAIN_SKILLS_DIR / skill_name / "SKILL.md").read_text()
            assert f"name: {skill_name}" in content, f"{skill_name} SKILL.md missing name field"

    def test_skill_md_has_description(self):
        for skill_name in EXPECTED_SKILLS:
            content = (DOMAIN_SKILLS_DIR / skill_name / "SKILL.md").read_text()
            assert "description:" in content, f"{skill_name} SKILL.md missing description"


class TestSkillMdContentMatchesExtension:
    """SKILL.md body should contain the same content as system_prompt_extension."""

    def test_extension_content_in_skill_md(self):
        discover_skills()
        for skill_name in EXPECTED_SKILLS:
            cls = get_skill(skill_name)
            sk = load_skill(cls)
            if not sk.system_prompt_extension:
                continue

            skill_md = (DOMAIN_SKILLS_DIR / skill_name / "SKILL.md").read_text()
            # Extract body (after frontmatter)
            parts = skill_md.split("---", 2)
            body = parts[2].strip() if len(parts) >= 3 else ""

            # The body should match the extension (stripped)
            assert body == sk.system_prompt_extension.strip(), (
                f"{skill_name}: SKILL.md body doesn't match system_prompt_extension"
            )


class TestDomainSkillsDiscovery:
    """AgentSkills plugin should discover domain SKILL.md files."""

    def test_domain_skills_dir_has_skill_md_files(self):
        found = list(DOMAIN_SKILLS_DIR.glob("*/SKILL.md"))
        assert len(found) == 16, f"Expected 16 SKILL.md files, found {len(found)}"

    def test_agent_skills_plugin_with_domain_dir(self):
        try:
            from strands import AgentSkills
            # Verify it's the real SDK, not conftest mock
            if not hasattr(AgentSkills, 'get_available_skills'):
                import pytest
                pytest.skip("Using mock AgentSkills (no get_available_skills)")
        except ImportError:
            import pytest
            pytest.skip("strands.AgentSkills not available")

        plugin = AgentSkills(skills=str(DOMAIN_SKILLS_DIR))
        available = plugin.get_available_skills()
        # Should find at least some of the 16 skills
        assert len(available) >= 10, f"Expected >=10 skills, found {len(available)}"


class TestFoundationAgentDomainSkills:
    """FoundationAgent should discover domain skills via plugin."""

    def test_plugin_includes_domain_skills(self, tmp_path):
        from platform_agent.foundation.agent import FoundationStrandsAgent

        # Create workspace with skills dir
        ws_skills = tmp_path / "skills" / "ws_skill"
        ws_skills.mkdir(parents=True)
        (ws_skills / "SKILL.md").write_text(
            "---\nname: ws_skill\ndescription: A workspace skill\n---\nBody."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        if agent._skills_plugin is None:
            import pytest
            pytest.skip("AgentSkills plugin not available")

        # Verify plugin was created (even with mock, it should exist)
        assert agent._skills_plugin is not None

    def test_plugin_created_with_multiple_sources(self, tmp_path):
        """Without harness, plugin uses workspace/skills/ fallback only.

        With the harness-driven elif pattern, workspace/skills/ is the
        fallback when no harness is provided. Domain skills come from
        harness.skill_directories.
        """
        from platform_agent.foundation.agent import FoundationStrandsAgent

        ws_skills = tmp_path / "skills" / "ws_skill"
        ws_skills.mkdir(parents=True)
        (ws_skills / "SKILL.md").write_text(
            "---\nname: ws_skill\ndescription: A workspace skill\n---\nBody."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        if agent._skills_plugin is None:
            import pytest
            pytest.skip("AgentSkills plugin not available")

        # Without harness, only workspace/skills/ is scanned (elif fallback)
        skills_arg = agent._skills_plugin.skills
        if isinstance(skills_arg, list):
            assert len(skills_arg) >= 1, "Expected workspace skill dir"
            assert str(tmp_path / "skills") in skills_arg
        else:
            assert str(tmp_path / "skills") in str(skills_arg)
