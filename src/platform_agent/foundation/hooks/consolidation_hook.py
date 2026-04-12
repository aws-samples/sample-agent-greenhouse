"""ConsolidationHook — consolidates memory events into higher-level insights (DEPRECATED).

.. deprecated::
    This hook is **deprecated** and was never enabled in the production
    entrypoint.  It is retained solely for backward compatibility — the harness
    configuration can still reference it.  Do **not** add new functionality
    here; memory consolidation is handled by AgentCore strategies server-side.

Original design inspired by Claude Code's autoDream pattern
(services/autoDream/).  Implements a three-trigger gate (time, count, lock)
before running consolidation.

When triggered, retrieves recent memory records, consolidates them into
higher-level insights, and writes back as a consolidated event.

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from platform_agent.foundation.memory import WorkspaceMemory

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import BeforeInvocationEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



# Gate defaults (matching CC autoDream pattern).
_DEFAULT_TIME_GATE_SECONDS = 86400  # 24 hours
_DEFAULT_COUNT_GATE = 10  # minimum new events since last consolidation

# Consolidation state file within workspace memory.
_CONSOLIDATION_STATE_FILE = "consolidation_state.json"


class ConsolidationHook(HookBase):
    """Hook that consolidates memory events into higher-level insights.

    Implements a three-trigger gate inspired by Claude Code's autoDream:

    1. **Time gate**: Minimum 24h since last consolidation.
    2. **Count gate**: Minimum 10 new events since last consolidation.
    3. **Lock gate**: File-based lock to prevent concurrent consolidation.

    When all three gates pass, retrieves recent memory records, consolidates
    them into higher-level insights, and writes them back as a consolidated
    event.

    Args:
        workspace_dir: Path to workspace directory for state persistence.
        time_gate_seconds: Minimum seconds between consolidations. Default: 86400.
        count_gate: Minimum new events before consolidation. Default: 10.
        consolidation_callback: Optional callable(memories: list[str]) -> str
            that produces a consolidated insight from a list of memory texts.
    """

    def __init__(
        self,
        workspace_dir: str | None = None,
        time_gate_seconds: int = _DEFAULT_TIME_GATE_SECONDS,
        count_gate: int = _DEFAULT_COUNT_GATE,
        consolidation_callback: object | None = None,
        namespace_template: str = "",
        namespace_vars: dict[str, str] | None = None,
        ttl_days: int | None = None,
    ) -> None:
        self._namespace_template = namespace_template
        self._namespace_vars = namespace_vars or {}
        self.ttl_days = ttl_days

        # Compute resolved namespace from template + vars
        self.namespace = self._compute_namespace()

        # Effective workspace path — all internal methods use self._workspace_dir,
        # so assigning the namespace-prefixed path here propagates automatically.
        effective_workspace = self._effective_workspace(workspace_dir)

        self.workspace_memory: WorkspaceMemory | None = None
        self._workspace_dir = effective_workspace
        if effective_workspace:
            self.workspace_memory = WorkspaceMemory(workspace_dir=effective_workspace)

        self._time_gate_seconds = time_gate_seconds
        self._count_gate = count_gate
        self._consolidation_callback = consolidation_callback
        self._event_count_since_last = 0

        # Load persisted state
        self._state = self._load_state()

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
            registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)

    def on_before_invocation(self, event) -> None:
        """Check consolidation gates before each invocation.

        Args:
            event: BeforeInvocationEvent with writable messages field.
        """
        self._event_count_since_last += 1

        if self._should_consolidate():
            self._run_consolidation()

    def _should_consolidate(self) -> bool:
        """Check all three gates to determine if consolidation should run.

        Returns:
            True if all gates pass.
        """
        # Gate 1: Time gate
        last_consolidation = self._state.get("last_consolidation_timestamp", 0)
        elapsed = time.time() - last_consolidation
        if elapsed < self._time_gate_seconds:
            return False

        # Gate 2: Count gate
        events_since = self._state.get("events_since_last", 0) + self._event_count_since_last
        if events_since < self._count_gate:
            return False

        # Gate 3: Lock gate
        if not self._acquire_lock():
            return False

        return True

    def _acquire_lock(self) -> bool:
        """Acquire a file-based lock to prevent concurrent consolidation.

        Returns:
            True if lock acquired successfully.
        """
        if not self._workspace_dir:
            return True  # No workspace = in-memory only, no contention

        lock_path = Path(self._workspace_dir) / ".consolidation.lock"
        try:
            if lock_path.exists():
                # Check if lock is stale (older than 5 minutes)
                lock_age = time.time() - lock_path.stat().st_mtime
                if lock_age < 300:  # 5 minutes
                    return False
                # Stale lock — remove it
                lock_path.unlink(missing_ok=True)

            lock_path.write_text(str(os.getpid()))
            return True
        except OSError:
            logger.warning("Failed to acquire consolidation lock", exc_info=True)
            return False

    def _release_lock(self) -> None:
        """Release the file-based consolidation lock."""
        if not self._workspace_dir:
            return
        lock_path = Path(self._workspace_dir) / ".consolidation.lock"
        lock_path.unlink(missing_ok=True)

    def _run_consolidation(self) -> None:
        """Run the memory consolidation process."""
        try:
            memories = self._gather_recent_memories()
            if not memories:
                return

            insight = self._consolidate(memories)
            if insight:
                self._store_consolidated(insight)

            # Update state
            self._state["last_consolidation_timestamp"] = time.time()
            self._state["events_since_last"] = 0
            self._event_count_since_last = 0
            self._state["consolidation_count"] = self._state.get("consolidation_count", 0) + 1
            self._save_state()

        except Exception:
            logger.error("Consolidation failed", exc_info=True)
        finally:
            self._release_lock()

    def _gather_recent_memories(self) -> list[str]:
        """Gather recent memory entries from workspace memory.

        Returns:
            List of memory text strings.
        """
        if not self.workspace_memory:
            return []

        memories: list[str] = []
        memory_dir = Path(self._workspace_dir or "") / "memory" / "extracted"

        if not memory_dir.exists():
            return []

        # Read recent memory files (sorted by name, which includes timestamp)
        files = sorted(memory_dir.glob("*.json"), reverse=True)[:50]
        for f in files:
            try:
                data = json.loads(f.read_text())
                content = data.get("content", "")
                if content:
                    memories.append(content)
            except (json.JSONDecodeError, OSError):
                continue

        return memories

    def _consolidate(self, memories: list[str]) -> str:
        """Consolidate a list of memory texts into a higher-level insight.

        Uses the consolidation callback if provided, otherwise falls back to
        a simple concatenation summary.

        Args:
            memories: List of memory text strings.

        Returns:
            Consolidated insight text.
        """
        if self._consolidation_callback and callable(self._consolidation_callback):
            try:
                result = self._consolidation_callback(memories)
                if isinstance(result, str):
                    return result
            except Exception:
                logger.warning("Consolidation callback failed", exc_info=True)

        # Simple fallback: concatenate with deduplication
        unique = list(dict.fromkeys(memories))  # preserve order, remove dupes
        if not unique:
            return ""
        return "Consolidated insights:\n" + "\n".join(f"- {m}" for m in unique[:20])

    def _store_consolidated(self, insight: str) -> None:
        """Store a consolidated insight to workspace memory directory.

        Writes JSON files to {workspace}/memory/consolidated/.

        Args:
            insight: The consolidated insight text.
        """
        if not self._workspace_dir:
            return

        timestamp = datetime.now(timezone.utc).isoformat()
        safe_ts = timestamp.replace(":", "-")
        consolidated_dir = Path(self._workspace_dir) / "memory" / "consolidated"
        consolidated_dir.mkdir(parents=True, exist_ok=True)

        filepath = consolidated_dir / f"{safe_ts}.json"
        try:
            filepath.write_text(
                json.dumps(
                    {
                        "type": "consolidated_insight",
                        "timestamp": timestamp,
                        "content": insight,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            logger.info("Stored consolidated insight: %s", insight[:80])
        except Exception:
            logger.warning("Failed to store consolidated insight", exc_info=True)

    def _load_state(self) -> dict:
        """Load consolidation gate state from workspace file.

        Returns:
            State dict with gate values.
        """
        if not self._workspace_dir:
            return {"last_consolidation_timestamp": 0, "events_since_last": 0, "consolidation_count": 0}

        state_path = Path(self._workspace_dir) / _CONSOLIDATION_STATE_FILE
        try:
            if state_path.is_file():
                content = state_path.read_text(encoding="utf-8")
                if content:
                    return json.loads(content)
        except (json.JSONDecodeError, OSError):
            pass

        return {"last_consolidation_timestamp": 0, "events_since_last": 0, "consolidation_count": 0}

    def _save_state(self) -> None:
        """Save consolidation gate state to workspace file."""
        if not self._workspace_dir:
            return

        state_path = Path(self._workspace_dir) / _CONSOLIDATION_STATE_FILE
        try:
            state_path.write_text(
                json.dumps(self._state, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("Failed to save consolidation state", exc_info=True)

    def get_state(self) -> dict:
        """Return the current consolidation gate state.

        Returns:
            Dict with last_consolidation_timestamp, events_since_last,
            consolidation_count.
        """
        return dict(self._state)

    def increment_event_count(self) -> None:
        """Manually increment the event count for testing/external use."""
        self._event_count_since_last += 1
