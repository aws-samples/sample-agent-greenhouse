"""Integration tests — FoundationAgent + Control Plane Skills.

Validates that control plane skills compose correctly onto the
FoundationAgent and that the full agent system works end-to-end.
"""

from __future__ import annotations

import pytest

from platform_agent._legacy_foundation import FoundationAgent
from platform_agent.plato.skills.base import load_skill, compose


# ── Skill Loading Tests ──


class TestSkillComposition:
    """Test that control plane skills load onto FoundationAgent correctly."""

    def _load_cp_skills(self):
        """Load all 4 control plane skills."""
        from platform_agent.plato.skills.governance import GovernanceSkill
        from platform_agent.plato.skills.observability import ObservabilitySkill
        from platform_agent.plato.skills.fleet_ops import FleetOpsSkill
        from platform_agent.plato.skills.onboarding import OnboardingSkill

        return [
            load_skill(GovernanceSkill),
            load_skill(ObservabilitySkill),
            load_skill(FleetOpsSkill),
            load_skill(OnboardingSkill),
        ]

    def test_load_all_cp_skills(self):
        """All 4 control plane skills load without error."""
        skills = self._load_cp_skills()
        assert len(skills) == 4
        names = {s.name for s in skills}
        assert "governance" in names
        assert "observability" in names
        assert "fleet_ops" in names
        assert "onboarding" in names

    def test_compose_no_conflicts(self):
        """Skills compose without MCP server conflicts."""
        skills = self._load_cp_skills()
        composed = compose(*skills)
        assert len(composed) == 4

    def test_agent_system_prompt_includes_skills(self):
        """FoundationAgent system prompt includes all skill extensions."""
        agent = FoundationAgent()
        skills = self._load_cp_skills()
        for s in skills:
            agent.load_skill(s)

        prompt = agent._build_system_prompt()

        # Foundation prompt present
        assert "Platform Agent" in prompt or "Plato" in prompt

        # Each skill's system prompt extension should appear
        for skill in skills:
            if skill.system_prompt_extension:
                # At least the skill name section should be present
                assert skill.name in prompt.lower() or skill.system_prompt_extension[:50] in prompt

    def test_agent_tools_composed(self):
        """Agent tool list includes base tools + skill tools."""
        agent = FoundationAgent()
        skills = self._load_cp_skills()
        for s in skills:
            agent.load_skill(s)

        tools = agent._build_tools()

        # Base tools always present
        assert "Read" in tools
        assert "Write" in tools
        assert "Bash" in tools

        # No duplicates
        assert len(tools) == len(set(tools))

    def test_agent_runtime_detection(self):
        """Agent correctly detects runtime mode."""
        agent = FoundationAgent()
        # Without claude-agent-sdk installed, should be bedrock
        assert agent.runtime in ("bedrock", "claude-agent-sdk")

    def test_agent_with_skills_and_memory(self):
        """Agent can be created with skills and memory store."""
        from platform_agent.memory import create_memory_store

        agent = FoundationAgent(memory_store=create_memory_store(backend="local"))
        skills = self._load_cp_skills()
        for s in skills:
            agent.load_skill(s)

        prompt = agent._build_system_prompt()
        assert "Memory" in prompt  # Memory section added

    def test_skill_descriptions_present(self):
        """Each skill has a description for discoverability."""
        skills = self._load_cp_skills()
        for s in skills:
            assert s.description, f"Skill {s.name} missing description"

    def test_skill_versions(self):
        """Each skill has a version."""
        skills = self._load_cp_skills()
        for s in skills:
            assert s.version, f"Skill {s.name} missing version"


# ── Control Plane Module Integration ──


