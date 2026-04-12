"""Explicit memory tools — save and recall long-term memories.

Provides two Strands @tool functions that the agent can call directly:

1. save_memory — Save structured facts/preferences/decisions to LTM.
2. recall_memory — Semantic search over long-term memory.

Both tools require an AgentCoreMemory (or compatible MemoryBackend) instance
along with actor/session context. Use ``create_memory_tools()`` to create
bound tool instances.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from platform_agent.foundation.memory_access_guard import MemoryAccessGuard

logger = logging.getLogger(__name__)

try:
    from strands import tool as strands_tool
except ImportError:
    import functools

    def strands_tool(fn: Callable) -> Callable:
        """Fallback identity @tool decorator when strands is not installed."""
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)
        return wrapper


# Map user-facing category names to AgentCore strategy IDs
_CATEGORY_TO_STRATEGY: dict[str, str] = {
    "fact": "semanticKnowledge",
    "preference": "userPreferences",
    "decision": "semanticKnowledge",
    "lesson": "episodicMemory",
    "todo": "semanticKnowledge",
}

_VALID_CATEGORIES = {"fact", "preference", "decision", "lesson", "todo"}


def create_memory_tools(
    memory_backend: Any,
    actor_id: str,
    session_id: str,
    namespace: str = "",
    enable_access_guard: bool = True,
) -> list[Callable]:
    """Create bound save_memory and recall_memory tool functions.

    Returns tool functions with memory_backend, actor_id, and session_id
    captured in closure — ready to pass to the Strands Agent tools list.

    Args:
        memory_backend: An AgentCoreMemory (or compatible MemoryBackend) instance.
        actor_id: The actor/user ID for namespace isolation.
        session_id: The current session ID.
        namespace: The memory namespace for access control validation.
        enable_access_guard: Whether to enable memory access validation.

    Returns:
        List of [save_memory, recall_memory] tool functions.
    """

    # Initialize memory access guard
    access_guard = MemoryAccessGuard(strict_mode=enable_access_guard) if enable_access_guard else None

    @strands_tool
    def save_memory(content: str, category: str = "fact") -> str:
        """Save an explicit memory to long-term storage.

        Categories: fact, preference, decision, lesson, todo
        """
        if category not in _VALID_CATEGORIES:
            return (
                f"Invalid category '{category}'. "
                f"Valid categories: {', '.join(sorted(_VALID_CATEGORIES))}"
            )

        structured_text = f"[MEMORY:{category}] {content}"

        try:
            event_id = memory_backend.add_assistant_message(
                actor_id=actor_id,
                session_id=session_id,
                text=structured_text,
                metadata={"category": category, "source": "explicit_save"},
            )
            if event_id:
                logger.debug("Saved memory (category=%s): %s", category, content[:50])
                return f"Memory saved (category: {category}): {content[:100]}"
            return "Memory save attempted but no event ID returned."
        except Exception as e:
            logger.error("Failed to save memory: %s", e, exc_info=True)
            return f"Failed to save memory: {e}"

    @strands_tool
    def recall_memory(query: str, category: str = "") -> str:
        """Search long-term memory for relevant information."""
        try:
            # Validate memory access if guard is enabled
            if access_guard and namespace:
                if not access_guard.validate_retrieval_request(
                    namespace=namespace,
                    actor_id=actor_id,
                    query=query
                ):
                    return "Memory access denied: insufficient permissions for the requested namespace."

            strategy_id = None
            if category and category in _CATEGORY_TO_STRATEGY:
                strategy_id = _CATEGORY_TO_STRATEGY[category]

            records = memory_backend.search_long_term(
                query=query,
                actor_id=actor_id,
                top_k=5,
                strategy_id=strategy_id,
            )

            if not records:
                return f"No memories found for query: '{query}'"

            lines = [f"Found {len(records)} memory record(s):\n"]
            for i, record in enumerate(records, 1):
                score_str = f" (score: {record.score:.2f})" if record.score else ""
                strategy_str = f" [{record.strategy_id}]" if record.strategy_id else ""
                lines.append(f"{i}. {record.text}{score_str}{strategy_str}")

            return "\n".join(lines)
        except Exception as e:
            logger.error("Failed to recall memory: %s", e, exc_info=True)
            return f"Failed to search memory: {e}"

    return [save_memory, recall_memory]
