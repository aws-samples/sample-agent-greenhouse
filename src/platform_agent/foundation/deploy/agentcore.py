"""AgentCore runtime configuration and deployment.

Uses the bedrock-agentcore SDK and starter toolkit for deployment.
The proper deployment flow is:
    1. agentcore configure -e entrypoint.py
    2. agentcore deploy

This module generates the configuration and IAM policy.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentCoreConfig:
    """Configuration for AgentCore deployment.

    Args:
        region: AWS region. Default: AWS_REGION env or us-west-2.
        model_id: Bedrock model identifier.
        workspace_dir: Path to workspace directory in the container.
        enable_memory: Whether to enable AgentCore Memory integration.
        enable_claude_code: Whether to enable Claude Code CLI tool.
        memory_strategies: Memory strategies to configure.
    """

    region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-west-2"))
    model_id: str = "global.anthropic.claude-opus-4-6-v1"
    workspace_dir: str = "/app/workspace"
    enable_memory: bool = False
    enable_claude_code: bool = False
    memory_strategies: list[str] = field(default_factory=lambda: ["semantic"])


def generate_entrypoint(config: AgentCoreConfig | None = None) -> str:
    """Generate a Python entry point script for AgentCore runtime.

    Uses BedrockAgentCoreApp with @app.entrypoint decorator,
    which is the correct AgentCore Runtime protocol.

    Args:
        config: AgentCore configuration. Uses defaults if None.

    Returns:
        Python script content as string.
    """
    if config is None:
        config = AgentCoreConfig()

    lines = [
        '"""AgentCore Runtime Entry Point — auto-generated."""',
        "",
        "import os",
        "",
        "from bedrock_agentcore import BedrockAgentCoreApp",
        "from strands import Agent",
        "from strands.models.bedrock import BedrockModel",
        "",
        "from platform_agent.foundation.agent import FoundationAgent",
        "",
        "",
        "# Configuration from environment",
        f'WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "{config.workspace_dir}")',
        f'MODEL_ID = os.environ.get("MODEL_ID", "{config.model_id}")',
        "",
        "# Build the foundation agent",
        "foundation = FoundationAgent(",
        "    workspace_dir=WORKSPACE_DIR,",
        "    model_id=MODEL_ID,",
        f"    enable_claude_code={config.enable_claude_code},",
        ")",
        "",
        "# Build the Strands agent (reused across invocations)",
        "agent = foundation._build_strands_agent()",
        "",
        "# AgentCore Runtime app",
        "app = BedrockAgentCoreApp()",
        "",
        "",
        "@app.entrypoint",
        "def invoke(payload, context=None):",
        '    """Main entry point for AgentCore Runtime."""',
        '    user_message = payload.get("prompt", "Hello! How can I help you today?")',
        "",
        "    # Use session ID from AgentCore runtime for session isolation",
        '    if context and hasattr(context, "session_id"):',
        '        agent.state["session_id"] = context.session_id',
        "",
        "    result = agent(user_message)",
        "",
        "    # Extract text response",
        '    if hasattr(result, "message"):',
        "        content = result.message",
        '        if isinstance(content, dict) and "content" in content:',
        '            text_parts = [b["text"] for b in content["content"] if "text" in b]',
        '            return {"result": "".join(text_parts)}',
        '        return {"result": str(content)}',
        '    return {"result": str(result)}',
        "",
        "",
        'if __name__ == "__main__":',
        "    app.run()",
    ]

    return "\n".join(lines)


def generate_iam_policy(config: AgentCoreConfig | None = None) -> dict[str, Any]:
    """Generate an IAM policy document for AgentCore deployment.

    Args:
        config: AgentCore configuration. Uses defaults if None.

    Returns:
        IAM policy document as dict.
    """
    if config is None:
        config = AgentCoreConfig()

    statements: list[dict[str, Any]] = [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            "Resource": f"arn:aws:bedrock:{config.region}:*:foundation-model/*",
        },
    ]

    if config.enable_memory:
        statements.append({
            "Effect": "Allow",
            "Action": [
                "bedrock-agentcore:CreateEvent",
                "bedrock-agentcore:ListEvents",
                "bedrock-agentcore:RetrieveMemoryRecords",
                "bedrock-agentcore:CreateMemorySession",
                "bedrock-agentcore:GetMemorySession",
            ],
            "Resource": f"arn:aws:bedrock-agentcore:{config.region}:*:memory/*",
        })

    return {
        "Version": "2012-10-17",
        "Statement": statements,
    }


def generate_deploy_commands(config: AgentCoreConfig | None = None) -> str:
    """Generate the CLI commands to deploy to AgentCore.

    Args:
        config: AgentCore configuration. Uses defaults if None.

    Returns:
        Shell commands as string.
    """
    if config is None:
        config = AgentCoreConfig()

    lines = [
        "#!/bin/bash",
        "# Deploy Foundation Agent to AgentCore Runtime",
        "",
        "# Step 1: Install dependencies",
        "pip install bedrock-agentcore strands-agents bedrock-agentcore-starter-toolkit",
        "",
        "# Step 2: Configure the agent",
        f"agentcore configure -e entrypoint.py -r {config.region}",
        "",
        "# Step 3: Deploy to AgentCore Runtime",
        "agentcore deploy",
        "",
        "# Step 4: Test the deployed agent",
        'agentcore invoke \'{"prompt": "Hello, tell me about yourself"}\'',
        "",
        "# Step 5: Check deployment status",
        "agentcore status",
    ]

    if config.enable_memory:
        lines.extend([
            "",
            "# Step 6: Setup memory strategies (idempotent)",
            "# Requires AGENTCORE_MEMORY_ID env var or pass --memory-id",
            "python3 scripts/setup_memory.py --memory-id $AGENTCORE_MEMORY_ID",
        ])

    return "\n".join(lines)
