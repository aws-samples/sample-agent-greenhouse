"""MCP (Model Context Protocol) implementation for tool access.

Provides structured tool discovery and execution following the MCP
specification. Agents can discover tools, validate inputs, and execute
them through a standardized interface.

Key concepts:
- MCPTool: Definition of a tool with input/output schemas
- ToolResult: Structured result from tool execution
- MCPServer: Hosts and serves tools
- MCPClient: Discovers and invokes tools on servers
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class ToolStatus(Enum):
    """Status of a tool execution."""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class MCPTool:
    """Definition of an MCP tool.

    Describes a tool's interface including its input/output schemas,
    used for discovery and validation.
    """

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPTool:
        """Deserialize tool definition."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        """Validate input against schema.

        Returns list of validation errors (empty if valid).
        Simple required-field checking; full JSON Schema validation
        can be added when jsonschema is available.
        """
        errors: list[str] = []
        required = self.input_schema.get("required", [])
        for field_name in required:
            if field_name not in input_data:
                errors.append(f"Missing required field: {field_name}")
        return errors


@dataclass
class ToolResult:
    """Result from executing an MCP tool."""

    tool_name: str
    status: ToolStatus
    output: Any = None
    error: str = ""
    execution_time_ms: float = 0.0
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        """Serialize result."""
        return {
            "tool_name": self.tool_name,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "request_id": self.request_id,
        }

    @property
    def is_success(self) -> bool:
        """Check if tool execution was successful."""
        return self.status == ToolStatus.SUCCESS


# Type alias for tool handler functions
ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class MCPServer:
    """MCP tool server that hosts and serves tools.

    Agents can register tools with handlers, and clients can discover
    and invoke them.

    Usage:
        server = MCPServer("plato-tools")
        server.register_tool(read_tool, read_handler)
        result = await server.execute("Read", {"path": "file.py"})
    """

    def __init__(self, server_id: str, name: str = "", description: str = "") -> None:
        self._server_id = server_id
        self._name = name or server_id
        self._description = description
        self._tools: dict[str, MCPTool] = {}
        self._handlers: dict[str, ToolHandler] = {}

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def name(self) -> str:
        return self._name

    def register_tool(self, tool: MCPTool, handler: ToolHandler) -> None:
        """Register a tool with its execution handler.

        Args:
            tool: Tool definition.
            handler: Async function that executes the tool.
        """
        self._tools[tool.name] = tool
        self._handlers[tool.name] = handler
        logger.debug("Registered MCP tool: %s", tool.name)

    def list_tools(self) -> list[MCPTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_tool(self, name: str) -> MCPTool | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    async def execute(self, tool_name: str, input_data: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with given input.

        Validates input, runs the handler, and returns a structured result.

        Args:
            tool_name: Name of the tool to execute.
            input_data: Input data for the tool.

        Returns:
            ToolResult with execution outcome.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                error=f"Unknown tool: {tool_name}",
            )

        # Validate input
        errors = tool.validate_input(input_data)
        if errors:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                error=f"Validation failed: {'; '.join(errors)}",
            )

        handler = self._handlers[tool_name]
        start = time.monotonic()
        try:
            output = await handler(input_data)
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.SUCCESS,
                output=output,
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            logger.error("Tool %s execution failed: %s", tool_name, e, exc_info=True)
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                error=str(e),
                execution_time_ms=elapsed,
            )


class MCPClient:
    """Client for discovering and invoking tools on MCP servers.

    Usage:
        client = MCPClient()
        client.register_server(server)
        tools = client.list_tools()
        result = await client.invoke("Read", {"path": "file.py"})
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServer] = {}

    def register_server(self, server: MCPServer) -> None:
        """Register an MCP server."""
        self._servers[server.server_id] = server

    def list_servers(self) -> list[str]:
        """List registered server IDs."""
        return list(self._servers.keys())

    def list_tools(self, server_id: str | None = None) -> list[MCPTool]:
        """List all available tools, optionally filtered by server.

        Args:
            server_id: If specified, only list tools from this server.

        Returns:
            List of available tools.
        """
        if server_id:
            server = self._servers.get(server_id)
            return server.list_tools() if server else []

        tools: list[MCPTool] = []
        for server in self._servers.values():
            tools.extend(server.list_tools())
        return tools

    def find_tool(self, tool_name: str) -> tuple[MCPServer, MCPTool] | None:
        """Find a tool across all registered servers.

        Returns (server, tool) tuple or None if not found.
        """
        for server in self._servers.values():
            tool = server.get_tool(tool_name)
            if tool:
                return server, tool
        return None

    async def invoke(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        server_id: str | None = None,
    ) -> ToolResult:
        """Invoke a tool by name.

        If server_id is not specified, searches all servers.

        Args:
            tool_name: Name of the tool to invoke.
            input_data: Input data for the tool.
            server_id: Specific server to use (optional).

        Returns:
            ToolResult with execution outcome.
        """
        if server_id:
            server = self._servers.get(server_id)
            if server is None:
                return ToolResult(
                    tool_name=tool_name,
                    status=ToolStatus.ERROR,
                    error=f"Unknown server: {server_id}",
                )
            return await server.execute(tool_name, input_data)

        result = self.find_tool(tool_name)
        if result is None:
            return ToolResult(
                tool_name=tool_name,
                status=ToolStatus.ERROR,
                error=f"Tool not found: {tool_name}",
            )
        server, _ = result
        return await server.execute(tool_name, input_data)
