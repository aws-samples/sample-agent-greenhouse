---
name: debug
description: Help diagnose and fix agent issues — runtime errors, memory problems, IAM failures, integration bugs. Use when something is broken.
---

# Debug

## When to Use
- Agent deployment failures
- Runtime errors (500s, timeouts, OOM)
- Memory not working (events not persisting, LTM empty)
- IAM permission errors
- Slack integration issues

## Debugging Approach
1. **Reproduce** — What exact steps trigger the issue?
2. **Logs** — Check CloudWatch logs for the AgentCore runtime
3. **Isolate** — Is it agent code, infrastructure, or configuration?
4. **Fix** — Apply the smallest change that fixes the issue
5. **Verify** — Confirm the fix works and didn't break anything else

## Common Issues
- `ResourceNotFoundException` for memory → memory resource was deleted, recreate it
- Agent stuck in "Deploying" → check CloudWatch build logs for errors
- Lambda timeout → Worker Lambda needs 15min timeout for long tasks
- Session isolation failures → verify session ID format and length
