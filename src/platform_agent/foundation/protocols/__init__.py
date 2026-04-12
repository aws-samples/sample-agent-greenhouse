"""Protocol support for agent communication and tool access.

Provides abstractions for:
- A2A (Agent-to-Agent) protocol for inter-agent communication
- MCP (Model Context Protocol) for tool discovery and access
- AgentCore Gateway integration for protocol routing
"""

from platform_agent.foundation.protocols.a2a import (
    A2AClient,
    A2AMessage,
    A2AServer,
    AgentCard,
)
from platform_agent.foundation.protocols.mcp import (
    MCPClient,
    MCPServer,
    MCPTool,
    ToolResult,
)

__all__ = [
    "A2AClient",
    "A2AMessage",
    "A2AServer",
    "AgentCard",
    "MCPClient",
    "MCPServer",
    "MCPTool",
    "ToolResult",
]
