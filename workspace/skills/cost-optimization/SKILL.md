---
name: cost-optimization
description: Analyze and optimize costs for AI agent workloads on AWS — model selection, caching, memory pricing, scaling strategies. Use when the user asks about costs, pricing, or optimization.
---

# Cost Optimization for AI Agents

## Model Selection
- Claude Haiku for simple routing/classification (~10x cheaper than Opus)
- Claude Sonnet for most agent tasks (good balance)
- Claude Opus only for complex reasoning/code generation
- Amazon Nova Lite/Micro for high-volume, simple tasks
- Consider prompt caching for repeated system prompts (up to 90% savings)

## AgentCore Pricing
- Runtime: per-second compute (scale-to-zero = no idle cost)
- Memory: per-event storage + per-retrieval calls
- Browser: per-session charges
- Network: standard EC2 data transfer rates

## Optimization Strategies
- **Prompt engineering**: shorter prompts = fewer tokens = lower cost
- **Lazy skill loading**: only load full SKILL.md when needed (not in system prompt)
- **Memory compaction**: CompactionHook to summarize long conversations
- **Session pooling**: reuse agent instances across invocations
- **Tiered model routing**: use cheap model for triage, expensive for complex tasks
- **Caching**: cache tool results (e.g., API calls) to avoid redundant work

## Memory Cost Control
- STM events: minimize event size (don't store large payloads)
- LTM strategies: 4 strategies × extraction cost per event
- Retrieval: semantic search has per-query cost
- Tip: use explicit save_memory for important facts only, don't over-index

## Monitoring Costs
- CloudWatch metrics for invocation count, duration, token usage
- Set billing alarms for unexpected spikes
- Track per-user usage for chargeback models