class TestControlPlaneModules:
    """Test that control plane modules work together correctly."""

    def test_full_stack_initialization(self):
        """All control plane modules can be initialized together."""
        from platform_agent.plato.control_plane.registry import AgentRegistry
        from platform_agent.plato.control_plane.policy_engine import PlatformPolicyEngine
        from platform_agent.plato.control_plane.task_manager import TaskManager, TaskDispatcher
        from platform_agent.plato.control_plane.message_router import MessageRouter
        from platform_agent.plato.control_plane.lifecycle import (
            ColdStartProtocol,
            HeartbeatManager,
            GracefulShutdown,
        )
        from platform_agent.plato.control_plane.audit import AuditStore
        from platform_agent.foundation.guardrails import PolicyStore

        registry = AgentRegistry()
        policy_store = PolicyStore()
        policy_engine = PlatformPolicyEngine(policy_store)
        task_manager = TaskManager()
        TaskDispatcher(task_manager, registry)
        MessageRouter()
        audit = AuditStore()
        ColdStartProtocol(registry, policy_engine, audit)
        HeartbeatManager(registry, audit_store=audit)
        GracefulShutdown(registry, task_manager, audit)

        assert registry.agent_count == 0
        assert len(task_manager.list_tasks()) == 0

    def test_skills_reference_docs_exist(self):
        """Each skill's reference docs exist on disk."""
        import os

        skills_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "platform_agent",
            "skills",
        )
        cp_skills = ["governance", "observability", "fleet_ops", "onboarding"]

        for skill_name in cp_skills:
            skill_dir = os.path.join(skills_dir, skill_name)
            assert os.path.isdir(skill_dir), f"Skill dir {skill_name} not found"
            init_file = os.path.join(skill_dir, "__init__.py")
            assert os.path.isfile(init_file), f"Skill {skill_name} missing __init__.py"

    def test_health_endpoint(self):
        """Health check server starts and responds."""
        import json
        import urllib.request

        from platform_agent.health import start_health_server

        server = start_health_server(port=0)  # Random port
        port = server.server_address[1]

        try:
            url = f"http://localhost:{port}/health"
            resp = urllib.request.urlopen(url, timeout=5)
            data = json.loads(resp.read())
            assert data["status"] == "healthy"
            assert data["service"] == "platform-agent"
        finally:
            server.shutdown()

    def test_health_endpoint_404(self):
        """Health server returns 404 for unknown paths."""
        import urllib.error
        import urllib.request

        from platform_agent.health import start_health_server

        server = start_health_server(port=0)
        port = server.server_address[1]

        try:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://localhost:{port}/nope", timeout=5)
            assert exc_info.value.code == 404
        finally:
            server.shutdown()


# ── Docker/Build Validation ──


class TestBuildValidation:
    """Validate the project builds and imports correctly."""

    def test_all_control_plane_imports(self):
        """All control plane modules import without error."""
        from platform_agent.plato.control_plane import registry
        from platform_agent.plato.control_plane import policy_engine
        from platform_agent.plato.control_plane import task_manager
        from platform_agent.plato.control_plane import message_router
        from platform_agent.plato.control_plane import lifecycle
        from platform_agent.plato.control_plane import audit

        assert registry.AgentRegistry
        assert policy_engine.PlatformPolicyEngine
        assert task_manager.TaskManager
        assert message_router.MessageRouter
        assert lifecycle.ColdStartProtocol
        assert audit.AuditStore

    def test_dynamodb_store_imports(self):
        """DynamoDB store imports without error."""
        from platform_agent.plato.control_plane.dynamodb_store import (
            DynamoDBAgentRegistry,
            DynamoDBTaskManager,
            DynamoDBAuditStore,
            create_table,
        )
        assert DynamoDBAgentRegistry
        assert DynamoDBTaskManager
        assert DynamoDBAuditStore
        assert create_table

    def test_cli_entry_point(self):
        """CLI entry point is importable."""
        from platform_agent.cli import cli
        assert cli

    def test_dockerfile_exists(self):
        """Dockerfile exists in project root."""
        import os

        dockerfile = os.path.join(
            os.path.dirname(__file__), "..", "Dockerfile"
        )
        assert os.path.isfile(dockerfile)

    def test_dockerfile_valid_syntax(self):
        """Dockerfile has required directives."""
        import os

        dockerfile = os.path.join(
            os.path.dirname(__file__), "..", "Dockerfile"
        )
        with open(dockerfile) as f:
            content = f.read()

        assert "FROM" in content
        assert "WORKDIR" in content
        assert "COPY" in content
        assert "EXPOSE" in content
        assert "HEALTHCHECK" in content
