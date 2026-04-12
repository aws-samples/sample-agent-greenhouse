# Design Advisor Skill — Design Document

## Purpose

The `design_advisor` skill pack augments the Foundation Agent with platform-specific
architecture review capabilities. When loaded, the agent becomes a "Design Advisor"
that can assess whether a developer's agent application is ready for deployment to
the platform (Amazon Bedrock AgentCore).

**Core question this skill answers:** "Is this agent app designed in a way that will
work well on our platform?"

## Developer Pain Points Addressed

1. **"What does the platform require?"** — Developers shouldn't need to read 50 pages
   of docs to know what the platform expects. The Design Advisor tells them.
2. **"Is my app compatible?"** — Instead of discovering issues at deployment time,
   catch them during design/development.
3. **"What should I change?"** — Not just "you have a problem" but "here's how to fix it".

## Platform Readiness Checklist

The Design Advisor evaluates agent apps against this checklist. Each item has a
severity level:

| # | Check | Severity | Description |
|---|-------|----------|-------------|
| C1 | Containerizable | 🔴 BLOCKER | App must be containerizable (Dockerfile or can generate one) |
| C2 | No hardcoded secrets | 🔴 BLOCKER | No API keys, passwords, tokens in source code |
| C3 | Environment-based config | 🟡 WARNING | Config via env vars, not hardcoded values |
| C4 | Health check endpoint | 🟡 WARNING | HTTP `/health` or `/healthz` endpoint exists |
| C5 | Stateless design | 🟡 WARNING | No local filesystem for persistent state |
| C6 | Graceful shutdown | 🟢 INFO | Handles SIGTERM for zero-downtime deploys |
| C7 | Logging to stdout | 🟢 INFO | Logs to stdout/stderr (not local files) for CloudWatch |
| C8 | Error handling | 🟡 WARNING | Proper try/catch, no bare exceptions, meaningful error messages |
| C9 | Dependency management | 🟡 WARNING | requirements.txt / pyproject.toml with pinned versions |
| C10 | Agent framework compatibility | 🟢 INFO | Uses supported framework (Claude Agent SDK, Strands, LangGraph, etc.) |
| C11 | MCP tool safety | 🟡 WARNING | Tools don't execute arbitrary user code without sandboxing |
| C12 | Memory pattern | 🟢 INFO | If stateful, uses appropriate memory pattern (AgentCore Memory compatible) |

## Scoring

Each check produces:
- **Status**: PASS / FAIL / WARNING / SKIP (if not applicable)
- **Details**: What was found
- **Recommendation**: How to fix (if FAIL or WARNING)

Overall readiness score:
- **READY** ✅ — 0 blockers, ≤2 warnings
- **NEEDS WORK** ⚠️ — 0 blockers, >2 warnings  
- **NOT READY** ❌ — 1+ blockers

## System Prompt Extension

```
You are the Design Advisor for the Plato platform. Your role is to help developers
ensure their agent applications are ready for deployment to Amazon Bedrock AgentCore.

When reviewing an agent application, systematically check:

BLOCKER checks (must pass):
- C1: Is the app containerizable? Look for Dockerfile. If missing, can one be generated?
- C2: Are there hardcoded secrets? Search for API keys, passwords, tokens in source files.
  Check: env vars, .env files committed, config files with credentials.

WARNING checks (should fix):
- C3: Is configuration via environment variables? Or hardcoded in code?
- C4: Is there a health check endpoint? Look for /health, /healthz, or similar.
- C5: Does the app write to local filesystem for persistent state? 
  (Temp files for processing are OK; storing session data locally is not.)
- C8: Is error handling robust? Look for bare except, missing error handling in tool calls.
- C9: Are dependencies properly managed? Check for requirements.txt or pyproject.toml
  with pinned versions.
- C11: Do MCP tools validate inputs? Can they execute arbitrary code?

INFO checks (nice to have):
- C6: Does the app handle SIGTERM? Look for signal handlers or graceful shutdown logic.
- C7: Does logging go to stdout/stderr? Or to local files?
- C10: What agent framework is used? Is it supported on AgentCore?
- C12: If the app needs persistent state, does it use a pattern compatible with
  AgentCore Memory (or external state store)?

For each check, provide:
1. Status: PASS / FAIL / WARNING / SKIP
2. Evidence: What you found in the code
3. Recommendation: How to fix (if needed)

End with an overall readiness assessment: READY / NEEDS WORK / NOT READY.
Always be specific and actionable — don't just say "fix error handling", 
say exactly which file and what to change.
```

## MCP Tools (Future)

For MVP, the skill uses only built-in tools (Read, Glob, Grep). Future MCP tools:

| Tool | Purpose |
|------|---------|
| `scan_secrets` | Automated secret detection (regex + entropy analysis) |
| `check_dockerfile` | Validate Dockerfile best practices |
| `analyze_dependencies` | Check for known vulnerabilities in dependencies |

## Evaluation Criteria

For our internal eval framework (testing skill quality):

**Test cases** (5 minimum for MVP):
1. **Good app** — Should score READY, find 0 blockers
2. **Hardcoded secrets app** — Should find C2 blocker
3. **No Dockerfile app** — Should find C1 blocker + suggest one
4. **Stateful local storage app** — Should find C5 warning
5. **Mixed issues app** — Should find 1 blocker + multiple warnings, rate as NOT READY

**Metrics:**
- Precision: % of reported issues that are real issues
- Recall: % of planted issues that are detected
- Actionability: Are recommendations specific enough to act on?

## Integration with CC Skill

When the Design Advisor finds issues, it should reference the unified CC skill
(`plato-platform-guide.md`) so the developer can install it into their Claude Code:

> "I found 3 issues. Install our platform guide skill in your Claude Code to
> automatically follow these best practices: `plato skill install platform-guide`"
