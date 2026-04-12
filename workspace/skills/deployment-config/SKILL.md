---
name: deployment-config
description: Help with deploying AI agents to AWS — AgentCore, Lambda, ECS, CDK/CloudFormation. Use when the user asks about deployment, configuration, or infrastructure.
---

# Deployment Configuration

## When to Use
- Deploying agents to AgentCore Runtime
- Setting up Lambda + API Gateway for Slack integration
- CDK/CloudFormation infrastructure
- IAM policy and role configuration

## AgentCore Deployment Checklist
1. Install dependencies: `pip install bedrock-agentcore strands-agents`
2. Configure: `agentcore configure -e entrypoint.py`
3. Deploy: `agentcore deploy`
4. Setup memory strategies: `python3 scripts/setup_memory.py`
5. Test: `agentcore invoke '{"prompt": "Hello"}'`

## Common Gotchas
- Session ID must be >= 33 characters
- Memory resource needs strategies configured separately
- `execution_role_auto_create: false` if you don't have `iam:CreateRole`
- Orphaned memory resources need manual cleanup with `aws bedrock-agent delete-memory`
