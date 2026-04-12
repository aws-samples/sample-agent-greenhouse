---
name: design-advisor
description: Provide architecture and design advice for AI agent systems. Use when the user asks about system design, architecture patterns, or tradeoffs.
---

# Design Advisor

## When to Use
- Architecture design discussions
- Tradeoff analysis (cost vs latency vs complexity)
- Technology selection (which AWS service, which framework)
- Multi-agent system design

## Approach
1. Understand the requirements and constraints
2. Propose 2-3 options with clear tradeoffs
3. Give a recommendation with justification
4. Include rough cost/complexity estimates
5. Flag risks and mitigation strategies

## Key Patterns
- Agent + Tools pattern (single agent with tool access)
- Router + Specialist pattern (dispatcher + domain agents)
- Pipeline pattern (sequential agent chain)
- Supervisor pattern (orchestrator + workers)
