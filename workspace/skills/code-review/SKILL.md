---
name: code-review
description: Review code for correctness, security, best practices, and maintainability. Use when the user shares code or asks for a code review.
---

# Code Review

## When to Use
- User shares code and asks for review
- User asks about code quality or best practices
- PR review requests

## Review Checklist
1. **Correctness** — Does the code do what it's supposed to?
2. **Security** — SQL injection, credential leaks, SSRF, over-permissive IAM?
3. **Error handling** — Are errors caught, logged, and handled gracefully?
4. **Testing** — Are there tests? Are edge cases covered?
5. **Maintainability** — Clear naming, reasonable complexity, good structure?
6. **Performance** — Obvious inefficiencies? N+1 queries? Unnecessary allocations?

## Output Format
- List issues by severity: 🔴 Blocker / 🟡 Warning / 🟢 Suggestion
- Reference specific lines
- Provide concrete fix suggestions
