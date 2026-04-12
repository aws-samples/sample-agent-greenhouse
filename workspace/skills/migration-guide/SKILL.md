---
name: migration-guide
description: Help teams migrate AI agents between frameworks and runtimes — Bedrock Agents to AgentCore, LangChain to Strands, monolith to multi-agent. Use when the user asks about migration, porting, or switching frameworks.
---

# Migration Guide

## Common Migration Paths

### Bedrock Agents → AgentCore + Strands
- Extract action groups → Strands @tool functions
- Convert knowledge bases → AgentCore Memory + RAG
- Migrate session state → AgentCore Memory STM
- Replace agent instructions → Soul System (SOUL.md)
- Update IAM: bedrock:InvokeAgent → bedrock-agentcore:InvokeAgentRuntime

### LangChain/LangGraph → Strands
- Replace chain/graph with Agent + tools
- Convert LangChain tools → @tool decorated functions
- Replace ConversationBufferMemory → AgentCore Memory
- StateGraph nodes → hook middleware (before/after invoke)

### Lambda Monolith → AgentCore Runtime
- Extract agent logic from Lambda handler
- Create Dockerfile or direct code upload
- Configure .bedrock_agentcore.yaml
- Set up API Gateway → Lambda → AgentCore invoke pattern
- Add session management (AgentCore handles isolation)

## Key Considerations
- **Session ID design**: AgentCore requires ≥33 chars, UUID format recommended
- **Memory migration**: Export existing conversation data, replay via create_event
- **IAM**: AgentCore uses different service principals and actions
- **Cold start**: AgentCore has 30s init budget; use lazy initialization
- **Timeout**: AgentCore sessions can run longer than Lambda 15-min limit
