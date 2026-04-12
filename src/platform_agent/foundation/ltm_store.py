"""LTM Store — cross-session key-value store for long-term memory.

Provides an ABC and two concrete implementations:
- LocalFileLTMStore: JSON file-based, for local / development use.
- AgentCoreLTMStore: Stub for future AgentCore Memory integration.

All operations validate namespace access via MemoryAccessGuard.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from platform_agent.foundation.memory_access_guard import MemoryAccessGuard

logger = logging.getLogger(__name__)


class LTMStore(ABC):
    """Abstract base class for cross-session LTM key-value stores."""

    @abstractmethod
    def put(self, namespace: str, key: str, value: Any, *, actor_id: str) -> None:
        """Store a value under the given namespace and key.

        Args:
            namespace: Namespace for scoping (e.g., "/plato/user123/").
            key: Unique key within the namespace.
            value: JSON-serializable value to store.
            actor_id: The actor performing the operation (for access control).
        """

    @abstractmethod
    def get(self, namespace: str, key: str, *, actor_id: str) -> Any | None:
        """Retrieve a value by namespace and key.

        Args:
            namespace: Namespace for scoping.
            key: Key to retrieve.
            actor_id: The actor performing the operation.

        Returns:
            The stored value, or None if not found.
        """

    @abstractmethod
    def delete(self, namespace: str, key: str, *, actor_id: str) -> bool:
        """Delete a value by namespace and key.

        Args:
            namespace: Namespace for scoping.
            key: Key to delete.
            actor_id: The actor performing the operation.

        Returns:
            True if deleted, False if key was not found.
        """

    @abstractmethod
    def list_keys(self, namespace: str, *, actor_id: str) -> list[str]:
        """List all keys within a namespace.

        Args:
            namespace: Namespace to list.
            actor_id: The actor performing the operation.

        Returns:
            List of key names.
        """


class LocalFileLTMStore(LTMStore):
    """JSON file-based LTM store for local / development use.

    Stores each key as a separate JSON file:
        {base_dir}/{namespace_hash}/{key}.json

    Each file contains:
        {"value": <user-value>, "updated_at": <ISO-8601>, "namespace": <ns>}
    """

    def __init__(self, base_dir: str, *, strict_mode: bool = False) -> None:
        self._base_dir = base_dir
        self._guard = MemoryAccessGuard(strict_mode=strict_mode)

    def _namespace_dir(self, namespace: str) -> str:
        ns_hash = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[:16]
        return os.path.join(self._base_dir, ns_hash)

    def _key_path(self, namespace: str, key: str) -> str:
        safe_key = key.replace("/", "_").replace("\\", "_")
        return os.path.join(self._namespace_dir(namespace), f"{safe_key}.json")

    def _check_access(self, namespace: str, actor_id: str) -> bool:
        return self._guard.validate_namespace(namespace, actor_id)

    def put(self, namespace: str, key: str, value: Any, *, actor_id: str) -> None:
        if not self._check_access(namespace, actor_id):
            logger.warning(
                "LTM put blocked: namespace=%r actor=%r key=%r", namespace, actor_id, key
            )
            return

        path = self._key_path(namespace, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        payload = {
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "namespace": namespace,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def get(self, namespace: str, key: str, *, actor_id: str) -> Any | None:
        if not self._check_access(namespace, actor_id):
            logger.warning(
                "LTM get blocked: namespace=%r actor=%r key=%r", namespace, actor_id, key
            )
            return None

        path = self._key_path(namespace, key)
        if not os.path.isfile(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("value")

    def delete(self, namespace: str, key: str, *, actor_id: str) -> bool:
        if not self._check_access(namespace, actor_id):
            logger.warning(
                "LTM delete blocked: namespace=%r actor=%r key=%r", namespace, actor_id, key
            )
            return False

        path = self._key_path(namespace, key)
        if not os.path.isfile(path):
            return False

        os.remove(path)
        return True

    def list_keys(self, namespace: str, *, actor_id: str) -> list[str]:
        if not self._check_access(namespace, actor_id):
            logger.warning(
                "LTM list_keys blocked: namespace=%r actor=%r", namespace, actor_id
            )
            return []

        ns_dir = self._namespace_dir(namespace)
        if not os.path.isdir(ns_dir):
            return []

        keys: list[str] = []
        for fname in sorted(os.listdir(ns_dir)):
            if fname.endswith(".json"):
                keys.append(fname[: -len(".json")])
        return keys


class AgentCoreLTMStore(LTMStore):
    """Stub for future AgentCore Memory-backed LTM store.

    All operations raise NotImplementedError until the AgentCore Memory
    API integration is complete.
    """

    def put(self, namespace: str, key: str, value: Any, *, actor_id: str) -> None:
        raise NotImplementedError("AgentCoreLTMStore is not yet implemented")

    def get(self, namespace: str, key: str, *, actor_id: str) -> Any | None:
        raise NotImplementedError("AgentCoreLTMStore is not yet implemented")

    def delete(self, namespace: str, key: str, *, actor_id: str) -> bool:
        raise NotImplementedError("AgentCoreLTMStore is not yet implemented")

    def list_keys(self, namespace: str, *, actor_id: str) -> list[str]:
        raise NotImplementedError("AgentCoreLTMStore is not yet implemented")
