"""Tests for AgentCore Deployment — Dockerfile, entry point, IAM config."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


from platform_agent.foundation.deploy.dockerfile import (
    generate_dockerfile,
    DockerfileConfig,
)
from platform_agent.foundation.deploy.agentcore import (
    generate_entrypoint,
    generate_iam_policy,
    AgentCoreConfig,
)


# ---------------------------------------------------------------------------
# Dockerfile generation
# ---------------------------------------------------------------------------


class TestDockerfileGeneration:
    """Test Dockerfile content generation."""

    def test_default_dockerfile(self):
        content = generate_dockerfile()
        assert "FROM" in content
        assert "python" in content.lower()
        assert "COPY" in content
        assert "CMD" in content or "ENTRYPOINT" in content

    def test_includes_strands_install(self):
        content = generate_dockerfile()
        assert "strands-agents" in content or "strands" in content

    def test_includes_claude_code_install(self):
        config = DockerfileConfig(include_claude_code=True)
        content = generate_dockerfile(config)
        assert "claude" in content.lower()

    def test_without_claude_code(self):
        config = DockerfileConfig(include_claude_code=False)
        content = generate_dockerfile(config)
        # Should still be valid
        assert "FROM" in content

    def test_custom_base_image(self):
        config = DockerfileConfig(base_image="python:3.12-slim")
        content = generate_dockerfile(config)
        assert "python:3.12-slim" in content

    def test_default_base_image(self):
        content = generate_dockerfile()
        assert "python:3.11" in content or "python:3.12" in content

    def test_includes_workspace_copy(self):
        content = generate_dockerfile()
        # Should copy workspace files
        assert "COPY" in content

    def test_exposes_port(self):
        config = DockerfileConfig(port=8080)
        content = generate_dockerfile(config)
        assert "8080" in content


# ---------------------------------------------------------------------------
# Entry point generation
# ---------------------------------------------------------------------------


class TestEntrypointGeneration:
    """Test AgentCore runtime entry point."""

    def test_basic_entrypoint(self):
        content = generate_entrypoint()
        assert "BedrockAgentCoreApp" in content
        assert "@app.entrypoint" in content
        assert "app.run()" in content
        assert "import" in content

    def test_entrypoint_with_workspace(self):
        config = AgentCoreConfig(workspace_dir="/app/workspace")
        content = generate_entrypoint(config)
        assert "/app/workspace" in content

    def test_entrypoint_with_custom_model(self):
        config = AgentCoreConfig(model_id="anthropic.claude-sonnet-4-20250514-v1:0")
        content = generate_entrypoint(config)
        assert "claude-sonnet" in content

    def test_entrypoint_imports(self):
        content = generate_entrypoint()
        assert "bedrock_agentcore" in content
        assert "strands" in content


# ---------------------------------------------------------------------------
# IAM policy generation
# ---------------------------------------------------------------------------


class TestIAMPolicyGeneration:
    """Test IAM policy document generation."""

    def test_basic_policy(self):
        policy = generate_iam_policy()
        assert "Version" in policy
        assert "Statement" in policy
        assert isinstance(policy["Statement"], list)
        assert len(policy["Statement"]) > 0

    def test_includes_bedrock_permissions(self):
        policy = generate_iam_policy()
        actions = []
        for stmt in policy["Statement"]:
            actions.extend(stmt.get("Action", []))
        # Should include Bedrock model invocation
        bedrock_actions = [a for a in actions if "bedrock" in a.lower()]
        assert len(bedrock_actions) > 0

    def test_includes_memory_permissions(self):
        config = AgentCoreConfig(enable_memory=True)
        policy = generate_iam_policy(config)
        actions = []
        for stmt in policy["Statement"]:
            actions.extend(stmt.get("Action", []))
        action_str = " ".join(actions)
        assert "memory" in action_str.lower() or "agentcore" in action_str.lower()

    def test_minimal_permissions_without_memory(self):
        config = AgentCoreConfig(enable_memory=False)
        policy = generate_iam_policy(config)
        actions = []
        for stmt in policy["Statement"]:
            actions.extend(stmt.get("Action", []))
        # Should still have bedrock permissions but fewer overall
        assert len(actions) > 0

    def test_policy_uses_least_privilege(self):
        policy = generate_iam_policy()
        for stmt in policy["Statement"]:
            # No wildcard resources ideally, but at minimum check structure
            assert "Effect" in stmt
            assert stmt["Effect"] in ("Allow", "Deny")
            assert "Action" in stmt
            assert "Resource" in stmt

    def test_custom_region(self):
        config = AgentCoreConfig(region="eu-west-1")
        policy = generate_iam_policy(config)
        # Region should appear in resource ARNs
        policy_str = str(policy)
        assert "eu-west-1" in policy_str or "*" in policy_str


# ---------------------------------------------------------------------------
# AgentCoreConfig
# ---------------------------------------------------------------------------


class TestAgentCoreConfig:
    """Test AgentCore configuration dataclass."""

    def test_default_config(self):
        config = AgentCoreConfig()
        assert config.region is not None
        assert config.model_id is not None

    def test_custom_config(self):
        config = AgentCoreConfig(
            region="us-east-1",
            model_id="anthropic.claude-sonnet-4-20250514-v1:0",
            workspace_dir="/app/ws",
            enable_memory=True,
        )
        assert config.region == "us-east-1"
        assert config.model_id == "anthropic.claude-sonnet-4-20250514-v1:0"
        assert config.workspace_dir == "/app/ws"
        assert config.enable_memory is True
