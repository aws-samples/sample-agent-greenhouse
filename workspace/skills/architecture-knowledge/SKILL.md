---
name: architecture-knowledge
description: Deep knowledge about AI agent architectures, AWS services, memory patterns, and best practices. Use as reference when answering technical questions.
---

# Architecture Knowledge

## AgentCore Runtime
- Managed container runtime for AI agents
- Supports Strands SDK, LangChain, and custom frameworks
- Request-driven model (invoke_agent_runtime API)
- Session-based with automatic scaling (including scale-to-zero)
- Memory integration (STM events + LTM strategy extraction)

## Memory Architecture (Plato Design)
- **Platform files** (SOUL.md, IDENTITY.md) → baked into container image
- **User memory** → AgentCore Memory with namespace isolation
- **STM**: Conversation events per session (list_events / create_event)
- **LTM**: Extracted records from 4 strategies (Semantic, UserPreference, Summary, Episodic)
- **Namespace isolation**: `/actors/{actorId}/` for server-side filtering
- **Explicit memory**: save_memory / recall_memory tools for high-value facts

## Slack Integration Pattern
- API Gateway → Lambda (3s ack) → SQS → Worker Lambda (15min) → AgentCore
- Session ID: thread-based for shared context, channel+user for non-thread
- Actor ID: Slack user ID for memory isolation
