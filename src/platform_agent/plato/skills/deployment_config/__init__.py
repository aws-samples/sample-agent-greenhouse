"""Deployment Config skill pack — deployment configuration generation for AgentCore.

Generates Dockerfiles, IAM policies, CDK stacks, buildspec files, runtime
configs, and environment variable templates for deploying agent applications
to Amazon Bedrock AgentCore.

Reference: docs/design/deployment-config-skill.md
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

# DEPLOYMENT_CONFIG_PROMPT removed — SKILL.md is the sole prompt source.
class DeploymentConfigSkill(SkillPack):
    """Deployment configuration generation for Amazon Bedrock AgentCore.

    Augments the Foundation Agent with the ability to generate production-ready
    deployment artifacts: Dockerfile, IAM policy, CDK stack, buildspec,
    runtime config, and env var template.

    Usage:
        agent = FoundationAgent()
        agent.load_skill(load_skill(DeploymentConfigSkill))
        result = await agent.run("Generate deployment configs for ./my-agent")
    """

    name: str = "deployment-config"
    description: str = (
        "Generates deployment configurations for Amazon Bedrock AgentCore. "
        "Produces Dockerfiles, IAM policies, CDK stacks, buildspec files, "
        "runtime configs, and environment variable templates following AWS "
        "security best practices and least-privilege principles."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]  # type: ignore[assignment]

    def configure(self) -> None:
        """No additional configuration needed for MVP.

        Future: could load project-specific overrides from a config file,
        or add MCP tools for AWS resource validation.
        """
        pass


register_skill("deployment-config", DeploymentConfigSkill)
