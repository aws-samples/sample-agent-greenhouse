# Security Standards — v1
<!-- plato-policy-version: security-v1 -->

## Applies To: All Tiers

These security requirements apply to every agent built on this platform,
regardless of data sensitivity or deployment target.

## Credential Management

- **NEVER** hardcode API keys, tokens, or passwords in source code or config files
- Use AWS Secrets Manager or SSM Parameter Store (SecureString) for all secrets
- Use IAM roles with temporary credentials instead of long-lived access keys
- Rotate all credentials on a defined schedule (maximum 90 days)

## IAM Policies

- Follow least-privilege principle: only grant permissions the agent actually uses
- Use separate IAM roles for deployment vs runtime execution
- Scope resource ARNs specifically — avoid `Resource: "*"` in production
- Use ABAC (attribute-based access control) for multi-tenant data isolation
- Document all IAM permissions with inline comments explaining why each is needed

## Input Validation

- Validate and sanitize all user inputs before processing
- Implement input length limits appropriate to the use case
- Reject inputs containing known injection patterns when possible
- Never pass raw user input directly into system prompts without escaping

## Prompt Injection Defense

- Use structured prompt templates with clear delimiters between system and user content
- Implement GuardrailsHook for automated input/output validation
- Use ToolPolicyHook to restrict available tools based on context
- Log all tool invocations via AuditHook for forensic analysis
- Test against common injection patterns before deployment

## Network Security

- Use VPC connectivity for agents accessing internal resources
- Enable TLS for all external API calls
- Restrict outbound network access to required endpoints only

## Error Handling

- Never expose internal error details, stack traces, or system information to users
- Log errors with full context for debugging, but return sanitized messages
- Implement circuit breakers for external service calls
- Define graceful degradation behavior when tools or services are unavailable

## Dependency Management

- Pin all dependency versions in requirements.txt / package.json
- Regularly scan dependencies for known vulnerabilities
- Use only trusted, well-maintained packages from official repositories
