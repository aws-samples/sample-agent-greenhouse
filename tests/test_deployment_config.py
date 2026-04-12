"""Tests for the deployment_config skill pack — registration, prompt, templates."""

from __future__ import annotations

import json
import sys

import pytest
import yaml

from platform_agent.plato.skills.base import SkillPack, load_skill
from platform_agent.plato.skills import _registry
from platform_agent._legacy_foundation import FoundationAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the skill registry before each test."""
    saved = dict(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


@pytest.fixture()
def skill_cls():
    """Import and return the DeploymentConfigSkill class (triggers register_skill)."""
    mod_key = "platform_agent.plato.skills.deployment_config"
    if mod_key in sys.modules:
        del sys.modules[mod_key]
    from platform_agent.plato.skills.deployment_config import DeploymentConfigSkill

    return DeploymentConfigSkill


@pytest.fixture()
def templates():
    """Import and return the deployment templates dict."""
    from platform_agent.plato.skills.deployment_config.templates import DEPLOYMENT_TEMPLATES

    return DEPLOYMENT_TEMPLATES


@pytest.fixture()
def template_descriptions():
    """Import and return template descriptions."""
    from platform_agent.plato.skills.deployment_config.templates import TEMPLATE_DESCRIPTIONS

    return TEMPLATE_DESCRIPTIONS


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_correctly(self, skill_cls) -> None:
        """DeploymentConfigSkill should be in the registry after import."""
        assert "deployment_config" in _registry
        assert _registry["deployment_config"] is skill_cls

    def test_is_skillpack_subclass(self, skill_cls) -> None:
        assert issubclass(skill_cls, SkillPack)

    def test_loads_via_load_skill(self, skill_cls) -> None:
        skill = load_skill(skill_cls)
        assert skill.name == "deployment_config"
        assert isinstance(skill, SkillPack)

    def test_skill_metadata(self, skill_cls) -> None:
        skill = load_skill(skill_cls)
        assert skill.version == "0.1.0"
        assert "AgentCore" in skill.description


# ---------------------------------------------------------------------------
# System prompt tests
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_prompt_covers_iam(self, skill_cls) -> None:
        """System prompt should discuss IAM policies and least-privilege."""
        skill = load_skill(skill_cls)
        prompt = skill.system_prompt_extension
        assert "IAM" in prompt
        assert "least-privilege" in prompt.lower() or "least privilege" in prompt.lower()

    def test_prompt_covers_docker(self, skill_cls) -> None:
        """System prompt should discuss Dockerfile best practices."""
        skill = load_skill(skill_cls)
        prompt = skill.system_prompt_extension
        assert "Dockerfile" in prompt
        assert "HEALTHCHECK" in prompt
        assert "non-root" in prompt.lower() or "non root" in prompt.lower()
        assert "multi-stage" in prompt.lower() or "multi stage" in prompt.lower()

    def test_prompt_covers_cdk(self, skill_cls) -> None:
        """System prompt should discuss CDK stack generation."""
        skill = load_skill(skill_cls)
        prompt = skill.system_prompt_extension
        assert "CDK" in prompt
        assert "ECR" in prompt

    def test_prompt_covers_runtime(self, skill_cls) -> None:
        """System prompt should discuss runtime configuration."""
        skill = load_skill(skill_cls)
        prompt = skill.system_prompt_extension
        assert "runtime" in prompt.lower()
        assert "scaling" in prompt.lower() or "Scaling" in prompt

    def test_prompt_covers_buildspec(self, skill_cls) -> None:
        """System prompt should discuss CI/CD buildspec."""
        skill = load_skill(skill_cls)
        prompt = skill.system_prompt_extension
        assert "buildspec" in prompt.lower()
        assert "CodeBuild" in prompt

    def test_prompt_covers_env_vars(self, skill_cls) -> None:
        """System prompt should discuss environment variables."""
        skill = load_skill(skill_cls)
        prompt = skill.system_prompt_extension
        assert "env" in prompt.lower()
        assert "AGENT_MODEL" in prompt or "environment" in prompt.lower()

    def test_prompt_references_design_advisor(self, skill_cls) -> None:
        """System prompt should reference the Design Advisor readiness check."""
        skill = load_skill(skill_cls)
        prompt = skill.system_prompt_extension
        assert "Design Advisor" in prompt
        assert "readiness" in prompt.lower() or "BLOCKER" in prompt

    def test_prompt_mentions_placeholder_markers(self, skill_cls) -> None:
        """System prompt should document placeholder markers."""
        skill = load_skill(skill_cls)
        prompt = skill.system_prompt_extension
        assert "{project_name}" in prompt
        assert "{aws_region}" in prompt
        assert "{aws_account_id}" in prompt


# ---------------------------------------------------------------------------
# Tool configuration tests
# ---------------------------------------------------------------------------


class TestTools:
    def test_has_write_tools(self, skill_cls) -> None:
        """Deployment config skill needs write access to generate files."""
        skill = load_skill(skill_cls)
        assert "Write" in skill.tools
        assert "Edit" in skill.tools
        assert "Bash" in skill.tools

    def test_has_read_tools(self, skill_cls) -> None:
        """Skill also needs read tools to inspect existing project."""
        skill = load_skill(skill_cls)
        assert "Read" in skill.tools
        assert "Glob" in skill.tools
        assert "Grep" in skill.tools


# ---------------------------------------------------------------------------
# Template validation tests
# ---------------------------------------------------------------------------


class TestTemplates:
    def test_all_templates_exist(self, templates) -> None:
        """All expected deployment templates should be defined."""
        expected = [
            "iam-policy.json",
            "buildspec.yml",
            "cdk/app_stack.py",
            "runtime-config.yaml",
            ".env.template",
            "Dockerfile",
        ]
        for name in expected:
            assert name in templates, f"Missing template: {name}"

    def test_template_descriptions_match(self, templates, template_descriptions) -> None:
        """Every template should have a corresponding description."""
        for name in templates:
            assert name in template_descriptions, f"Missing description for: {name}"

    def test_iam_policy_is_valid_json(self, templates) -> None:
        """IAM policy template should parse as valid JSON after substitution."""
        rendered = templates["iam-policy.json"].format(
            project_name="test_agent",
            aws_account_id="123456789012",
            aws_region="us-east-1",
            s3_bucket_name="test-bucket",
        )
        policy = json.loads(rendered)
        assert policy["Version"] == "2012-10-17"
        assert isinstance(policy["Statement"], list)
        assert len(policy["Statement"]) > 0

    def test_iam_policy_least_privilege(self, templates) -> None:
        """IAM policy should not use wildcard actions."""
        rendered = templates["iam-policy.json"].format(
            project_name="test_agent",
            aws_account_id="123456789012",
            aws_region="us-east-1",
            s3_bucket_name="test-bucket",
        )
        policy = json.loads(rendered)
        for statement in policy["Statement"]:
            actions = statement.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            for action in actions:
                assert action != "*", (
                    f"Wildcard action found in statement {statement.get('Sid', 'unknown')}"
                )

    def test_iam_policy_has_scoped_resources(self, templates) -> None:
        """IAM policy resources should use specific ARNs, not bare wildcards."""
        rendered = templates["iam-policy.json"].format(
            project_name="test_agent",
            aws_account_id="123456789012",
            aws_region="us-east-1",
            s3_bucket_name="test-bucket",
        )
        policy = json.loads(rendered)
        for statement in policy["Statement"]:
            resources = statement.get("Resource", [])
            if isinstance(resources, str):
                resources = [resources]
            for resource in resources:
                assert resource != "*", (
                    f"Wildcard resource in statement {statement.get('Sid', 'unknown')}"
                )

    def test_iam_policy_has_bedrock_permissions(self, templates) -> None:
        """IAM policy should include bedrock:InvokeModel."""
        rendered = templates["iam-policy.json"].format(
            project_name="test_agent",
            aws_account_id="123456789012",
            aws_region="us-east-1",
            s3_bucket_name="test-bucket",
        )
        policy = json.loads(rendered)
        all_actions = []
        for statement in policy["Statement"]:
            actions = statement.get("Action", [])
            if isinstance(actions, str):
                actions = [actions]
            all_actions.extend(actions)
        assert "bedrock:InvokeModel" in all_actions

    def test_buildspec_is_valid_yaml(self, templates) -> None:
        """buildspec.yml template should parse as valid YAML after substitution."""
        rendered = templates["buildspec.yml"].format(
            project_name="test_agent",
            aws_account_id="123456789012",
            aws_region="us-east-1",
            ecr_repo_name="test-agent-repo",
        )
        spec = yaml.safe_load(rendered)
        assert spec["version"] == 0.2
        assert "phases" in spec
        assert "pre_build" in spec["phases"]
        assert "build" in spec["phases"]
        assert "post_build" in spec["phases"]

    def test_runtime_config_is_valid_yaml(self, templates) -> None:
        """runtime-config.yaml should parse as valid YAML after substitution."""
        rendered = templates["runtime-config.yaml"].format(
            project_name="test_agent",
            aws_account_id="123456789012",
            aws_region="us-east-1",
            ecr_repo_name="test-agent-repo",
        )
        config = yaml.safe_load(rendered)
        assert "runtime" in config
        assert "container" in config
        assert "resources" in config
        assert "scaling" in config
        assert config["container"]["health_check"]["path"] == "/health"

    def test_dockerfile_has_healthcheck(self, templates) -> None:
        """Dockerfile template should include HEALTHCHECK directive."""
        assert "HEALTHCHECK" in templates["Dockerfile"]

    def test_dockerfile_has_non_root_user(self, templates) -> None:
        """Dockerfile template should create and use a non-root user."""
        dockerfile = templates["Dockerfile"]
        assert "useradd" in dockerfile or "adduser" in dockerfile
        assert "USER agent" in dockerfile

    def test_dockerfile_has_multi_stage_build(self, templates) -> None:
        """Dockerfile template should use multi-stage build."""
        dockerfile = templates["Dockerfile"]
        assert "AS builder" in dockerfile
        assert "COPY --from=builder" in dockerfile

    def test_templates_have_placeholder_markers(self, templates) -> None:
        """All templates should use substitution placeholders."""
        for name, content in templates.items():
            assert "{project_name}" in content or "{aws_" in content, (
                f"Template {name} has no placeholder markers"
            )

    def test_env_template_has_documentation(self, templates) -> None:
        """.env.template should have comments explaining each variable."""
        env = templates[".env.template"]
        assert "# " in env  # Has comments
        assert "AGENT_MODEL" in env
        assert "AGENT_PORT" in env
        assert "AWS_DEFAULT_REGION" in env
        assert "NEVER commit" in env


# ---------------------------------------------------------------------------
# Foundation Agent integration tests
# ---------------------------------------------------------------------------


class TestFoundationAgentIntegration:
    def test_loads_onto_foundation_agent(self, skill_cls) -> None:
        """Skill should integrate cleanly with FoundationAgent."""
        agent = FoundationAgent()
        skill = load_skill(skill_cls)
        agent.load_skill(skill)
        full_prompt = agent._build_system_prompt()
        # Foundation prompt
        assert "Plato" in full_prompt
        # Skill prompt content
        assert "IAM" in full_prompt
        assert "Dockerfile" in full_prompt
        assert "CDK" in full_prompt

    def test_built_tools_include_skill_tools(self, skill_cls) -> None:
        """Agent tools should include both base and skill tools."""
        agent = FoundationAgent()
        skill = load_skill(skill_cls)
        agent.load_skill(skill)
        tools = agent._build_tools()
        assert "Write" in tools
        assert "Edit" in tools
        assert "Bash" in tools
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools

    def test_composes_with_design_advisor(self, skill_cls) -> None:
        """Should compose alongside design_advisor without conflicts."""
        from platform_agent.plato.skills.base import compose

        mod_key = "platform_agent.plato.skills.design_advisor"
        if mod_key in sys.modules:
            del sys.modules[mod_key]
        from platform_agent.plato.skills.design_advisor import DesignAdvisorSkill

        dc_skill = load_skill(skill_cls)
        da_skill = load_skill(DesignAdvisorSkill)
        result = compose(dc_skill, da_skill)
        assert len(result) == 2
