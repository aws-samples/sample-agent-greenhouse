"""MemoryAccessGuard — validates memory retrieval requests to prevent cross-user access.

Provides security validation for memory namespace access patterns to ensure
users can only access their own memory data and prevent unauthorized cross-user
memory retrieval.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MemoryAccessViolation(Exception):
    """Exception raised when a memory access violates security policies."""
    pass


class MemoryAccessGuard:
    """Guard that validates memory retrieval requests for security.

    Enforces namespace-based access control to prevent cross-user data access.
    Used by MemoryHook before any Long-Term Memory (LTM) search operations.

    Security Rules:
    1. REJECT any retrieval where namespace does not include {actorId} or concrete actor_id
    2. REJECT any retrieval with namespace "/" (root — searches ALL users)
    3. ALLOW retrievals within user's own namespace or properly scoped namespaces

    Args:
        strict_mode: If True, raises exceptions on violations. If False, logs warnings.
    """

    def __init__(self, strict_mode: bool = True) -> None:
        self.strict_mode = strict_mode
        logger.info("MemoryAccessGuard initialized: strict_mode=%s", strict_mode)

    def validate_namespace(self, namespace: str, actor_id: str) -> bool:
        """Validate that a namespace access is allowed for the given actor.

        Args:
            namespace: The namespace being accessed (e.g., "user123/session456", "/", "global").
            actor_id: The ID of the user/actor making the request.

        Returns:
            True if access is allowed, False if blocked.

        Raises:
            MemoryAccessViolation: If strict_mode=True and access is denied.
        """
        if not namespace:
            # Empty namespace is treated as no scoping - potentially dangerous
            return self._handle_violation(
                f"Empty namespace not allowed",
                namespace=namespace,
                actor_id=actor_id
            )

        if namespace == "/":
            # Root namespace allows access to ALL users - block this
            return self._handle_violation(
                f"Root namespace '/' access denied - would expose all user data",
                namespace=namespace,
                actor_id=actor_id
            )

        if not actor_id:
            # No actor ID means we can't validate user scope
            return self._handle_violation(
                f"Cannot validate namespace '{namespace}' - missing actor_id",
                namespace=namespace,
                actor_id=actor_id
            )

        # Check for template placeholders that would be resolved to actor_id
        if "{actorId}" in namespace or "{actor_id}" in namespace:
            logger.debug("Access allowed: namespace '%s' contains actor template", namespace)
            return True

        # Check for shared/public spaces (but prevent path traversal)
        if (namespace.startswith("shared/") or namespace.startswith("public/")) and ".." not in namespace:
            logger.debug("Access allowed: namespace '%s' is shared/public", namespace)
            return True

        # Check if namespace contains the actor_id as a complete path component
        # This prevents partial matches like "user123x" matching "user123"
        namespace_parts = namespace.split("/")
        actor_parts = actor_id.split("/") if "/" in actor_id else [actor_id]

        # Check if any part of the namespace exactly matches the actor_id
        for ns_part in namespace_parts:
            if ns_part == actor_id:
                logger.debug("Access allowed: namespace '%s' contains exact actor_id '%s'", namespace, actor_id)
                return True

        # Check if the namespace starts with actor_id/ (user's own namespace)
        if namespace.startswith(f"{actor_id}/"):
            logger.debug("Access allowed: namespace '%s' starts with actor_id '%s/'", namespace, actor_id)
            return True

        # Namespace doesn't contain user ID - potential cross-user access
        return self._handle_violation(
            f"Cross-user access denied: namespace '{namespace}' does not include actor '{actor_id}'",
            namespace=namespace,
            actor_id=actor_id
        )

    def validate_retrieval_request(
        self,
        namespace: str,
        actor_id: str,
        query: str | None = None,
        metadata: dict[str, Any] | None = None
    ) -> bool:
        """Validate a complete memory retrieval request.

        Args:
            namespace: The namespace being accessed.
            actor_id: The ID of the user/actor making the request.
            query: The search query being executed (optional, for logging).
            metadata: Additional request metadata (optional).

        Returns:
            True if the request is allowed, False if blocked.

        Raises:
            MemoryAccessViolation: If strict_mode=True and access is denied.
        """
        # Primary validation: namespace access control
        if not self.validate_namespace(namespace, actor_id):
            return False

        # Additional validations can be added here:
        # - Query content filtering
        # - Rate limiting
        # - Time-based access controls

        logger.debug(
            "Memory retrieval validated: namespace='%s', actor='%s', query='%s'",
            namespace,
            actor_id,
            query[:50] + "..." if query and len(query) > 50 else query
        )

        return True

    def _handle_violation(
        self,
        message: str,
        namespace: str,
        actor_id: str
    ) -> bool:
        """Handle a security violation.

        Args:
            message: Description of the violation.
            namespace: The namespace that was accessed.
            actor_id: The actor that attempted access.

        Returns:
            False (access denied).

        Raises:
            MemoryAccessViolation: If strict_mode=True.
        """
        full_message = f"Memory access violation: {message}"

        if self.strict_mode:
            logger.error(full_message)
            raise MemoryAccessViolation(full_message)
        else:
            logger.warning(full_message)
            return False

    def validate_retrieval_config(self, config: dict[str, Any], actor_id: str) -> dict[str, Any]:
        """Filter a retrieval config to remove unsafe namespaces.

        Examines namespace-related fields in the config and strips any that
        would violate access control rules (root namespace, cross-user, etc.).

        Args:
            config: Retrieval configuration dict. Expected keys include
                ``namespaces`` (list[str]) and/or ``namespace`` (str).
            actor_id: The actor making the retrieval request.

        Returns:
            A new config dict with unsafe namespaces removed. If all
            namespaces are unsafe, returns config with an empty namespace list.
        """
        filtered = dict(config)

        # Filter list of namespaces
        if "namespaces" in filtered and isinstance(filtered["namespaces"], list):
            safe: list[str] = []
            for ns in filtered["namespaces"]:
                if isinstance(ns, str) and self._is_namespace_safe(ns, actor_id):
                    safe.append(ns)
                else:
                    logger.warning(
                        "Removed unsafe namespace %r from retrieval config for actor %r",
                        ns,
                        actor_id,
                    )
            filtered["namespaces"] = safe

        # Filter single namespace field
        if "namespace" in filtered and isinstance(filtered["namespace"], str):
            if not self._is_namespace_safe(filtered["namespace"], actor_id):
                logger.warning(
                    "Removed unsafe namespace %r from retrieval config for actor %r",
                    filtered["namespace"],
                    actor_id,
                )
                filtered["namespace"] = ""

        return filtered

    def _is_namespace_safe(self, namespace: str, actor_id: str) -> bool:
        """Check namespace safety without raising or logging violations.

        Uses the same rules as validate_namespace but returns bool only.
        """
        guard = MemoryAccessGuard(strict_mode=False)
        return guard.validate_namespace(namespace, actor_id)

    def get_security_summary(self) -> dict[str, Any]:
        """Get a summary of current security configuration.

        Returns:
            Dictionary containing security settings and statistics.
        """
        return {
            "strict_mode": self.strict_mode,
            "rules": [
                "Namespace must include actor_id or template placeholder",
                "Root namespace '/' is blocked",
                "Empty namespace is blocked",
                "shared/ and public/ namespaces are allowed",
            ],
        }


# Convenience function for simple validation
def validate_namespace(namespace: str, actor_id: str) -> bool:
    """Convenience function for simple namespace validation.

    Args:
        namespace: The namespace to validate.
        actor_id: The actor ID to validate against.

    Returns:
        True if access is allowed, False otherwise.
    """
    guard = MemoryAccessGuard(strict_mode=False)
    return guard.validate_namespace(namespace, actor_id)