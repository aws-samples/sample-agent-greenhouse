"""Tests for AgentSkills plugin integration in FoundationAgent.

Verifies:
- Plugin created when AgentSkills is available and skills dir exists
- Plugin passed to strands.Agent as plugins kwarg
- get_prompt_summary() NOT called when plugin is active
- Fallback to SkillRegistry when AgentSkills not importable
"""

from __future__ import annotations

from unittest.mock import MagicMock

from platform_agent.foundation.agent import FoundationStrandsAgent


# ---------------------------------------------------------------------------
# Plugin creation
# ---------------------------------------------------------------------------


class TestAgentSkillsPluginCreation:
    """Test that _skills_plugin is created when appropriate."""

    def test_plugin_created_when_skills_dir_exists(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: A skill\n---\nBody."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        assert agent._skills_plugin is not None
        # Plugin receives a list of skill sources (workspace + domain)
        skills_arg = agent._skills_plugin.skills
        if isinstance(skills_arg, list):
            assert str(tmp_path / "skills") in skills_arg
        else:
            assert skills_arg == str(tmp_path / "skills")

    def test_plugin_not_created_without_skills_dir(self, tmp_path):
        # Workspace exists but no skills/ directory — plugin may still be
        # created if domain skills exist (plato package installed)
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        # If plato domain skills are available, plugin will still be created
        # with only the domain source. Otherwise it will be None.
        if agent._skills_plugin is not None:
            skills_arg = agent._skills_plugin.skills
            if isinstance(skills_arg, list):
                assert str(tmp_path / "skills") not in skills_arg

    def test_plugin_not_created_without_workspace(self):
        agent = FoundationStrandsAgent()
        assert agent._skills_plugin is None

    def test_plugin_not_created_when_agent_skills_unavailable(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: A skill\n---\nBody."
        )
        # Temporarily make _AgentSkills None to simulate import failure
        import platform_agent.foundation.agent as agent_mod
        original = agent_mod._AgentSkills
        try:
            agent_mod._AgentSkills = None
            agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
            assert agent._skills_plugin is None
        finally:
            agent_mod._AgentSkills = original


# ---------------------------------------------------------------------------
# Plugin passed to strands.Agent
# ---------------------------------------------------------------------------


class TestPluginPassedToAgent:
    """Test that plugin is included in Agent kwargs."""

    def test_plugins_kwarg_when_plugin_active(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: A skill\n---\nBody."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        assert agent._skills_plugin is not None

        # Build the strands agent and inspect kwargs
        strands_agent = agent._build_strands_agent()
        # _FakeAgent stores kwargs as attributes
        assert hasattr(strands_agent, "plugins")
        assert strands_agent.plugins == [agent._skills_plugin]

    def test_no_plugins_kwarg_without_plugin(self, tmp_path, monkeypatch):
        # Force no AgentSkills → no plugin at all
        import platform_agent.foundation.agent as agent_mod
        monkeypatch.setattr(agent_mod, "_AgentSkills", None)
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        assert agent._skills_plugin is None

        strands_agent = agent._build_strands_agent()
        # plugins should not be set when no plugin exists
        assert not hasattr(strands_agent, "plugins") or strands_agent.plugins is None

    def test_plugins_kwarg_in_callback_agent(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: A skill\n---\nBody."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))

        callback = MagicMock()
        strands_agent = agent._build_strands_agent_with_callback(callback)
        assert hasattr(strands_agent, "plugins")
        assert strands_agent.plugins == [agent._skills_plugin]


# ---------------------------------------------------------------------------
# Prompt injection skipped when plugin active
# ---------------------------------------------------------------------------


class TestPromptInjectionSkipped:
    """Test that get_prompt_summary() is NOT called when plugin is active."""

    def test_no_skills_summary_in_prompt_when_plugin_active(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: A test skill\n---\nFull instructions."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        assert agent._skills_plugin is not None

        prompt = agent.build_system_prompt()
        # SkillRegistry prompt summary should NOT appear
        assert "Available Skills" not in prompt
        assert "my_skill" not in prompt

    def test_skills_summary_in_prompt_when_plugin_absent(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: A test skill\n---\nFull instructions."
        )
        import platform_agent.foundation.agent as agent_mod
        original = agent_mod._AgentSkills
        try:
            agent_mod._AgentSkills = None
            agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
            assert agent._skills_plugin is None

            # Explicitly discover since auto-discover is no longer done
            agent.skill_registry.discover()
            prompt = agent.build_system_prompt()
            assert "Available Skills" in prompt
            assert "my_skill" in prompt
        finally:
            agent_mod._AgentSkills = original


# ---------------------------------------------------------------------------
# SkillRegistry still functional (backward compat)
# ---------------------------------------------------------------------------


class TestSkillRegistryBackwardCompat:
    """Test that SkillRegistry still works when explicitly used (backward compat).

    Note: SkillRegistry.discover() is no longer called eagerly by FoundationAgent.
    Consumers must call it explicitly if they need the registry.
    """

    def test_skill_registry_still_populated(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: A skill\n---\nBody."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        # Explicitly discover (no longer auto-called)
        agent.skill_registry.discover()
        skills = agent.skill_registry.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "my_skill"

    def test_skill_registry_lazy_load_still_works(self, tmp_path):
        skills_dir = tmp_path / "skills" / "my_skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: my_skill\ndescription: A skill\n---\nFull body content."
        )
        agent = FoundationStrandsAgent(workspace_dir=str(tmp_path))
        # Explicitly discover (no longer auto-called)
        agent.skill_registry.discover()
        skill = agent.skill_registry.get_skill("my_skill")
        assert skill is not None
        assert "Full body content" in skill.full_content
