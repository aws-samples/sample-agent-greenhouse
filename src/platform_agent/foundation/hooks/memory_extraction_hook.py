"""MemoryExtractionHook — extracts structured memories after each invocation (DEPRECATED).

.. deprecated::
    This hook is **deprecated** and no longer instantiated in the active agent
    entrypoint (``enable_memory_extraction=False`` by default).  It is retained
    solely for backward compatibility — the harness factory (``agent.py``) can
    still create it from configuration.  Do **not** add new functionality here;
    long-term memory extraction is handled by the AgentCore event-based pipeline.

Original design inspired by Claude Code's extractMemories pattern
(services/extractMemories/).  After each LLM invocation, uses a lightweight
side query to extract key facts, user preferences, and decisions from the
conversation, then stores them via workspace memory.

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from platform_agent.foundation.memory import WorkspaceMemory

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import AfterInvocationEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



# System prompt for the memory extraction side query.
_EXTRACTION_PROMPT = """\
Extract key facts, user preferences, and decisions from this conversation turn.
Return a JSON array of objects with keys: "type" (fact|preference|decision), "content" (string).
Only include genuinely new information worth remembering.
If nothing notable, return an empty array [].
Keep each item under 100 words. Return at most 5 items.
Output ONLY valid JSON, no markdown fencing."""

# Maximum output tokens for the extraction side query.
_MAX_EXTRACTION_TOKENS = 500


class MemoryExtractionHook(HookBase):
    """Hook that extracts structured memories after each invocation.

    After each LLM invocation completes, this hook examines the conversation
    result and extracts key facts, user preferences, and decisions into
    structured memory entries stored in workspace memory.

    Inspired by Claude Code's extractMemories pattern.

    Args:
        workspace_dir: Path to the workspace directory for memory storage.
        extraction_callback: Optional callable(conversation_text) -> list[dict]
            for custom extraction logic. If None, memories are extracted by
            parsing the result text for structured content.
    """

    def __init__(
        self,
        workspace_dir: str | None = None,
        extraction_callback: object | None = None,
        namespace_template: str = "",
        namespace_vars: dict[str, str] | None = None,
        ttl_days: int | None = None,
    ) -> None:
        self._namespace_template = namespace_template
        self._namespace_vars = namespace_vars or {}
        self.ttl_days = ttl_days

        # Compute resolved namespace from template + vars
        self.namespace = self._compute_namespace()

        # Effective workspace path (namespace sub-path when namespace is set)
        effective_workspace = self._effective_workspace(workspace_dir)

        self.workspace_memory: WorkspaceMemory | None = None
        if effective_workspace:
            self.workspace_memory = WorkspaceMemory(workspace_dir=effective_workspace)
        self._extraction_callback = extraction_callback
        self._extracted_memories: list[dict[str, str]] = []

    def _compute_namespace(self) -> str:
        """Resolve namespace_template using namespace_vars."""
        if not self._namespace_template:
            return ""
        try:
            return self._namespace_template.format(**self._namespace_vars)
        except KeyError:
            return self._namespace_template  # keep template literal if vars missing

    def _effective_workspace(self, workspace_dir: str | None) -> str | None:
        """Return workspace_dir with namespace appended when namespace is non-empty."""
        if workspace_dir and self.namespace:
            return os.path.join(workspace_dir, self.namespace)
        return workspace_dir

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(AfterInvocationEvent, self.on_after_invocation)

    def on_after_invocation(self, event) -> None:
        """Extract memories from the invocation result.

        Args:
            event: AfterInvocationEvent with result attribute.
        """
        result_text = self._extract_result_text(event)
        if not result_text:
            return

        memories = self._extract_memories(result_text)
        if not memories:
            return

        self._extracted_memories.extend(memories)
        self._persist_memories(memories)

    def _extract_result_text(self, event) -> str:
        """Extract text content from an AfterInvocationEvent result.

        Args:
            event: The AfterInvocationEvent.

        Returns:
            Extracted text string, empty if no text found.
        """
        result = getattr(event, "result", None)
        if result is None:
            return ""

        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            content = result.get("content", [])
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    parts.append(block["text"])
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)

        return str(result)

    def _extract_memories(self, text: str) -> list[dict[str, str]]:
        """Extract structured memories from conversation text.

        Uses the extraction callback if provided, otherwise falls back to
        a simple heuristic that looks for decision/preference patterns.

        Args:
            text: The conversation text to extract from.

        Returns:
            List of memory dicts with 'type' and 'content' keys.
        """
        if self._extraction_callback and callable(self._extraction_callback):
            try:
                result = self._extraction_callback(text)
                if isinstance(result, list):
                    return [
                        m for m in result
                        if isinstance(m, dict) and "type" in m and "content" in m
                    ]
            except Exception:
                logger.warning("Memory extraction callback failed", exc_info=True)

        return self._heuristic_extract(text)

    def _heuristic_extract(self, text: str) -> list[dict[str, str]]:
        """Simple heuristic extraction when no LLM callback is available.

        Looks for decision-like and preference-like patterns in the text.

        Args:
            text: Text to extract from.

        Returns:
            List of memory dicts.
        """
        memories: list[dict[str, str]] = []
        text_lower = text.lower()

        # Look for decision patterns
        decision_markers = ["decided to ", "decision: ", "we'll go with ", "chosen approach: "]
        for marker in decision_markers:
            idx = text_lower.find(marker)
            if idx >= 0:
                # Extract up to the next sentence boundary
                start = idx
                end = text.find(".", start + len(marker))
                if end < 0:
                    end = min(start + 200, len(text))
                content = text[start:end + 1].strip()
                if content:
                    memories.append({"type": "decision", "content": content})

        # Limit to 5 memories max
        return memories[:5]

    def _persist_memories(self, memories: list[dict[str, str]]) -> None:
        """Persist extracted memories to workspace memory directory.

        Writes JSON files to {workspace}/memory/extracted/.

        Args:
            memories: List of memory dicts to persist.
        """
        if not self.workspace_memory or not memories:
            return

        ws_dir = self.workspace_memory.workspace_dir
        if not ws_dir:
            return

        timestamp = datetime.now(timezone.utc).isoformat()
        memory_dir = Path(ws_dir) / "memory" / "extracted"
        memory_dir.mkdir(parents=True, exist_ok=True)

        for i, memory in enumerate(memories):
            safe_ts = timestamp.replace(":", "-")
            filepath = memory_dir / f"{safe_ts}_{i}.json"
            try:
                filepath.write_text(
                    json.dumps({"timestamp": timestamp, **memory}, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                logger.warning(
                    "Failed to persist extracted memory: %s",
                    memory.get("content", "")[:50],
                    exc_info=True,
                )

    def get_extracted_memories(self) -> list[dict[str, str]]:
        """Return all memories extracted in this session.

        Returns:
            List of memory dicts with 'type' and 'content' keys.
        """
        return list(self._extracted_memories)

    def clear(self) -> None:
        """Clear the in-memory extracted memories list."""
        self._extracted_memories.clear()

    @staticmethod
    def get_extraction_prompt() -> str:
        """Return the system prompt used for LLM-based memory extraction.

        Returns:
            The extraction prompt string.
        """
        return _EXTRACTION_PROMPT
