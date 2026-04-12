"""Tests for A2A and MCP protocol implementations."""

from __future__ import annotations

import pytest

from platform_agent.foundation.protocols.a2a import (
    A2AClient,
    A2AMessage,
    A2AServer,
    AgentCard,
    MessageType,
    TaskStatus,
)
from platform_agent.foundation.protocols.mcp import (
    MCPClient,
    MCPServer,
    MCPTool,
    ToolResult,
    ToolStatus,
)


# ===========================================================================
# A2A Protocol Tests
# ===========================================================================


class TestAgentCard:
    def test_create(self):
        card = AgentCard(
            agent_id="plato",
            name="Platform Agent",
            description="Helps developers deploy agents",
            capabilities=["design", "review", "deploy"],
        )
        assert card.agent_id == "plato"
        assert len(card.capabilities) == 3

    def test_to_dict(self):
        card = AgentCard(agent_id="test", name="Test", description="desc")
        d = card.to_dict()
        assert d["agent_id"] == "test"
        assert d["name"] == "Test"

    def test_from_dict(self):
        data = {"agent_id": "test", "name": "Test", "description": "desc", "version": "1.0"}
        card = AgentCard.from_dict(data)
        assert card.agent_id == "test"
        assert card.version == "1.0"

    def test_roundtrip(self):
        original = AgentCard(
            agent_id="plato",
            name="Plato",
            description="Platform agent",
            capabilities=["design"],
        )
        restored = AgentCard.from_dict(original.to_dict())
        assert restored.agent_id == original.agent_id
        assert restored.capabilities == original.capabilities


class TestA2AMessage:
    def test_create(self):
        msg = A2AMessage(sender_id="a", receiver_id="b", payload={"task": "review"})
        assert msg.message_id  # auto-generated
        assert msg.sender_id == "a"
        assert msg.message_type == MessageType.TASK

    def test_to_dict(self):
        msg = A2AMessage(sender_id="a", receiver_id="b")
        d = msg.to_dict()
        assert d["sender_id"] == "a"
        assert d["message_type"] == "task"

    def test_from_dict(self):
        data = {
            "message_id": "abc",
            "message_type": "result",
            "sender_id": "b",
            "receiver_id": "a",
            "task_id": "t1",
            "payload": {"result": "ok"},
            "timestamp": 123.0,
            "correlation_id": "orig",
        }
        msg = A2AMessage.from_dict(data)
        assert msg.message_type == MessageType.RESULT
        assert msg.correlation_id == "orig"

    def test_create_response(self):
        request = A2AMessage(sender_id="a", receiver_id="b", task_id="t1")
        response = request.create_response(payload={"result": "done"})
        assert response.sender_id == "b"
        assert response.receiver_id == "a"
        assert response.task_id == "t1"
        assert response.correlation_id == request.message_id
        assert response.message_type == MessageType.RESULT


class TestA2AServer:
    @pytest.fixture
    def server(self):
        card = AgentCard(agent_id="test-agent", name="Test", description="Test agent")
        return A2AServer(card)

    @pytest.mark.asyncio
    async def test_discover(self, server):
        msg = A2AMessage(
            message_type=MessageType.DISCOVER,
            sender_id="client",
            receiver_id="test-agent",
        )
        response = await server.handle(msg)
        assert response.message_type == MessageType.CARD
        assert response.payload["agent_id"] == "test-agent"

    @pytest.mark.asyncio
    async def test_handle_task(self, server):
        async def handler(msg):
            return msg.create_response(payload={"result": "processed"})

        server.register_handler(MessageType.TASK, handler)
        msg = A2AMessage(sender_id="client", receiver_id="test-agent", payload={"data": "test"})
        response = await server.handle(msg)
        assert response.message_type == MessageType.RESULT
        assert response.payload["result"] == "processed"

    @pytest.mark.asyncio
    async def test_handle_unknown_type(self, server):
        msg = A2AMessage(
            message_type=MessageType.STATUS,
            sender_id="client",
            receiver_id="test-agent",
        )
        response = await server.handle(msg)
        assert response.message_type == MessageType.ERROR

    @pytest.mark.asyncio
    async def test_handler_error(self, server):
        async def bad_handler(msg):
            raise ValueError("Something went wrong")

        server.register_handler(MessageType.TASK, bad_handler)
        msg = A2AMessage(sender_id="client", receiver_id="test-agent")
        response = await server.handle(msg)
        assert response.message_type == MessageType.ERROR
        assert "Something went wrong" in response.payload["error"]

    @pytest.mark.asyncio
    async def test_task_status_tracking(self, server):
        async def handler(msg):
            return msg.create_response(payload={})

        server.register_handler(MessageType.TASK, handler)
        msg = A2AMessage(sender_id="client", receiver_id="test-agent")
        await server.handle(msg)
        assert server.get_task_status(msg.task_id) == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failed_task_status(self, server):
        async def bad_handler(msg):
            raise RuntimeError("fail")

        server.register_handler(MessageType.TASK, bad_handler)
        msg = A2AMessage(sender_id="client", receiver_id="test-agent")
        await server.handle(msg)
        assert server.get_task_status(msg.task_id) == TaskStatus.FAILED

    def test_agent_card_property(self, server):
        assert server.agent_card.agent_id == "test-agent"


