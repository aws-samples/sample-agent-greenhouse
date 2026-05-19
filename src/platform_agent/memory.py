"""Memory layer for the Platform Agent — event-based AgentCore Memory.

Provides two abstraction layers:

1. **ConversationMemory** — Short-term memory using AgentCore events (create_event /
   list_events). Stores conversation turns and retrieves history for a session.

2. **LongTermMemory** — Long-term memory using AgentCore memory records
   (retrieve_memory_records). Semantic search across extracted insights.

3. **InMemoryStore** — Local development fallback (no AWS calls).

Namespace isolation strategy:
    Production Memory has per-strategy namespace templates loaded at runtime
    via ``get_memory``.  ``search_long_term`` issues one
    ``retrieve_memory_records`` call per strategy, substituting ``{actorId}``
    (and ``{memoryStrategyId}``, ``{sessionId}`` where present) so that each
    call is scoped to the requesting actor's namespace.  A defensive
    post-filter drops any record whose namespace does not prefix-match the
    expected actor namespace.  The root namespace ``"/"`` is never used.

Usage (production):
    memory = AgentCoreMemory(memory_id="mem-abc123")
    memory.add_user_message(actor_id="U123", session_id="thread-1", text="Hello")
    memory.add_assistant_message(actor_id="U123", session_id="thread-1", text="Hi!")
    messages = memory.get_conversation_history(actor_id="U123", session_id="thread-1", max_turns=20)
    records = memory.search_long_term(query="user preferences", actor_id="U123")

Usage (local dev):
    memory = LocalMemory()
    # Same interface, in-memory storage
"""

from __future__ import annotations

