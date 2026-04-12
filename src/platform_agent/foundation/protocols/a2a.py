"""A2A (Agent-to-Agent) protocol implementation.

Provides structured inter-agent communication following the A2A protocol
specification. Agents can discover each other, send tasks, and receive
results through a standardized message format.

Key concepts:
- AgentCard: Metadata describing an agent's capabilities
- A2AMessage: Structured message for inter-agent communication
- A2AServer: Receives and handles incoming agent requests
- A2AClient: Sends requests to other agents
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Types of A2A messages."""

    TASK = "task"           # Request to perform a task
    RESULT = "result"       # Task result
    STATUS = "status"       # Status update
    ERROR = "error"         # Error response
    DISCOVER = "discover"   # Agent discovery request
    CARD = "card"           # Agent card response


class TaskStatus(Enum):
    """Status of an A2A task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentCard:
    """Metadata describing an agent's capabilities.

    Used for agent discovery — other agents can find and understand
    what this agent can do based on its card.
    """

    agent_id: str
    name: str
    description: str
    version: str = "0.1.0"
    capabilities: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    endpoint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize agent card."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "capabilities": self.capabilities,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "endpoint": self.endpoint,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCard:
        """Deserialize agent card."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class A2AMessage:
    """Structured message for inter-agent communication.

    Follows the A2A protocol format with sender, receiver, message type,
    and payload.
    """

    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    message_type: MessageType = MessageType.TASK
    sender_id: str = ""
    receiver_id: str = ""
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = ""  # Links request to response

    def to_dict(self) -> dict[str, Any]:
        """Serialize message."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "task_id": self.task_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> A2AMessage:
        """Deserialize message."""
        data = dict(data)
        if "message_type" in data:
            data["message_type"] = MessageType(data["message_type"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def create_response(
        self,
        message_type: MessageType = MessageType.RESULT,
        payload: dict[str, Any] | None = None,
    ) -> A2AMessage:
        """Create a response message linked to this request."""
        return A2AMessage(
            message_type=message_type,
            sender_id=self.receiver_id,
            receiver_id=self.sender_id,
            task_id=self.task_id,
            payload=payload or {},
            correlation_id=self.message_id,
        )


class A2AServer:
    """Server that receives and handles incoming A2A requests.

    Agents register handlers for different message types. The server
    dispatches incoming messages to the appropriate handler.

    Usage:
        server = A2AServer(agent_card)
        server.register_handler(MessageType.TASK, handle_task)
        response = await server.handle(message)
    """

    def __init__(self, agent_card: AgentCard) -> None:
        self._card = agent_card
        self._handlers: dict[MessageType, Any] = {}
        self._task_status: dict[str, TaskStatus] = {}

    @property
    def agent_card(self) -> AgentCard:
        """This server's agent card."""
        return self._card

    def register_handler(self, message_type: MessageType, handler: Any) -> None:
        """Register a handler for a message type.

        Handler signature: async def handler(message: A2AMessage) -> A2AMessage
        """
        self._handlers[message_type] = handler

    async def handle(self, message: A2AMessage) -> A2AMessage:
        """Process an incoming A2A message.

        Dispatches to the registered handler for the message type.
        Returns a DISCOVER response with the agent card if requested.
        """
        logger.info(
            "A2A server %s received %s from %s",
            self._card.agent_id,
            message.message_type.value,
            message.sender_id,
        )

        if message.message_type == MessageType.DISCOVER:
            return message.create_response(
                message_type=MessageType.CARD,
                payload=self._card.to_dict(),
            )

        handler = self._handlers.get(message.message_type)
        if handler is None:
            return message.create_response(
                message_type=MessageType.ERROR,
                payload={"error": f"No handler for {message.message_type.value}"},
            )

        self._task_status[message.task_id] = TaskStatus.IN_PROGRESS
        try:
            response = await handler(message)
            self._task_status[message.task_id] = TaskStatus.COMPLETED
            return response
        except Exception as e:
            self._task_status[message.task_id] = TaskStatus.FAILED
            logger.error("A2A handler failed: %s", e, exc_info=True)
            return message.create_response(
                message_type=MessageType.ERROR,
                payload={"error": str(e)},
            )

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        """Get the status of a task."""
        return self._task_status.get(task_id)


class A2AClient:
    """Client for sending A2A requests to other agents.

    Maintains a registry of known agents and their endpoints.

    Usage:
        client = A2AClient(sender_id="plato")
        client.register_agent(other_agent_card)
        response = await client.send_task("other-agent", {"task": "review code"})
    """

    def __init__(self, sender_id: str) -> None:
        self._sender_id = sender_id
        self._agents: dict[str, AgentCard] = {}
        self._servers: dict[str, A2AServer] = {}  # For local routing

    def register_agent(self, card: AgentCard) -> None:
        """Register a known agent."""
        self._agents[card.agent_id] = card

    def register_local_server(self, server: A2AServer) -> None:
        """Register a local A2A server for direct routing (no network)."""
        self._servers[server.agent_card.agent_id] = server
        self._agents[server.agent_card.agent_id] = server.agent_card

    @property
    def known_agents(self) -> list[AgentCard]:
        """List all known agents."""
        return list(self._agents.values())

    async def discover(self, agent_id: str) -> AgentCard | None:
        """Discover an agent's capabilities by ID.

        Returns None if agent is not reachable.
        """
        server = self._servers.get(agent_id)
        if server is None:
            return self._agents.get(agent_id)

        message = A2AMessage(
            message_type=MessageType.DISCOVER,
            sender_id=self._sender_id,
            receiver_id=agent_id,
        )
        response = await server.handle(message)
        if response.message_type == MessageType.CARD:
            card = AgentCard.from_dict(response.payload)
            self._agents[card.agent_id] = card
            return card
        return None

    async def send_task(
        self,
        agent_id: str,
        payload: dict[str, Any],
    ) -> A2AMessage:
        """Send a task to another agent.

        Args:
            agent_id: Target agent ID.
            payload: Task payload.

        Returns:
            Response message from the target agent.

        Raises:
            KeyError: If agent is not known.
            RuntimeError: If no local server is registered for the agent.
        """
        if agent_id not in self._agents:
            raise KeyError(f"Unknown agent: {agent_id}")

        server = self._servers.get(agent_id)
        if server is None:
            raise RuntimeError(
                f"No local server for {agent_id}. "
                "Remote A2A transport not yet implemented."
            )

        message = A2AMessage(
            message_type=MessageType.TASK,
            sender_id=self._sender_id,
            receiver_id=agent_id,
            payload=payload,
        )
        return await server.handle(message)

    async def send_message(self, message: A2AMessage) -> A2AMessage:
        """Send an arbitrary A2A message.

        Args:
            message: The message to send.

        Returns:
            Response message.
        """
        server = self._servers.get(message.receiver_id)
        if server is None:
            raise RuntimeError(
                f"No local server for {message.receiver_id}. "
                "Remote transport not yet implemented."
            )
        return await server.handle(message)