class TestA2AClient:
    @pytest.fixture
    def setup(self):
        card = AgentCard(agent_id="server-agent", name="Server", description="Test")
        server = A2AServer(card)

        async def handler(msg):
            return msg.create_response(payload={"echo": msg.payload.get("input", "")})

        server.register_handler(MessageType.TASK, handler)
        client = A2AClient(sender_id="client-agent")
        client.register_local_server(server)
        return client, server

    @pytest.mark.asyncio
    async def test_send_task(self, setup):
        client, _ = setup
        response = await client.send_task("server-agent", {"input": "hello"})
        assert response.payload["echo"] == "hello"

    @pytest.mark.asyncio
    async def test_discover(self, setup):
        client, _ = setup
        card = await client.discover("server-agent")
        assert card is not None
        assert card.agent_id == "server-agent"

    def test_known_agents(self, setup):
        client, _ = setup
        agents = client.known_agents
        assert len(agents) == 1
        assert agents[0].agent_id == "server-agent"

    @pytest.mark.asyncio
    async def test_send_task_unknown_agent(self, setup):
        client, _ = setup
        with pytest.raises(KeyError, match="Unknown agent"):
            await client.send_task("nonexistent", {})

    def test_register_agent(self):
        client = A2AClient(sender_id="test")
        card = AgentCard(agent_id="remote", name="Remote", description="desc")
        client.register_agent(card)
        assert len(client.known_agents) == 1

    @pytest.mark.asyncio
    async def test_discover_registered_only(self):
        client = A2AClient(sender_id="test")
        card = AgentCard(agent_id="remote", name="Remote", description="desc")
        client.register_agent(card)
        discovered = await client.discover("remote")
        assert discovered is not None
        assert discovered.agent_id == "remote"


# ===========================================================================
# MCP Protocol Tests
# ===========================================================================


class TestMCPTool:
    def test_create(self):
        tool = MCPTool(name="Read", description="Read a file")
        assert tool.name == "Read"

    def test_to_dict(self):
        tool = MCPTool(name="Read", description="Read a file")
        d = tool.to_dict()
        assert d["name"] == "Read"

    def test_from_dict(self):
        data = {"name": "Read", "description": "Read a file", "input_schema": {"required": ["path"]}}
        tool = MCPTool.from_dict(data)
        assert tool.name == "Read"
        assert tool.input_schema["required"] == ["path"]

    def test_validate_input_valid(self):
        tool = MCPTool(
            name="Read",
            description="Read a file",
            input_schema={"required": ["path"]},
        )
        errors = tool.validate_input({"path": "/tmp/file.py"})
        assert errors == []

    def test_validate_input_missing_required(self):
        tool = MCPTool(
            name="Read",
            description="Read a file",
            input_schema={"required": ["path"]},
        )
        errors = tool.validate_input({})
        assert len(errors) == 1
        assert "path" in errors[0]

    def test_validate_input_no_schema(self):
        tool = MCPTool(name="Noop", description="No-op")
        errors = tool.validate_input({"anything": "goes"})
        assert errors == []


class TestToolResult:
    def test_success(self):
        result = ToolResult(tool_name="Read", status=ToolStatus.SUCCESS, output="content")
        assert result.is_success
        assert result.output == "content"

    def test_error(self):
        result = ToolResult(tool_name="Read", status=ToolStatus.ERROR, error="not found")
        assert not result.is_success
        assert result.error == "not found"

    def test_to_dict(self):
        result = ToolResult(tool_name="Read", status=ToolStatus.SUCCESS, output="ok")
        d = result.to_dict()
        assert d["status"] == "success"
        assert d["tool_name"] == "Read"


