## Summary

<!-- Brief description of changes -->

## Type of Change

- [ ] New feature
- [ ] Bug fix
- [ ] Refactor (no functional change)
- [ ] Configuration change
- [ ] Documentation

## Policy Compliance Checklist

### Security (All Tiers)
- [ ] No hardcoded credentials, API keys, or tokens
- [ ] All user inputs validated and sanitized
- [ ] Error messages do not expose internal details
- [ ] Dependencies pinned to specific versions

### Architecture (Tier 1-2)
- [ ] Tools use `@tool` decorator with proper types and docs
- [ ] Hook middleware used for cross-cutting concerns (not inline)
- [ ] Memory uses namespace isolation (`/actors/{actorId}/`)
- [ ] Configuration via environment variables (no hardcoded values)

### Compliance (Tier 1 Only)
- [ ] PII is masked before storing in memory
- [ ] Audit logging enabled for all tool invocations
- [ ] Human approval workflow enforced for high-risk operations
- [ ] Investment advice disclaimer in place (if applicable)

### Testing
- [ ] Unit tests added/updated for changed code
- [ ] Test coverage not decreased
- [ ] Integration tests pass
- [ ] Agent evaluation tests pass (if applicable)

## Related Issues

<!-- Closes #123 -->

## Screenshots / Test Output

<!-- Paste relevant test output or screenshots -->
