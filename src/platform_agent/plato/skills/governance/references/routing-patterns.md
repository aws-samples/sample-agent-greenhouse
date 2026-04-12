# Message Routing Patterns

## Table of Contents
- [Direct Routing](#direct-routing)
- [Capability-Based Matching](#capability-based-matching)
- [Broadcast](#broadcast)
- [Escalation Chains](#escalation-chains)
- [Circuit Breaker](#circuit-breaker)

## Direct Routing

Send a message to a specific agent by ID.

```python
message = Message(
    source_agent="agent-a",
    target_agent="agent-b",
    intent="review_code",
    payload={"file": "src/main.py"},
    tenant_id="tenant-1",
)
router.send(message)
```

Use direct routing when:
- You know the target agent
- The task requires a specific agent's expertise
- You need guaranteed delivery to one agent

## Capability-Based Matching

Use TaskDispatcher to find agents with matching capabilities.

```python
task = task_manager.create_task(
    tenant_id="tenant-1",
    intent="review_architecture",
    required_capabilities=["design_review", "aws_architecture"],
)
dispatcher.dispatch(task)
```

The dispatcher:
1. Finds agents in READY state with all required capabilities
2. Scores candidates by cumulative confidence
3. Assigns to the highest-scoring agent

## Broadcast

Send to all agents by targeting "*".

```python
message = Message(
    source_agent="control-plane",
    target_agent="*",
    intent="config_update",
    payload={"key": "max_retries", "value": 5},
    tenant_id="tenant-1",
)
```

Use broadcast for:
- Configuration updates
- Announcements
- Health check pings

## Escalation Chains

Implement escalation by retrying with broader capabilities.

```python
# First attempt: specific agent
task = task_manager.create_task(
    tenant_id="tenant-1",
    intent="resolve_incident",
    required_capabilities=["incident_response"],
    priority=10,
)
dispatcher.dispatch(task)

# If no match, retry with fewer requirements
if task.status == TaskStatus.PENDING:
    task.required_capabilities = []  # broadcast
    task.priority = 20  # escalate priority
```

## Circuit Breaker

Prevent runaway agent conversations.

```python
circuit_breaker = CircuitBreaker(threshold=50, window_seconds=300)
router.add_middleware(circuit_breaker)
```

Configuration:
- `threshold`: Maximum messages between a pair in the window (default: 50)
- `window_seconds`: Time window for counting (default: 300s)

When the circuit breaks:
- Messages between the pair are dropped
- The pair is logged for investigation
- Reset with `circuit_breaker.reset(source, target)`