class TestMCPServer:
    @pytest.fixture
    def server(self):
        return MCPServer("test-server", name="Test Server")

    @pytest.mark.asyncio
    async def test_register_and_execute(self, server):
        tool = MCPTool(name="echo", description="Echo input")

        async def handler(input_data):
            return input_data.get("text", "")

        server.register_tool(tool, handler)
        result = await server.execute("echo", {"text": "hello"})
        assert result.is_success
        assert result.output == "hello"
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, server):
        result = await server.execute("nonexistent", {})
        assert not result.is_success
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_execute_validation_failure(self, server):
        tool = MCPTool(
            name="read",
            description="Read file",
            input_schema={"required": ["path"]},
        )

        async def handler(input_data):
            return "content"

        server.register_tool(tool, handler)
        result = await server.execute("read", {})  # Missing 'path'
        assert not result.is_success
        assert "Validation failed" in result.error

    @pytest.mark.asyncio
    async def test_execute_handler_error(self, server):
        tool = MCPTool(name="bad", description="Always fails")

        async def handler(input_data):
            raise RuntimeError("handler crashed")

        server.register_tool(tool, handler)
        result = await server.execute("bad", {})
        assert not result.is_success
        assert "handler crashed" in result.error

    def test_list_tools(self, server):
        tool1 = MCPTool(name="a", description="A")
        tool2 = MCPTool(name="b", description="B")

        async def noop(data):
            return None

        server.register_tool(tool1, noop)
        server.register_tool(tool2, noop)
        tools = server.list_tools()
        assert len(tools) == 2
        assert {t.name for t in tools} == {"a", "b"}

    def test_get_tool(self, server):
        tool = MCPTool(name="test", description="Test")

        async def noop(data):
            return None

        server.register_tool(tool, noop)
        found = server.get_tool("test")
        assert found is not None
        assert found.name == "test"

    def test_get_tool_nonexistent(self, server):
        assert server.get_tool("nonexistent") is None

    def test_server_properties(self, server):
        assert server.server_id == "test-server"
        assert server.name == "Test Server"


class TestMCPClient:
    @pytest.fixture
    def setup(self):
        server = MCPServer("srv1", name="Server 1")
        tool = MCPTool(name="greet", description="Greet someone")

        async def handler(data):
            return f"Hello, {data.get('name', 'world')}!"

        server.register_tool(tool, handler)
        client = MCPClient()
        client.register_server(server)
        return client, server

    @pytest.mark.asyncio
    async def test_invoke(self, setup):
        client, _ = setup
        result = await client.invoke("greet", {"name": "Plato"})
        assert result.is_success
        assert result.output == "Hello, Plato!"

    @pytest.mark.asyncio
    async def test_invoke_specific_server(self, setup):
        client, _ = setup
        result = await client.invoke("greet", {"name": "test"}, server_id="srv1")
        assert result.is_success

    @pytest.mark.asyncio
    async def test_invoke_unknown_server(self, setup):
        client, _ = setup
        result = await client.invoke("greet", {}, server_id="nonexistent")
        assert not result.is_success
        assert "Unknown server" in result.error

    @pytest.mark.asyncio
    async def test_invoke_unknown_tool(self, setup):
        client, _ = setup
        result = await client.invoke("nonexistent", {})
        assert not result.is_success
        assert "not found" in result.error

    def test_list_servers(self, setup):
        client, _ = setup
        assert client.list_servers() == ["srv1"]

    def test_list_tools(self, setup):
        client, _ = setup
        tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "greet"

    def test_list_tools_by_server(self, setup):
        client, _ = setup
        tools = client.list_tools(server_id="srv1")
        assert len(tools) == 1

    def test_list_tools_unknown_server(self, setup):
        client, _ = setup
        tools = client.list_tools(server_id="nonexistent")
        assert tools == []

    def test_find_tool(self, setup):
        client, _ = setup
        result = client.find_tool("greet")
        assert result is not None
        server, tool = result
        assert tool.name == "greet"

    def test_find_tool_not_found(self, setup):
        client, _ = setup
        assert client.find_tool("nonexistent") is None
