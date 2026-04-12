# Compliance Requirements — v1
<!-- plato-policy-version: compliance-v1 -->

## Applies To: Tier 1 Only

These requirements apply to agents handling sensitive data (PII, financial,
health). They ensure regulatory compliance and audit readiness.

## Audit Logging

- Log every tool invocation with: timestamp, actor_id, tool name, input summary, output summary
- Use AuditHook to capture tool calls automatically
- Store audit logs in a tamper-resistant location (CloudWatch Logs with retention policy)
- Retain audit logs for minimum 12 months (configurable per regulation)
- Include session_id and actor_id in all log entries for traceability

## PII Handling

- Classify all data fields by sensitivity level (public, internal, confidential, restricted)
- PII must be masked or tokenized before storing in agent memory
- Never include raw PII in system prompts or tool call logs
- Implement data minimization: only collect PII that is strictly necessary
- Provide a mechanism for PII deletion upon user request (right to erasure)
- Document all PII data flows in the project's data flow diagram

## Human-in-the-Loop

- Define actions that require human approval before execution
- Implement approval workflows for high-risk operations:
  - Financial transactions above configurable threshold
  - Account modifications (deletion, permission changes)
  - External communications (emails, notifications to customers)
- Use AgentCore Policy service (Cedar policies) when available
- Log all approval decisions (approved/denied, by whom, timestamp)

## Data Retention

- Define retention periods for all data types:
  - Conversation events (STM): 30 days default
  - Long-term memory records (LTM): project-specific, maximum 2 years
  - Audit logs: 12 months minimum
- Implement automated cleanup for expired data
- Document retention policy in project README

## Access Control

- Implement role-based access control (RBAC) for agent administration
- Separate admin operations (deploy, configure) from user operations (chat, query)
- Use AgentCore Identity for OAuth token management when accessing third-party services
- Implement rate limiting per user to prevent abuse
- Log failed authentication/authorization attempts

## Incident Response

- Define escalation paths for agent errors that affect customers
- Implement automated alerts for:
  - Error rate exceeding threshold (>5% of invocations)
  - Latency exceeding SLA (>30 seconds for interactive agents)
  - Unauthorized access attempts
  - Memory isolation violations
- Document rollback procedures for each deployment
