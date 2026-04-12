"""Slack integration for Plato agent.

Provides a Lambda-based adapter that connects Slack Bot events to the
Plato FoundationAgent via API Gateway. Supports both channel messages
and direct messages (DMs).

Architecture:
    Slack Bot → API Gateway (HTTP API) → Lambda (async)
      ↓ (3s ack)                          ↓
    Slack gets 200              InvokeAgentRuntime / local agent
                                          ↓
                                Slack chat.postMessage (response)

The async pattern avoids Slack's 3-second timeout and Lambda's 15-min limit
is sufficient since the Lambda only orchestrates — the agent runs on AgentCore.
"""
