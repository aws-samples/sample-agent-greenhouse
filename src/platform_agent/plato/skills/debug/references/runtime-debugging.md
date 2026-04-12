# Runtime Debugging Guide

## Table of Contents
- [SDK Exceptions](#sdk-exceptions)
- [Tool Execution Failures](#tool-execution-failures)
- [Conversation Loop Errors](#conversation-loop-errors)
- [Timeout Handling](#timeout-handling)
- [Model Invocation Errors](#model-invocation-errors)
- [Async/Await Issues](#asyncawait-issues)

---

## SDK Exceptions

### Symptom: ClaudeAgentError during query

**Diagnosis:**
```python
import traceback
try:
    result = await agent.run(prompt)
except Exception as e:
    print(f"Type: {type(e).__name__}")
    print(f"Message: {e}")
    traceback.print_exc()
```

**Common errors:**
1. `ValidationException` — Invalid model ID or malformed request
2. `ThrottlingException` — Rate limit exceeded
3. `ModelTimeoutException` — Model took too long to respond
4. `ServiceException` — Internal service error

**Fixes:**
- Validate model ID: `anthropic.claude-sonnet-4-20250514`
- Implement exponential backoff for throttling
- Set appropriate timeout values
- Add retry logic for transient errors

### Retry pattern:
```python
import asyncio
from random import uniform

async def run_with_retry(agent, prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await agent.run(prompt)
        except ThrottlingException:
            wait = (2 ** attempt) + uniform(0, 1)
            await asyncio.sleep(wait)
    raise RuntimeError(f"Failed after {max_retries} retries")
```

---

## Tool Execution Failures

### Symptom: Tool returns error or unexpected result

**Diagnosis:**
```python
# Add logging to tool execution
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("platform_agent")
```

**Common causes:**
1. Tool not in allowed_tools list
2. File path doesn't exist (Read/Write tools)
3. Bash command returns non-zero exit code
4. Tool output exceeds size limit

**Fixes:**
- Verify tool is in `FoundationAgent._base_tools` or skill's `tools` list
- Use absolute paths or set correct `cwd`
- Handle non-zero exit codes in Bash tool
- Truncate large outputs before returning

### Debugging tool registration:
```python
agent = FoundationAgent()
agent.load_skill(my_skill)
print("Available tools:", agent._build_tools())
```

---

## Conversation Loop Errors

### Symptom: Agent loops endlessly or exceeds max turns

**Diagnosis:**
```python
# Check max_turns setting
agent = FoundationAgent(max_turns=50)  # Default

# Add turn counter logging
turn = 0
async for message in agent.stream(prompt):
    turn += 1
    print(f"Turn {turn}: {message.type}")
    if turn > 100:
        print("WARNING: Excessive turns detected")
        break
```

**Common causes:**
1. Agent keeps calling the same tool in a loop
2. Tool output triggers repeated re-evaluation
3. System prompt creates ambiguous completion criteria
4. max_turns set too high without guardrails

**Fixes:**
- Set reasonable `max_turns` (10-50 for most use cases)
- Add explicit completion criteria in system prompt
- Implement tool call deduplication
- Add a "stop and summarize" instruction after N tool calls

---

## Timeout Handling

### Symptom: Request times out before completion

**Diagnosis:**
```bash
# Check AgentCore timeout settings
aws bedrock-agent get-agent --agent-id <id> \
  --query 'agent.idleSessionTTLInSeconds'

# Check CloudWatch for duration metrics
aws cloudwatch get-metric-statistics \
  --namespace AgentCore \
  --metric-name InvocationDuration \
  --dimensions Name=AgentId,Value=<agent-id> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average,Maximum
```

**Common causes:**
1. Complex multi-tool tasks exceed timeout
2. External API calls within tools are slow
3. Large file processing
4. Model thinking time on complex prompts

**Fixes:**
- Break complex tasks into subtasks
- Add timeout to external API calls within tools
- Use streaming for long-running operations
- Increase session timeout if needed

---

## Model Invocation Errors

### Symptom: ModelNotReadyException or ModelNotFoundException

**Diagnosis:**
```bash
# Verify model access
aws bedrock list-foundation-models \
  --query 'modelSummaries[?modelId==`anthropic.claude-sonnet-4-20250514`]'

# Check model access in your account
aws bedrock get-foundation-model-availability \
  --model-id anthropic.claude-sonnet-4-20250514
```

**Fixes:**
- Request model access through the Bedrock console
- Verify model ID spelling (common typo source)
- Check region availability (not all models in all regions)
- Use `us-east-1` or `us-west-2` for broadest model availability

---

## Async/Await Issues

### Symptom: RuntimeWarning about unawaited coroutine

**Common mistakes:**
```python
# WRONG: Missing await
result = agent.run(prompt)  # Returns coroutine, not result

# RIGHT: With await
result = await agent.run(prompt)

# WRONG: Mixing sync and async
def handle_request():  # sync function
    result = await agent.run(prompt)  # Can't await in sync

# RIGHT: Use asyncio.run or async function
async def handle_request():
    result = await agent.run(prompt)
```

### Symptom: Event loop is already running

**Fix:** Use `nest_asyncio` for Jupyter/notebook environments:
```python
import nest_asyncio
nest_asyncio.apply()
```

### Symptom: Task was destroyed but it is pending

**Fix:** Properly clean up async tasks:
```python
async def cleanup(tasks):
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
```
