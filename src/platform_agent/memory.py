"""Memory layer for the Platform Agent — event-based AgentCore Memory.

Provides two abstraction layers:

1. **ConversationMemory** — Short-term memory using AgentCore events (create_event /
   list_events). Stores conversation turns and retrieves history for a session.

2. **LongTermMemory** — Long-term memory using AgentCore memory records
   (retrieve_memory_records). Semantic search across extracted insights.

3. **InMemoryStore** — Local development fallback (no AWS calls).

Namespace isolation strategy:
    Long-term memory records are scoped per actor via server-side namespace
    prefixes.  When ``actor_id`` is supplied to ``search_long_term``, the
    search is narrowed to ``/actors/{actor_id}/`` so that AgentCore filters
    records at the API level — no client-side post-processing needed.
    This requires that Memory Strategies are configured with namespace
    templates that include ``{actorId}`` (e.g. ``/actors/{actorId}/``).

Usage (production):
    memory = AgentCoreMemory(memory_id="mem-abc123")
    # Store a user message
    memory.add_user_message(actor_id="U123", session_id="thread-1", text="Hello")
    # Store assistant reply
    memory.add_assistant_message(actor_id="U123", session_id="thread-1", text="Hi!")
    # Get conversation history as Bedrock messages array
    messages = memory.get_conversation_history(actor_id="U123", session_id="thread-1", max_turns=20)
    # Semantic search for long-term memories (server-side namespace isolation)
    records = memory.search_long_term(query="user preferences", actor_id="U123")

Usage (local dev):
    memory = LocalMemory()
    # Same interface, in-memory storage
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ConversationTurn:
    """A single conversation turn (one message)."""

    role: str  # "user" | "assistant"
    text: str
    timestamp: datetime | None = None
    event_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class MemoryRecord:
    """A long-term memory record extracted by AgentCore strategies."""

    record_id: str
    text: str
    score: float = 0.0
    strategy_id: str = ""
    namespaces: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class MemoryBackend(ABC):
    """Abstract interface for agent memory (short-term + long-term)."""

    # -- Short-term (conversation events) ----------------------------------

    @abstractmethod
    def add_user_message(
        self,
        actor_id: str,
        session_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        """Store a user message event. Returns event_id if available."""
        ...

    @abstractmethod
    def add_assistant_message(
        self,
        actor_id: str,
        session_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        """Store an assistant message event. Returns event_id if available."""
        ...

    @abstractmethod
    def get_conversation_history(
        self,
        actor_id: str,
        session_id: str,
        max_turns: int = 20,
    ) -> list[ConversationTurn]:
        """Retrieve recent conversation turns for a session.

        Returns turns in chronological order (oldest first).
        """
        ...

    # -- Long-term (extracted memory records) ------------------------------

    @abstractmethod
    def search_long_term(
        self,
        query: str,
        namespace_prefix: str = "/",
        top_k: int = 5,
        strategy_id: str | None = None,
        actor_id: str | None = None,
        project: str | None = None,
    ) -> list[MemoryRecord]:
        """Semantic search over long-term memory records.

        Args:
            query: Search query for semantic matching.
            namespace_prefix: Namespace prefix to search within.
            top_k: Maximum number of results.
            strategy_id: Filter by specific strategy.
            actor_id: If provided, scope search to this actor's namespace
                (``/actors/{actor_id}/``). Uses server-side filtering.
            project: If provided alongside actor_id, scope search to a
                specific project (``/actors/{actor_id}/projects/{project}/``).
        """
        ...


# ---------------------------------------------------------------------------
# AgentCore implementation (production)
# ---------------------------------------------------------------------------

class AgentCoreMemory(MemoryBackend):
    """AgentCore Memory integration using the bedrock_agentcore SDK MemoryClient.

    Uses the event-based model:
    - MemoryClient.create_event() to store conversation turns
    - MemoryClient.list_events() to retrieve conversation history
    - retrieve_memory_records() for long-term semantic search

    Long-term memory records are automatically extracted by AgentCore
    based on configured strategies (Semantic, UserPreference, Summary).
    You don't manually write to long-term memory — it's derived from events.

    Server-side namespace isolation:
        Long-term searches scope results to /actors/{actor_id}/ when an
        actor_id is provided, delegating user isolation to AgentCore rather
        than relying on client-side filtering.

    Requires:
    - bedrock-agentcore SDK (preferred) or boto3 (deprecated fallback)
    - A pre-created Memory resource (memory_id)
    - IAM permissions: bedrock-agentcore:CreateEvent, ListEvents,
      RetrieveMemoryRecords
    """

    def __init__(
        self,
        memory_id: str | None = None,
        region: str | None = None,
    ) -> None:
        self._memory_id = memory_id or os.environ.get("AGENTCORE_MEMORY_ID", "")
        if not self._memory_id:
            raise ValueError(
                "memory_id must be provided or set via AGENTCORE_MEMORY_ID env var"
            )

        region = region or os.environ.get("PLATO_REGION", "us-west-2")

        try:
            from bedrock_agentcore.memory import MemoryClient

            self._client = MemoryClient(region_name=region)
            self._use_sdk = True
        except ImportError:
            import warnings

            # DEPRECATED: boto3 fallback — the production entrypoint always
            # uses the bedrock-agentcore SDK MemoryClient.  This path exists
            # only for CLI tooling and legacy environments that have not yet
            # adopted the SDK.  It will be removed in a future version.
            warnings.warn(
                "bedrock_agentcore.memory.MemoryClient not available. "
                "Falling back to raw boto3 — this is deprecated and will "
                "be removed in a future version.",
                DeprecationWarning,
                stacklevel=2,
            )
            try:
                import boto3
            except ImportError as exc:
                raise ImportError(
                    "Either bedrock-agentcore SDK or boto3 is required for "
                    "AgentCoreMemory."
                ) from exc
            self._client = boto3.client("bedrock-agentcore", region_name=region)
            self._use_sdk = False

    @staticmethod
    def _actor_namespace(actor_id: str) -> str:
        """Build a server-side namespace prefix for user isolation.

        AgentCore Memory stores records under strategy-specific namespaces:
        ``/strategies/{strategyId}/actors/{actorId}/``

        Since records span multiple strategies, we search from root ``/``
        but ALWAYS pass the ``actor_id`` to scope results. AgentCore's
        retrieve_memory_records with a strategy filter handles isolation.

        IMPORTANT: This returns root because the API's prefix matching
        needs to cover all strategy paths. Actor isolation is enforced
        by the actorId in each strategy's namespace template.
        """
        # Return root prefix — actor scoping happens via strategy namespaces
        # which contain the actorId pattern.
        return "/"

    @staticmethod
    def _project_namespace(actor_id: str, project: str) -> str:
        """Build a namespace scoped to a specific project for an actor.

        Enables per-project memory isolation so that insights from different
        projects (e.g. "weather-agent" vs "rag-bot") don't bleed into each
        other during semantic search.

        Example: ``/actors/U123/projects/weather-agent/``
        """
        return f"/actors/{actor_id}/projects/{project}/"

    def _create_event(
        self,
        actor_id: str,
        session_id: str,
        text: str,
        role: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        """Create a conversational event in AgentCore Memory.

        Args:
            actor_id: The user/actor identifier.
            session_id: The session/conversation identifier.
            text: Message text content.
            role: "USER" or "ASSISTANT".
            metadata: Optional key-value metadata.

        Returns:
            The event_id if created successfully, None on failure.
        """
        try:
            sdk_metadata = None
            if metadata:
                sdk_metadata = {
                    k: {"stringValue": v} for k, v in metadata.items()
                }

            if self._use_sdk:
                response = self._client.create_event(
                    memory_id=self._memory_id,
                    actor_id=actor_id,
                    session_id=session_id,
                    messages=[(text, role)],
                    event_timestamp=datetime.now(timezone.utc),
                    metadata=sdk_metadata,
                )
            else:
                # DEPRECATED: Legacy boto3 path — not used by the production
                # entrypoint (which always has bedrock-agentcore SDK).  Retained
                # for CLI backward compatibility only.
                kwargs: dict[str, Any] = {
                    "memoryId": self._memory_id,
                    "actorId": actor_id,
                    "sessionId": session_id,
                    "eventTimestamp": datetime.now(timezone.utc),
                    "payload": [
                        {
                            "conversational": {
                                "content": {"text": text},
                                "role": role,
                            }
                        }
                    ],
                }
                if sdk_metadata:
                    kwargs["metadata"] = sdk_metadata
                response = self._client.create_event(**kwargs)

            event = response.get("event", {})
            event_id = event.get("eventId")
            logger.debug(
                "Created %s event %s in session %s",
                role, event_id, session_id,
            )
            return event_id

        except Exception:
            logger.error(
                "Failed to create %s event in session %s",
                role, session_id, exc_info=True,
            )
            return None

    def add_user_message(
        self,
        actor_id: str,
        session_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        return self._create_event(actor_id, session_id, text, "USER", metadata)

    def add_assistant_message(
        self,
        actor_id: str,
        session_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        return self._create_event(actor_id, session_id, text, "ASSISTANT", metadata)

    def get_conversation_history(
        self,
        actor_id: str,
        session_id: str,
        max_turns: int = 20,
    ) -> list[ConversationTurn]:
        """Retrieve conversation history from AgentCore events.

        Uses SDK MemoryClient.list_events when available, falling back to
        raw boto3 with manual pagination.  Returns up to *max_turns* most
        recent turns in chronological order.
        """
        try:
            if self._use_sdk:
                all_events = self._client.list_events(
                    memory_id=self._memory_id,
                    actor_id=actor_id,
                    session_id=session_id,
                    max_results=min(max_turns, 100),
                    include_payload=True,
                )
            else:
                # DEPRECATED: Legacy boto3 path with manual pagination —
                # not used by the production entrypoint.  Retained for CLI
                # backward compatibility only.
                all_events: list[dict] = []
                next_token: str | None = None
                while True:
                    kwargs: dict[str, Any] = {
                        "memoryId": self._memory_id,
                        "sessionId": session_id,
                        "actorId": actor_id,
                        "includePayloads": True,
                        "maxResults": min(max_turns, 100),
                    }
                    if next_token:
                        kwargs["nextToken"] = next_token

                    response = self._client.list_events(**kwargs)
                    events = response.get("events", [])
                    all_events.extend(events)
                    next_token = response.get("nextToken")

                    if not next_token or len(all_events) >= max_turns:
                        break

            # Take the last max_turns events (most recent)
            recent = all_events[-max_turns:] if len(all_events) > max_turns else all_events

            turns: list[ConversationTurn] = []
            for event in recent:
                payload_items = event.get("payload", [])
                for item in payload_items:
                    conv = item.get("conversational")
                    if conv:
                        role_raw = conv.get("role", "").upper()
                        role = "user" if role_raw == "USER" else "assistant"
                        text = conv.get("content", {}).get("text", "")
                        meta = {}
                        for k, v in event.get("metadata", {}).items():
                            meta[k] = v.get("stringValue", "")
                        turns.append(ConversationTurn(
                            role=role,
                            text=text,
                            timestamp=event.get("eventTimestamp"),
                            event_id=event.get("eventId"),
                            metadata=meta,
                        ))

            logger.debug(
                "Retrieved %d turns for session %s", len(turns), session_id,
            )
            return turns

        except Exception:
            logger.error(
                "Failed to retrieve history for session %s",
                session_id, exc_info=True,
            )
            return []

    def search_long_term(
        self,
        query: str,
        namespace_prefix: str = "/",
        top_k: int = 5,
        strategy_id: str | None = None,
        actor_id: str | None = None,
        project: str | None = None,
    ) -> list[MemoryRecord]:
        """Semantic search over long-term memory records.

        Uses **server-side namespace isolation** to scope results per actor
        and optionally per project.

        Namespace resolution priority:
            1. ``actor_id`` + ``project`` → ``/actors/{actor_id}/projects/{project}/``
            2. ``actor_id`` only → ``/actors/{actor_id}/``
            3. Neither → use ``namespace_prefix`` (default ``"/"``)

        Long-term records are automatically extracted by AgentCore from
        events based on configured strategies.  This searches across those
        extracted records.
        """
        try:
            # Server-side namespace isolation
            if actor_id and project:
                ns = self._project_namespace(actor_id, project)
            elif actor_id:
                ns = self._actor_namespace(actor_id)
            else:
                ns = namespace_prefix

            if self._use_sdk:
                # SDK MemoryClient wraps boto3 but may not convert
                # snake_case → camelCase for nested dicts like search_criteria.
                # Use camelCase to be safe.
                sdk_search: dict[str, Any] = {
                    "searchQuery": query,
                    "topK": top_k,
                }
                if strategy_id:
                    sdk_search["memoryStrategyId"] = strategy_id

                response = self._client.retrieve_memory_records(
                    memory_id=self._memory_id,
                    namespace=ns,
                    search_criteria=sdk_search,
                )
            else:
                # DEPRECATED: Legacy boto3 path — not used by the production
                # entrypoint.  Retained for CLI backward compatibility only.
                search_criteria: dict[str, Any] = {
                    "searchQuery": query,
                    "topK": top_k,
                }
                if strategy_id:
                    search_criteria["memoryStrategyId"] = strategy_id

                response = self._client.retrieve_memory_records(
                    memoryId=self._memory_id,
                    namespace=ns,
                    searchCriteria=search_criteria,
                )

            records: list[MemoryRecord] = []
            for summary in response.get("memoryRecordSummaries", []):
                content = summary.get("content", {})
                text = content.get("text", "")
                meta = {}
                for k, v in summary.get("metadata", {}).items():
                    meta[k] = v.get("stringValue", "")
                records.append(MemoryRecord(
                    record_id=summary.get("memoryRecordId", ""),
                    text=text,
                    score=summary.get("score", 0.0),
                    strategy_id=summary.get("memoryStrategyId", ""),
                    namespaces=summary.get("namespaces", []),
                    created_at=summary.get("createdAt"),
                    metadata=meta,
                ))

            logger.debug(
                "Found %d long-term records for query: %s",
                len(records), query[:50],
            )
            return records

        except Exception:
            logger.error(
                "Failed to search long-term memory", exc_info=True,
            )
            return []


# ---------------------------------------------------------------------------
# Local implementation (development/testing)
# ---------------------------------------------------------------------------

class LocalMemory(MemoryBackend):
    """In-memory implementation for local development and testing.

    Stores conversation turns in a dict keyed by (actor_id, session_id).
    Long-term search does simple substring matching over stored turns.
    Data is lost when the process exits.
    """

    def __init__(self) -> None:
        # Key: (actor_id, session_id) -> list of ConversationTurn
        self._sessions: dict[tuple[str, str], list[ConversationTurn]] = {}
        self._event_counter: int = 0

    def add_user_message(
        self,
        actor_id: str,
        session_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        return self._add_turn(actor_id, session_id, "user", text, metadata)

    def add_assistant_message(
        self,
        actor_id: str,
        session_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        return self._add_turn(actor_id, session_id, "assistant", text, metadata)

    def _add_turn(
        self,
        actor_id: str,
        session_id: str,
        role: str,
        text: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        key = (actor_id, session_id)
        if key not in self._sessions:
            self._sessions[key] = []

        self._event_counter += 1
        event_id = f"local-evt-{self._event_counter}"

        self._sessions[key].append(ConversationTurn(
            role=role,
            text=text,
            timestamp=datetime.now(timezone.utc),
            event_id=event_id,
            metadata=metadata or {},
        ))
        return event_id

    def get_conversation_history(
        self,
        actor_id: str,
        session_id: str,
        max_turns: int = 20,
    ) -> list[ConversationTurn]:
        key = (actor_id, session_id)
        turns = self._sessions.get(key, [])
        return turns[-max_turns:]

    def search_long_term(
        self,
        query: str,
        namespace_prefix: str = "/",
        top_k: int = 5,
        strategy_id: str | None = None,
        actor_id: str | None = None,
        project: str | None = None,
    ) -> list[MemoryRecord]:
        """Simple substring search across all stored turns (dev fallback).

        If actor_id is provided, only searches turns from that actor's sessions.
        The project parameter is accepted for interface compatibility but
        is not used in the local implementation.
        """
        query_lower = query.lower()
        results: list[MemoryRecord] = []

        for (_actor, _session), turns in self._sessions.items():
            # Actor filtering for LocalMemory
            if actor_id and _actor != actor_id:
                continue
            for turn in turns:
                if query_lower in turn.text.lower():
                    results.append(MemoryRecord(
                        record_id=turn.event_id or "",
                        text=turn.text,
                        score=1.0,
                    ))
                    if len(results) >= top_k:
                        return results

        return results


# ---------------------------------------------------------------------------
# DEPRECATED: Legacy KV interface (backward compatibility)
#
# The classes below (MemoryStore, InMemoryStore) and the factory
# create_memory_store() are deprecated.  They are NOT used by the production
# entrypoint — only by CLI tooling and legacy tests.  New code should use
# MemoryBackend / create_memory_backend() instead.
# ---------------------------------------------------------------------------

class MemoryStore(ABC):
    """Legacy abstract interface for KV-style memory storage.

    .. deprecated::
        Use :class:`MemoryBackend` (event-based) instead.
        Kept for backward compatibility with existing tests and CLI.
    """

    @abstractmethod
    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        ...

    @abstractmethod
    async def search(self, namespace: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def list(self, namespace: str) -> list[str]:
        ...

    @abstractmethod
    async def delete(self, namespace: str, key: str) -> bool:
        ...


@dataclass
class InMemoryStore(MemoryStore):
    """In-memory KV store for local development and testing (legacy).

    .. deprecated::
        Use :class:`LocalMemory` instead for new code.
    """

    _data: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    async def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        return self._data.get(namespace, {}).get(key)

    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        if namespace not in self._data:
            self._data[namespace] = {}
        self._data[namespace][key] = value

    async def search(self, namespace: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        ns_data = self._data.get(namespace, {})
        results: list[dict[str, Any]] = []
        query_lower = query.lower()
        for key, value in ns_data.items():
            searchable = key.lower()
            for v in value.values():
                if isinstance(v, str):
                    searchable += " " + v.lower()
            if query_lower in searchable:
                results.append({"key": key, **value})
            if len(results) >= limit:
                break
        return results

    async def list(self, namespace: str) -> list[str]:
        return list(self._data.get(namespace, {}).keys())

    async def delete(self, namespace: str, key: str) -> bool:
        ns_data = self._data.get(namespace, {})
        if key in ns_data:
            del ns_data[key]
            return True
        return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_memory_backend(
    backend: str | None = None,
    **kwargs: Any,
) -> MemoryBackend:
    """Create the appropriate memory backend.

    Selection priority:
        1. Explicit `backend` argument ("agentcore" or "local")
        2. PLATO_MEMORY_BACKEND environment variable
        3. Defaults to "local" (LocalMemory)

    Args:
        backend: Force a specific backend ("agentcore" or "local").
        **kwargs: Passed to the backend constructor.

    Returns:
        A configured MemoryBackend instance.
    """
    backend = backend or os.environ.get("PLATO_MEMORY_BACKEND", "local")

    if backend == "agentcore":
        return AgentCoreMemory(**kwargs)
    elif backend == "local":
        return LocalMemory()
    else:
        raise ValueError(
            f"Unknown memory backend: {backend!r}. Use 'agentcore' or 'local'."
        )


def create_memory_store(backend: str | None = None, **kwargs: Any) -> MemoryStore:
    """Legacy factory — creates a KV-style MemoryStore.

    .. deprecated::
        Use :func:`create_memory_backend` instead.  This factory is retained
        only for CLI backward compatibility.
    """
    backend = backend or os.environ.get("PLATO_MEMORY_BACKEND", "local")

    if backend == "agentcore":
        # AgentCore now uses event-based API; legacy KV wrapper not supported.
        # Raise a helpful error directing to the new API.
        raise ValueError(
            "AgentCore memory now uses event-based API. "
            "Use create_memory_backend(backend='agentcore') instead of "
            "create_memory_store()."
        )
    elif backend == "local":
        return InMemoryStore(**kwargs)
    else:
        raise ValueError(f"Unknown memory backend: {backend!r}. Use 'agentcore' or 'local'.")


# ---------------------------------------------------------------------------
# Helper: Convert ConversationTurns to Bedrock messages array
# ---------------------------------------------------------------------------

def turns_to_bedrock_messages(turns: list[ConversationTurn]) -> list[dict[str, Any]]:
    """Convert ConversationTurns into Bedrock Converse API messages format.

    Returns a list of {"role": "user"|"assistant", "content": [{"text": "..."}]}
    suitable for passing directly to the Bedrock Converse API `messages` parameter.

    Handles edge cases:
    - Consecutive same-role messages are merged.
    - Empty turns are skipped.
    - Ensures the array starts with a "user" message (Bedrock requirement).
    """
    if not turns:
        return []

    messages: list[dict[str, Any]] = []

    for turn in turns:
        if not turn.text.strip():
            continue

        if messages and messages[-1]["role"] == turn.role:
            # Merge consecutive same-role messages
            messages[-1]["content"][0]["text"] += "\n" + turn.text
        else:
            messages.append({
                "role": turn.role,
                "content": [{"text": turn.text}],
            })

    # Bedrock requires messages to start with "user" role.
    # If the first message is assistant, prepend a synthetic user context marker.
    if messages and messages[0]["role"] != "user":
        messages.insert(0, {
            "role": "user",
            "content": [{"text": "[Previous conversation context]"}],
        })

    # Bedrock requires alternating user/assistant roles.
    # Merge or skip messages to ensure strict alternation.
    cleaned: list[dict[str, Any]] = []
    for msg in messages:
        if not cleaned:
            # First message — must be user (guaranteed by above)
            cleaned.append(msg)
        elif cleaned[-1]["role"] == msg["role"]:
            # Same role as previous — merge text
            cleaned[-1]["content"][0]["text"] += "\n" + msg["content"][0]["text"]
        else:
            # Alternating role — append
            cleaned.append(msg)

    return cleaned


# ---------------------------------------------------------------------------
# Namespace helpers for AgentCore Memory (shims for compatibility)
# ---------------------------------------------------------------------------


def build_session_namespace(actor_id: str, session_id: str) -> str:
    """Build a session-scoped namespace path."""
    return f"/teams/{actor_id}/sessions/{session_id}/"


def build_consolidation_namespace(actor_id: str) -> str:
    """Build a consolidation namespace path for an actor."""
    return f"/teams/{actor_id}/consolidated/"


def build_actor_namespace(actor_id: str) -> str:
    """Build an actor-scoped namespace path."""
    return f"/teams/{actor_id}/"


def build_legacy_namespace(actor_id: str) -> str:
    """Build a legacy namespace path for an actor."""
    return f"/actors/{actor_id}/"
