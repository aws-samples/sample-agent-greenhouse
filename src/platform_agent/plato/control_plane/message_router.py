"""Message Router — middleware-based message routing between agents.

Provides a pipeline of middleware for authentication, policy checking,
content filtering, audit logging, and circuit breaking. Messages flow
through the middleware chain before delivery.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A message between agents.

    Carries intent and payload from a source agent to a target agent,
    or to a broadcast address (target_agent="*").
    """

    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_agent: str = ""
    target_agent: str = ""
    intent: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tenant_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "message_id": self.message_id,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "intent": self.intent,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "tenant_id": self.tenant_id,
            "metadata": self.metadata,
        }


class RouterMiddleware(Protocol):
    """Protocol for message router middleware.

    Middleware processes a message and returns it (possibly modified)
    or None to filter/block the message.
    """

    def process(self, message: Message) -> Message | None:
        """Process a message. Return None to block it."""
        ...


class AuthenticateMiddleware:
    """Verify that the source agent is registered."""

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def process(self, message: Message) -> Message | None:
        """Check that source agent exists in the registry."""
        if not message.source_agent:
            logger.warning("Message rejected: no source agent")
            return None

        # Look up by tenant
        agents = self._registry.list_agents(tenant_id=message.tenant_id)
        agent_ids = {a.agent_id for a in agents}

        if message.source_agent not in agent_ids:
            logger.warning(
                "Message rejected: source agent '%s' not registered (tenant=%s)",
                message.source_agent,
                message.tenant_id,
            )
            return None

        return message


class PolicyCheckMiddleware:
    """Check message against the policy engine."""

    def __init__(self, policy_engine: Any) -> None:
        self._policy_engine = policy_engine

    def process(self, message: Message) -> Message | None:
        """Evaluate send_message action against policies."""
        from platform_agent.foundation.guardrails import AuthorizationRequest

        request = AuthorizationRequest(
            principal_type="Agent",
            principal_id=message.source_agent,
            action="send_message",
            resource_type="Message",
            resource_id=message.target_agent,
            context={
                "intent": message.intent,
                "tenant_id": message.tenant_id,
            },
        )
        decision = self._policy_engine.evaluate(request)
        if not decision.is_allowed:
            logger.warning(
                "Message from '%s' to '%s' denied by policy: %s",
                message.source_agent,
                message.target_agent,
                decision.reasons,
            )
            return None
        return message


class ContentFilterMiddleware:
    """Filter thinking/reasoning leak patterns from message payloads."""

    def __init__(self, policy_engine: Any) -> None:
        self._policy_engine = policy_engine

    def process(self, message: Message) -> Message | None:
        """Filter content in payload text fields."""
        if not hasattr(self._policy_engine, "check_content"):
            return message

        for key in ("text", "content", "body", "response"):
            if key in message.payload and isinstance(message.payload[key], str):
                result = self._policy_engine.check_content(message.payload[key])
                if not result.is_clean:
                    message.payload[key] = result.filtered_text
                    message.metadata["content_filtered"] = True
                    message.metadata["filtered_patterns"] = result.patterns_found
                    logger.info(
                        "Content filtered in message %s (field=%s)",
                        message.message_id,
                        key,
                    )

        return message


class AuditLogMiddleware:
    """Log messages to the audit store."""

    def __init__(self, audit_store: Any) -> None:
        self._audit_store = audit_store

    def process(self, message: Message) -> Message | None:
        """Record message in audit log."""
        self._audit_store.log(
            agent_id=message.source_agent,
            tenant_id=message.tenant_id,
            action="message_sent",
            details={
                "message_id": message.message_id,
                "target": message.target_agent,
                "intent": message.intent,
            },
            result="success",
        )
        return message


class CircuitBreaker:
    """Circuit breaker for agent-pair conversations.

    Tracks message counts between agent pairs and breaks the circuit
    when the threshold is exceeded within a window.
    """

    def __init__(self, threshold: int = 50, window_seconds: float = 300.0) -> None:
        self._threshold = threshold
        self._window_seconds = window_seconds
        self._counts: dict[tuple[str, str], list[datetime]] = {}

    def process(self, message: Message) -> Message | None:
        """Check if the circuit should be broken for this agent pair."""
        pair = (message.source_agent, message.target_agent)
        now = datetime.now(timezone.utc)
        cutoff = now - __import__("datetime").timedelta(seconds=self._window_seconds)

        if pair not in self._counts:
            self._counts[pair] = []

        # Clean old entries
        self._counts[pair] = [t for t in self._counts[pair] if t > cutoff]

        if len(self._counts[pair]) >= self._threshold:
            logger.warning(
                "Circuit broken: %s → %s (%d messages in %.0fs)",
                message.source_agent,
                message.target_agent,
                len(self._counts[pair]),
                self._window_seconds,
            )
            return None

        self._counts[pair].append(now)
        return message

    def reset(self, source: str, target: str) -> None:
        """Reset circuit breaker for an agent pair."""
        pair = (source, target)
        self._counts.pop(pair, None)

    def get_count(self, source: str, target: str) -> int:
        """Get current message count for an agent pair."""
        pair = (source, target)
        if pair not in self._counts:
            return 0
        now = datetime.now(timezone.utc)
        cutoff = now - __import__("datetime").timedelta(seconds=self._window_seconds)
        self._counts[pair] = [t for t in self._counts[pair] if t > cutoff]
        return len(self._counts[pair])


class MessageRouter:
    """Routes messages through a middleware pipeline and delivers them.

    Messages pass through each middleware in order. If any middleware
    returns None, the message is dropped. Delivered messages are stored
    in the target agent's inbox.
    """

    def __init__(self) -> None:
        self._middleware: list[Any] = []
        self._inboxes: dict[str, list[Message]] = {}
        self._delivered: list[Message] = []

    def add_middleware(self, middleware: Any) -> None:
        """Add a middleware to the pipeline."""
        self._middleware.append(middleware)

    def send(self, message: Message) -> Message | None:
        """Send a message through the middleware pipeline.

        Returns the delivered message, or None if it was filtered.
        """
        current: Message | None = message

        for mw in self._middleware:
            if current is None:
                break
            current = mw.process(current)

        if current is not None:
            self._deliver(current)

        return current

    def _deliver(self, message: Message) -> None:
        """Deliver a message to the target agent's inbox."""
        target = message.target_agent
        if target not in self._inboxes:
            self._inboxes[target] = []
        self._inboxes[target].append(message)
        self._delivered.append(message)
        logger.debug(
            "Delivered message %s: %s → %s",
            message.message_id,
            message.source_agent,
            message.target_agent,
        )

    def get_inbox(self, agent_id: str) -> list[Message]:
        """Get all messages in an agent's inbox."""
        return list(self._inboxes.get(agent_id, []))

    def clear_inbox(self, agent_id: str) -> int:
        """Clear an agent's inbox. Returns count of cleared messages."""
        count = len(self._inboxes.get(agent_id, []))
        self._inboxes.pop(agent_id, None)
        return count

    @property
    def delivered_count(self) -> int:
        """Total number of delivered messages."""
        return len(self._delivered)

    @property
    def delivered_messages(self) -> list[Message]:
        """All delivered messages."""
        return list(self._delivered)