import logging
import os
import re
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
        session_id: str | None = None,
    ) -> list[MemoryRecord]:
        """Semantic search over long-term memory records.

        Args:
            query: Search query for semantic matching.
            namespace_prefix: Namespace prefix to search within.
            top_k: Maximum number of results.
            strategy_id: Filter by specific strategy.
            actor_id: Required for AgentCoreMemory. Scopes search to this
                actor's per-strategy namespaces.
            project: If provided alongside actor_id, scope search to a
                specific project (``/actors/{actor_id}/projects/{project}/``).
            session_id: Optional session ID for session-scoped templates.
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

        self._region = region or os.environ.get("PLATO_REGION", "us-west-2")

        try:
            from bedrock_agentcore.memory import MemoryClient

            self._client = MemoryClient(region_name=self._region)
            self._use_sdk = True
        except ImportError:
            import warnings

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
            self._client = boto3.client("bedrock-agentcore", region_name=self._region)
            self._use_sdk = False

        self._strategy_templates: list[dict[str, str]] | None = None

    # ------------------------------------------------------------------
    # Strategy namespace template loading
    # ------------------------------------------------------------------

    def _load_strategy_templates(self) -> list[dict[str, str]]:
        """Lazily load strategy namespace templates from AgentCore get_memory.

        Returns a list of dicts: [{"strategyId": ..., "namespace": ...}, ...]
        Cached per instance after first call.
        """
        if self._strategy_templates is not None:
            return self._strategy_templates

        try:
            import boto3
            ctrl = boto3.client("bedrock-agentcore-control", region_name=self._region)
            resp = ctrl.get_memory(memoryId=self._memory_id)
            # Response shape: {"memory": {"strategies": [...]}, ...}
            # Older shape: {"strategies": [...]} — keep both for safety.
            mem = resp.get("memory") if isinstance(resp.get("memory"), dict) else resp
            strategies = mem.get("strategies", []) if isinstance(mem, dict) else []
            templates: list[dict[str, str]] = []
            for s in strategies:
                sid = (
                    s.get("strategyId")
                    or s.get("memoryStrategyId")
                    or ""
                )
                # Real shape: "namespaces" / "namespaceTemplates" are list[str].
                # Legacy shape: "namespace" / "namespaceTemplate" is str.
                ns_list = (
                    s.get("namespaces")
                    or s.get("namespaceTemplates")
                    or []
                )
                ns_single = s.get("namespace") or s.get("namespaceTemplate") or ""
                ns_values = list(ns_list) if ns_list else ([ns_single] if ns_single else [])
                for ns in ns_values:
                    if sid and ns:
                        templates.append({"strategyId": sid, "namespace": ns})
            self._strategy_templates = templates
            logger.info(
                "Loaded %d strategy namespace templates for memory %s",
                len(templates), self._memory_id,
            )
            return templates
        except Exception:
            logger.error(
                "Failed to load strategy templates from get_memory", exc_info=True,
            )
            self._strategy_templates = []
            return []

    # ------------------------------------------------------------------
    # Namespace resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_namespace(
        template: str,
        actor_id: str,
        session_id: str | None = None,
        strategy_id: str | None = None,
    ) -> str:
        """Substitute placeholders in a namespace template.

        Supported placeholders: {actorId}, {memoryStrategyId}, {sessionId}.
        If session_id is None and the template contains {sessionId}, the
        trailing {sessionId}/ segment is dropped to achieve actor-level
        (cross-session) isolation.
        """
        ns = template
        ns = ns.replace("{actorId}", actor_id)
        if strategy_id:
            ns = ns.replace("{memoryStrategyId}", strategy_id)
        if session_id:
            ns = ns.replace("{sessionId}", session_id)
        elif "{sessionId}" in ns:
            ns = re.sub(r"\{sessionId\}/?\s*$", "", ns)
            ns = re.sub(r"\{sessionId\}", "", ns)
        return ns

    @staticmethod
    def _record_belongs_to_actor(
        record_namespaces: list[str],
        allowed_prefixes: list[str],
    ) -> bool:
        """Return True if at least one record namespace starts with an allowed prefix."""
        for rns in record_namespaces:
            for prefix in allowed_prefixes:
                if rns.startswith(prefix):
                    return True
        return False

    @staticmethod
    def _project_namespace(actor_id: str, project: str) -> str:
        """Build a namespace scoped to a specific project for an actor."""
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
        session_id: str | None = None,
    ) -> list[MemoryRecord]:
        """Semantic search over long-term memory records.

        Issues one ``retrieve_memory_records`` call per strategy namespace
        template, substituting ``{actorId}`` (and ``{memoryStrategyId}``,
        ``{sessionId}``) to scope each call to the requesting actor.  A
        defensive post-filter drops any record whose namespace does not
        prefix-match the expected actor namespace.

        Args:
            actor_id: **Required** (non-empty, not ``"default"``).
            project: Optional project scope shortcut.
            session_id: Optional — substituted into templates that use
                ``{sessionId}``.  When absent, the ``{sessionId}/`` segment
                is dropped so the search is actor-level (cross-session).
        """
        if not actor_id or actor_id == "default":
            logger.error(
                "search_long_term called without a valid actor_id (got %r). "
                "Refusing to search — this would leak data across actors.",
                actor_id,
            )
            return []

        if project:
            return self._search_project_namespace(
                query=query, actor_id=actor_id, project=project,
                top_k=top_k, strategy_id=strategy_id,
            )

        try:
            templates = self._load_strategy_templates()
            if not templates:
                logger.warning(
                    "No strategy templates loaded — falling back to safe "
                    "empty result for actor %s", actor_id,
                )
                return []

            all_records: list[MemoryRecord] = []
            allowed_prefixes: list[str] = []

            for tmpl in templates:
                sid = tmpl["strategyId"]
                if strategy_id and sid != strategy_id:
                    continue
                ns = self._resolve_namespace(
                    tmpl["namespace"],
                    actor_id=actor_id,
                    session_id=session_id,
                    strategy_id=sid,
                )
                if ns == "/" or not ns:
                    logger.error(
                        "MEMORY LEAK BLOCKED: resolved namespace is root "
                        "for strategy %s, actor %s — skipping", sid, actor_id,
                    )
                    continue
                allowed_prefixes.append(ns)

                records = self._retrieve_for_namespace(
                    ns=ns, query=query, top_k=top_k, strategy_id=sid,
                )
                all_records.extend(records)

            pre_filter_count = len(all_records)
            all_records = [
                r for r in all_records
                if self._record_belongs_to_actor(r.namespaces, allowed_prefixes)
            ]
            dropped = pre_filter_count - len(all_records)
            if dropped:
                logger.error(
                    "MEMORY LEAK BLOCKED: post-filter dropped %d record(s) "
                    "that did not match actor %s namespaces %s",
                    dropped, actor_id, allowed_prefixes,
                )

            seen: set[str] = set()
            deduped: list[MemoryRecord] = []
            for r in sorted(all_records, key=lambda x: x.score, reverse=True):
                if r.record_id not in seen:
                    seen.add(r.record_id)
                    deduped.append(r)

            result = deduped[:top_k]
            logger.debug(
                "Found %d long-term records for query (actor=%s): %s",
                len(result), actor_id, query[:50],
            )
            return result

        except Exception:
            logger.error(
                "Failed to search long-term memory", exc_info=True,
            )
            return []

    def _retrieve_for_namespace(
        self,
        ns: str,
        query: str,
        top_k: int,
        strategy_id: str | None = None,
    ) -> list[MemoryRecord]:
        """Issue a single retrieve_memory_records call and parse results."""
        try:
            if self._use_sdk:
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
            return records
        except Exception:
            logger.error(
                "Failed to retrieve records for namespace %s", ns, exc_info=True,
            )
            return []

    def _search_project_namespace(
        self,
        query: str,
        actor_id: str,
        project: str,
        top_k: int,
        strategy_id: str | None = None,
    ) -> list[MemoryRecord]:
        """Project-scoped search — uses a single known namespace pattern."""
        ns = self._project_namespace(actor_id, project)
        return self._retrieve_for_namespace(
            ns=ns, query=query, top_k=top_k, strategy_id=strategy_id,
        )


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
        session_id: str | None = None,
    ) -> list[MemoryRecord]:
        """Simple substring search across all stored turns (dev fallback).

        If actor_id is provided, only searches turns from that actor's sessions.
        The project and session_id parameters are accepted for interface
        compatibility but are not used in the local implementation.
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
