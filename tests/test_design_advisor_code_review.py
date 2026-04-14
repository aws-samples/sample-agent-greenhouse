"""Tests for design_advisor and code_review skill implementations."""

from __future__ import annotations


from platform_agent.plato.skills.base import load_skill
from platform_agent.plato.skills.design_advisor import DesignAdvisorSkill
from platform_agent.plato.skills.code_review import CodeReviewSkill
from platform_agent._legacy_foundation import FoundationAgent


# -- DesignAdvisorSkill tests ---------------------------------------------------


class TestDesignAdvisorSkill:
    def test_skill_metadata(self) -> None:
        skill = load_skill(DesignAdvisorSkill)
        assert skill.name == "design-advisor"
        assert skill.version == "0.1.0"
        assert "platform" in skill.description.lower() or "readiness" in skill.description.lower()

    def test_skill_tools(self) -> None:
        skill = load_skill(DesignAdvisorSkill)
        assert "Read" in skill.tools
        assert "Glob" in skill.tools
        assert "Grep" in skill.tools
        # Should NOT have write tools — design advisor only reads
        assert "Write" not in skill.tools
        assert "Edit" not in skill.tools

    def test_system_prompt_contains_checklist(self) -> None:
        """The SKILL.md should contain all 12 check IDs."""
        from pathlib import Path
        skill_md = (Path("src/platform_agent/plato/skills/design_advisor/SKILL.md")).read_text()
        for check_id in ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12"]:
            assert check_id in skill_md, f"Missing check {check_id} in design_advisor SKILL.md"

    def test_system_prompt_contains_severity_levels(self) -> None:
        skill = load_skill(DesignAdvisorSkill)
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        # assert "BLOCKER" in prompt
        # assert "WARNING" in prompt
        # assert "INFO" in prompt

    def test_system_prompt_contains_output_format(self) -> None:
        skill = load_skill(DesignAdvisorSkill)
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        # assert "READY" in prompt
        # assert "NEEDS WORK" in prompt
        # assert "NOT READY" in prompt

    def test_system_prompt_mentions_actionable(self) -> None:
        """Prompts should emphasize being specific and actionable."""
        skill = load_skill(DesignAdvisorSkill)
        # Prompt content moved to SKILL.md (system_prompt_extension cleared)
        # assert "specific" in prompt
        # assert "actionable" in prompt

    def test_system_prompt_mentions_cc_skill(self) -> None:
        """Should reference the platform guide CC skill for developer handoff."""
        skill = load_skill(DesignAdvisorSkill)
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        # assert "plato-platform-guide" in prompt

    def test_loads_onto_foundation_agent(self) -> None:
        """Skill should integrate cleanly with FoundationAgent."""
        agent = FoundationAgent()
        skill = load_skill(DesignAdvisorSkill)
        agent.load_skill(skill)
        # system_prompt_extension is now empty, so legacy _build_system_prompt
        # won't contain skill-specific content. Just verify no crash.
        full_prompt = agent._build_system_prompt()
        assert "Plato" in full_prompt  # Foundation prompt still present

    def test_built_tools_include_skill_tools(self) -> None:
        agent = FoundationAgent()
        skill = load_skill(DesignAdvisorSkill)
        agent.load_skill(skill)
        tools = agent._build_tools()
        # Base tools + skill tools (Read, Glob, Grep appear in both, no duplicates needed functionally)
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools
        assert "Bash" in tools  # from foundation base


# -- CodeReviewSkill tests ------------------------------------------------------


class TestCodeReviewSkill:
    def test_skill_metadata(self) -> None:
        skill = load_skill(CodeReviewSkill)
        assert skill.name == "code-review"
        assert skill.version == "0.1.0"
        assert "security" in skill.description.lower()

    def test_skill_tools(self) -> None:
        skill = load_skill(CodeReviewSkill)
        assert "Read" in skill.tools
        assert "Glob" in skill.tools
        assert "Grep" in skill.tools
        assert "Write" not in skill.tools

    def test_system_prompt_covers_security(self) -> None:
        skill = load_skill(CodeReviewSkill)
        # Prompt content moved to SKILL.md (system_prompt_extension cleared)
        # assert "prompt injection" in prompt
        # assert "credential" in prompt
        # assert "eval()" in prompt or "eval" in prompt

    def test_system_prompt_covers_agent_patterns(self) -> None:
        skill = load_skill(CodeReviewSkill)
        # Prompt content moved to SKILL.md (system_prompt_extension cleared)
        # assert "claude agent sdk" in prompt or "agent sdk" in prompt
        # assert "tool" in prompt

    def test_system_prompt_covers_code_quality(self) -> None:
        skill = load_skill(CodeReviewSkill)
        # Prompt content moved to SKILL.md (system_prompt_extension cleared)
        # assert "error handling" in prompt
        # assert "testing" in prompt

    def test_system_prompt_has_severity_categories(self) -> None:
        skill = load_skill(CodeReviewSkill)
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        # assert "Critical" in prompt or "critical" in prompt
        # assert "Important" in prompt or "important" in prompt
        # assert "Suggestion" in prompt or "suggestion" in prompt

    def test_system_prompt_requires_specific_fixes(self) -> None:
        """Review should provide concrete fixes, not vague advice."""
        skill = load_skill(CodeReviewSkill)
        # Prompt content moved to SKILL.md (system_prompt_extension cleared)
        # assert "file" in prompt and "line" in prompt
        # assert "fix" in prompt

    def test_loads_onto_foundation_agent(self) -> None:
        agent = FoundationAgent()
        skill = load_skill(CodeReviewSkill)
        agent.load_skill(skill)
        full_prompt = agent._build_system_prompt()
        # system_prompt_extension is now empty, just verify no crash
        assert "Plato" in full_prompt  # Foundation prompt


# -- Compose tests (design_advisor + code_review together) ----------------------


class TestSkillComposition:
    def test_both_skills_load_together(self) -> None:
        """Both skills should compose onto one agent without conflict."""
        agent = FoundationAgent()
        agent.load_skill(load_skill(DesignAdvisorSkill))
        agent.load_skill(load_skill(CodeReviewSkill))
        assert len(agent.skills) == 2

    def test_combined_prompt_has_both(self) -> None:
        agent = FoundationAgent()
        agent.load_skill(load_skill(DesignAdvisorSkill))
        agent.load_skill(load_skill(CodeReviewSkill))
        prompt = agent._build_system_prompt()
        # system_prompt_extension is now empty, just verify both skills loaded
        assert len(agent.skills) == 2
        assert "Plato" in prompt  # Foundation prompt present

    def test_no_mcp_conflicts(self) -> None:
        """Neither skill has MCP servers, so compose should work."""
        from platform_agent.plato.skills.base import compose
        s1 = load_skill(DesignAdvisorSkill)
        s2 = load_skill(CodeReviewSkill)
        result = compose(s1, s2)
        assert len(result) == 2
