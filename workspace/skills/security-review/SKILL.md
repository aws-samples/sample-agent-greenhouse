---
name: security-review
description: Review AI agent security — IAM policies, secret management, input validation, prompt injection defense, memory isolation. Use when the user asks about security, hardening, or threat modeling for agent systems.
---

# Security Review

## IAM Best Practices for Agents
- Least-privilege execution roles: only the permissions the agent actually uses
- Separate roles for deploy-time vs runtime
- Use `execution_role_auto_create: false` + manual role for production
- Never pass `iam:*` or `bedrock:*` — scope to specific actions and resources
- Use ABAC (attribute-based access control) for multi-tenant isolation

## Secret Management
- Never store credentials in source code, configs, or SKILL.md files
- Use AWS Secrets Manager or SSM Parameter Store (SecureString)
- For AgentCore: use Identity service for OAuth token management
- Rotate secrets regularly; use short-lived credentials where possible

## Prompt Injection Defense
- Validate all user inputs before passing to agent
- Use GuardrailsHook for input/output validation
- Never let user input modify system prompts directly
- Use ToolPolicyHook to restrict which tools are available
- Log all tool invocations via AuditHook for forensics

## Memory Isolation
- Use server-side namespace isolation (`/actors/{actorId}/`)
- Never rely on client-side filtering for user separation
- S3 prefix isolation is NOT real isolation (same IAM role)
- AgentCore Memory namespace is API-level (server enforced)

## Agent-Specific Threats
- Tool abuse: agent calling destructive APIs without confirmation
- Memory poisoning: injecting false facts into LTM
- Session hijacking: using another user's session_id
- Exfiltration: agent leaking data through tool outputs
