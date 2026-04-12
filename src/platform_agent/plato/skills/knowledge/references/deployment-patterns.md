# Deployment Patterns for AgentCore

Architecture patterns for deploying agent applications to Amazon Bedrock AgentCore.

## Table of Contents

- [Single Agent](#single-agent)
- [Multi-Agent Orchestration](#multi-agent-orchestration)
- [Sidecar Pattern](#sidecar-pattern)
- [Event-Driven Agent](#event-driven-agent)
- [Choosing a Pattern](#choosing-a-pattern)

## Single Agent

The simplest deployment: one agent, one container, one endpoint.

**When to use**: Simple conversational agents, single-purpose tools,
prototypes and MVPs.

**Architecture**:
```
Client → API Gateway → AgentCore Container
                          ├── Agent runtime
                          ├── Tool definitions
                          └── Health check
```

**Deployment artifacts**:
- Dockerfile (single stage)
- IAM role (bedrock:InvokeModel + tool-specific permissions)
- Runtime config (CPU/memory/scaling)

**Scaling**: AgentCore handles auto-scaling based on request volume.

## Multi-Agent Orchestration

Multiple specialized agents coordinated by an orchestrator.

**When to use**: Complex workflows spanning multiple domains,
when different agents need different tools/permissions.

**Architecture**:
```
Client → Orchestrator Agent
            ├── Design Advisor Agent
            ├── Code Review Agent
            ├── Scaffold Agent
            └── Deploy Config Agent
```

**Key decisions**:
- **Same container vs separate**: Start with same container (lower latency),
  split when agents need different scaling or permissions
- **Communication**: Agent-as-tool pattern (synchronous) vs A2A protocol (async)
- **Shared state**: Use AgentCore Memory for cross-agent state

**Plato itself uses this pattern**: Orchestrator + 4 specialist skills.

## Sidecar Pattern

Main agent + helper containers in the same task.

**When to use**: When the agent needs local services (vector DB, cache,
file processing) that don't justify a separate deployment.

**Architecture**:
```
AgentCore Task
  ├── Main Container (agent)
  ├── Sidecar: Vector DB (Qdrant/ChromaDB)
  └── Sidecar: Redis (cache)
```

**Trade-offs**:
- ✅ Low latency between containers
- ✅ Shared lifecycle (scale together)
- ❌ Resource coupling (can't scale independently)
- ❌ More complex Dockerfile/task definition

## Event-Driven Agent

Agent triggered by events rather than HTTP requests.

**When to use**: Batch processing, scheduled analysis, webhook handlers,
monitoring agents that react to alerts.

**Architecture**:
```
EventBridge/SQS → Lambda → AgentCore (async invoke)
                              └── Agent processes event
                              └── Results → DynamoDB/S3
```

**Key considerations**:
- Set appropriate timeouts (agent processing can be slow)
- Use dead letter queues for failed invocations
- Idempotency: agent should handle duplicate events

## Choosing a Pattern

| Factor | Single | Multi-Agent | Sidecar | Event-Driven |
|--------|--------|-------------|---------|---------------|
| Complexity | Low | High | Medium | Medium |
| Latency | Low | Medium | Low | High (async) |
| Cost | Low | Higher | Medium | Pay-per-event |
| Scalability | Good | Best | Coupled | Best |
| Use case | Simple | Complex workflows | Local services | Batch/scheduled |

**Start simple**: Begin with Single Agent, evolve to Multi-Agent as
complexity grows. Premature multi-agent architectures add overhead
without benefit.
