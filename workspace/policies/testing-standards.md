# Testing Standards — v1
<!-- plato-policy-version: testing-v1 -->

## Applies To: Tier 1 and Tier 2

These standards ensure agents are tested thoroughly before deployment.

## Required Test Types

### Unit Tests
- Test every `@tool` function independently with mocked dependencies
- Test hook middleware (before/after invoke callbacks)
- Test memory operations (create event, retrieve records, namespace isolation)
- Test input validation and error handling paths
- **Minimum coverage: 70%** (Tier 1: 80%)

### Integration Tests
- Test agent end-to-end with real model but mocked external services
- Test memory round-trip: write event → strategy extraction → retrieve record
- Test session isolation: verify User A cannot access User B's data
- Test the full invocation path (API Gateway → Lambda → AgentCore → response)

### Agent Evaluation
- Define golden test cases: specific inputs with expected behavior/output
- Test categories:
  - **Helpfulness**: Does the agent answer the question correctly?
  - **Safety**: Does the agent refuse harmful/out-of-scope requests?
  - **Memory**: Does the agent save and recall context correctly?
  - **Tool use**: Does the agent pick the right tool and use it correctly?
- Maintain a regression test suite of past failures

## Test Infrastructure

- Use pytest as the test framework
- Use fixtures for common mock setups (memory backend, model, tools)
- Store test fixtures in `tests/fixtures/` directory
- Use `@pytest.mark.integration` to tag integration tests (separate from unit)

## Pre-Merge Requirements

- All unit tests must pass
- No decrease in test coverage
- Integration tests must pass for changes touching:
  - Memory system
  - Tool implementations
  - Hook middleware
  - Invocation pipeline

## Pre-Deploy Requirements

- Run `scripts/smoke-test.sh` after every deployment
- Verify Slack (or other channel) end-to-end manually
- Never declare deployment successful based on partial verification

## Mocking Guidelines

```python
# Mock AgentCore Memory
from unittest.mock import patch, MagicMock

@patch("platform_agent.memory.AgentCoreMemory")
def test_save_memory(mock_memory):
    mock_memory.return_value.add_assistant_message.return_value = "evt-123"
    # Test save_memory tool

# Mock external APIs
@patch("requests.get")
def test_tool_with_api(mock_get):
    mock_get.return_value.json.return_value = {"status": "ok"}
    # Test tool that calls external API
```
