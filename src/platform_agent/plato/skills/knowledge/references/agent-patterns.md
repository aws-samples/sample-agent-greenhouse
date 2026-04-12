# Agent Architecture Patterns

Common patterns for building agent applications on AgentCore.

## Table of Contents

- [Tool-Use Agent](#tool-use-agent)
- [ReAct Agent](#react-agent)
- [Multi-Agent Delegation](#multi-agent-delegation)
- [Human-in-the-Loop](#human-in-the-loop)
- [Reflect-Refine (Evaluator-Critic)](#reflect-refine)
- [Pattern Selection Guide](#pattern-selection-guide)

## Tool-Use Agent

Agent with access to external tools (APIs, databases, file systems).

**When to use**: Most common pattern. Agent needs to take actions or
retrieve information beyond its training data.

**Structure**:
```
User request → Agent (LLM)
                  ├── Tool: search_docs()
                  ├── Tool: query_db()
                  └── Tool: send_email()
               → Response
```

**Best practices**:
- Define clear tool descriptions (the LLM uses these to decide when to call)
- Validate all tool inputs
- Handle tool failures gracefully (retry, fallback, or explain)
- Log tool calls for debugging

## ReAct Agent

Reason + Act loop: think about what to do, do it, observe the result, repeat.

**When to use**: Complex tasks requiring multiple steps and reasoning.

**Structure**:
```
Loop:
  1. Thought: "I need to check the Dockerfile..."
  2. Action: Read("Dockerfile")
  3. Observation: "Multi-stage build found..."
  4. Thought: "Now check for secrets..."
  5. Action: Grep("sk-", "*.py")
  ...until done
```

**Best practices**:
- Set max_turns to prevent infinite loops
- Log the thought chain for debugging
- Use structured output for intermediate steps

## Multi-Agent Delegation

Orchestrator agent delegates tasks to specialist agents.

**When to use**: Complex workflows where different skills need different
context, tools, or prompts.

**Structure**:
```
Orchestrator
  ├── Specialist A (domain knowledge + specific tools)
  ├── Specialist B (different domain)
  └── Specialist C (yet another domain)
```

**Plato uses this pattern**: Orchestrator delegates to design_advisor,
code_review, scaffold, and deployment_config specialists.

**Best practices**:
- Each specialist should have a focused system prompt
- Orchestrator should route based on request analysis, not keywords
- Limit the number of specialists (4-6 is usually enough)
- Allow orchestrator to invoke multiple specialists for complex requests

## Human-in-the-Loop

Agent pauses for human approval on critical decisions.

**When to use**: When actions are irreversible, high-stakes, or when
confidence is low.

**Structure**:
```
Agent analyzes → Confidence check
  ├── High confidence → Execute automatically
  └── Low confidence → Present to human
                         ├── Human approves → Execute
                         └── Human modifies → Re-analyze
```

**When to pause**:
- Deploying to production
- Sending external communications
- Modifying infrastructure (IAM, security groups)
- Spending money (provisioning resources)
- Confidence score below threshold

**Implementation**: Use the evaluator's escalation mechanism —
when `session.final_status == "escalated"`, present to human.

## Reflect-Refine

Evaluator-Critic pattern: produce output, evaluate quality, refine if needed.

**When to use**: When output quality matters and single-pass generation
is unreliable.

**Structure**:
```
Specialist produces → Evaluator scores (rubric)
  ├── Score >= threshold → ✅ Approved
  └── Score < threshold → Feedback to specialist
                            → Specialist revises
                            → Re-evaluate (loop)
                            → Max iterations → Escalate
```

**Plato implements this**: See `src/platform_agent/evaluator/`.

**Best practices**:
- Define clear rubrics with weighted criteria
- Set reasonable thresholds (0.7 is a good default)
- Limit iterations (3 is usually enough)
- Track score improvement across iterations
- Escalate if no improvement after max iterations

## Pattern Selection Guide

| Need | Pattern |
|------|---------|
| Simple task + external data | Tool-Use |
| Multi-step reasoning | ReAct |
| Multiple domains/skills | Multi-Agent |
| High-stakes decisions | Human-in-the-Loop |
| Quality-critical output | Reflect-Refine |

**Combine patterns**: Most real agents combine multiple patterns.
For example, Plato uses Multi-Agent + Tool-Use + Reflect-Refine.
