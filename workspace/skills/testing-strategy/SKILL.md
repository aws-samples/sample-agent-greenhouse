---
name: testing-strategy
description: Help design and implement test strategies for AI agents — unit tests, integration tests, agent evaluation, memory testing, tool mocking. Use when the user asks about testing agents.
---

# Testing Strategy for AI Agents

## Unit Testing
- Test each @tool function independently with mocked dependencies
- Test hook middleware (before/after invoke callbacks)
- Test memory backend operations (create_event, retrieve_records)
- Test session ID generation and namespace construction
- Use pytest fixtures for memory/tool mocking

## Integration Testing
- Test agent end-to-end with real model but mocked tools
- Test memory round-trip: write → extract → retrieve
- Test Slack handler → AgentCore invoke → response pipeline
- Test session isolation (two users, verify no data leak)
- Test cold start and lazy initialization

## Agent Evaluation
- Define golden test cases: input → expected behavior/output
- Test for: helpfulness, accuracy, safety, latency
- Evaluate memory usage: does the agent save/recall correctly?
- Test skill loading: does the agent pick the right skill?
- Test guardrails: does the agent refuse harmful requests?

## Memory Testing
- Verify STM events created for each conversation turn
- Verify LTM extraction after strategy processing
- Test namespace isolation (actor A can't see actor B)
- Test memory context loading on session resume
- Test explicit save_memory / recall_memory tools

## Mocking Patterns
```python
# Mock AgentCore Memory
@patch("platform_agent.memory.AgentCoreMemory")
def test_memory_save(mock_memory):
    mock_memory.add_assistant_message.return_value = "evt-123"
    # ... test save_memory tool

# Mock Bedrock model for agent tests
@patch("strands.models.bedrock.BedrockModel")
def test_agent_response(mock_model):
    mock_model.return_value = mock_streaming_response("Hello!")
    # ... test agent invocation
```
