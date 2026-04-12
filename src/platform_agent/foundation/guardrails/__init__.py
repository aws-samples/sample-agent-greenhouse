"""Cedar Policy Guardrails — policy engine for agent authorization.

Provides a Cedar-based policy evaluation engine that controls what
agents can and cannot do. Policies are expressed in Cedar policy language
and evaluated before agent actions are executed.

Key concepts:
- Policy: A Cedar policy statement (permit/forbid)
- PolicyStore: Collection of policies
- PolicyEngine: Evaluates authorization requests against policies
- AuthorizationRequest: What an agent wants to do
- AuthorizationDecision: Allow or Deny with reasons
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Decision(Enum):
    """Authorization decision."""

    ALLOW = "allow"
    DENY = "deny"


class Effect(Enum):
    """Policy effect."""

    PERMIT = "permit"
    FORBID = "forbid"


@dataclass
class Policy:
    """A Cedar-style policy statement.

    Simplified Cedar policy that evaluates principal, action, and resource
    against conditions.

    Example Cedar equivalent:
        permit(
            principal == Agent::"design-advisor",
            action == Action::"read",
            resource == Resource::"codebase"
        );
    """

    policy_id: str
    effect: Effect
    description: str = ""
    principal_type: str = ""  # e.g., "Agent", "*"
    principal_id: str = ""    # e.g., "design-advisor", "*"
    action: str = ""          # e.g., "read", "write", "execute", "*"
    resource_type: str = ""   # e.g., "File", "API", "*"
    resource_id: str = ""     # e.g., "codebase/*", "*"
    conditions: dict[str, Any] = field(default_factory=dict)

    def matches(self, request: AuthorizationRequest) -> bool:
        """Check if this policy applies to the given request.

        Uses wildcard matching — "*" matches anything.
        """
        if self.principal_type and self.principal_type != "*":
            if request.principal_type != self.principal_type:
                return False
        if self.principal_id and self.principal_id != "*":
            if request.principal_id != self.principal_id:
                return False
        if self.action and self.action != "*":
            if request.action != self.action:
                return False
        if self.resource_type and self.resource_type != "*":
            if request.resource_type != self.resource_type:
                return False
        if self.resource_id and self.resource_id != "*":
            # Simple prefix matching for paths like "codebase/*"
            if self.resource_id.endswith("/*"):
                prefix = self.resource_id[:-2]
                if not request.resource_id.startswith(prefix):
                    return False
            elif request.resource_id != self.resource_id:
                return False

        # Evaluate conditions
        for key, expected in self.conditions.items():
            actual = request.context.get(key)
            if actual != expected:
                return False

        return True

    def to_cedar(self) -> str:
        """Format as Cedar-like policy string."""
        parts = [f"{self.effect.value}("]
        if self.principal_id:
            parts.append(f'  principal == {self.principal_type}::"{self.principal_id}",')
        if self.action:
            parts.append(f'  action == Action::"{self.action}",')
        if self.resource_id:
            parts.append(f'  resource == {self.resource_type}::"{self.resource_id}"')
        parts.append(");")
        return "\n".join(parts)


@dataclass
class AuthorizationRequest:
    """What an agent wants to do.

    Describes the principal (who), action (what), resource (on what),
    and context (additional conditions).
    """

    principal_type: str  # e.g., "Agent"
    principal_id: str    # e.g., "design-advisor"
    action: str          # e.g., "read", "write", "execute"
    resource_type: str   # e.g., "File", "API"
    resource_id: str     # e.g., "/src/main.py"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthorizationDecision:
    """Result of a policy evaluation."""

    decision: Decision
    reasons: list[str] = field(default_factory=list)
    matching_policies: list[str] = field(default_factory=list)

    @property
    def is_allowed(self) -> bool:
        return self.decision == Decision.ALLOW


class PolicyStore:
    """Collection of Cedar policies.

    Manages policies and provides query methods.
    """

    def __init__(self) -> None:
        self._policies: dict[str, Policy] = {}

    def add_policy(self, policy: Policy) -> None:
        """Add a policy to the store."""
        self._policies[policy.policy_id] = policy
        logger.debug("Added policy: %s (%s)", policy.policy_id, policy.effect.value)

    def remove_policy(self, policy_id: str) -> bool:
        """Remove a policy. Returns True if it existed."""
        if policy_id in self._policies:
            del self._policies[policy_id]
            return True
        return False

    def get_policy(self, policy_id: str) -> Policy | None:
        """Get a policy by ID."""
        return self._policies.get(policy_id)

    def list_policies(self) -> list[Policy]:
        """List all policies."""
        return list(self._policies.values())

    @property
    def policy_count(self) -> int:
        return len(self._policies)


class PolicyEngine:
    """Evaluates authorization requests against Cedar policies.

    Follows Cedar's evaluation semantics:
    - Default deny (no matching policy = deny)
    - Explicit forbid overrides permit
    - At least one permit required for allow

    Usage:
        engine = PolicyEngine(policy_store)
        decision = engine.evaluate(request)
        if decision.is_allowed:
            # proceed
    """

    def __init__(self, store: PolicyStore) -> None:
        self._store = store

    def evaluate(self, request: AuthorizationRequest) -> AuthorizationDecision:
        """Evaluate an authorization request against all policies.

        Cedar evaluation rules:
        1. Find all matching policies
        2. If any matching FORBID → DENY
        3. If at least one matching PERMIT → ALLOW
        4. No matching policies → DENY (default deny)
        """
        matching_permits: list[str] = []
        matching_forbids: list[str] = []
        reasons: list[str] = []

        for policy in self._store.list_policies():
            if policy.matches(request):
                if policy.effect == Effect.FORBID:
                    matching_forbids.append(policy.policy_id)
                    reasons.append(
                        f"Denied by policy {policy.policy_id}: {policy.description}"
                    )
                elif policy.effect == Effect.PERMIT:
                    matching_permits.append(policy.policy_id)

        # Cedar semantics: forbid overrides permit
        if matching_forbids:
            return AuthorizationDecision(
                decision=Decision.DENY,
                reasons=reasons,
                matching_policies=matching_forbids,
            )

        if matching_permits:
            return AuthorizationDecision(
                decision=Decision.ALLOW,
                reasons=[f"Allowed by {len(matching_permits)} policy(ies)"],
                matching_policies=matching_permits,
            )

        # Default deny
        return AuthorizationDecision(
            decision=Decision.DENY,
            reasons=["No matching permit policy (default deny)"],
            matching_policies=[],
        )


def create_default_policies() -> PolicyStore:
    """Create a default policy store with common agent guardrails.

    Default policies:
    - Agents can read any file
    - Agents can write to project directories
    - Agents cannot execute destructive commands
    - Agents cannot access secrets directly
    """
    store = PolicyStore()

    store.add_policy(Policy(
        policy_id="default-read",
        effect=Effect.PERMIT,
        description="Agents can read files",
        principal_type="Agent",
        principal_id="*",
        action="read",
        resource_type="File",
        resource_id="*",
    ))

    store.add_policy(Policy(
        policy_id="default-write",
        effect=Effect.PERMIT,
        description="Agents can write to project directories",
        principal_type="Agent",
        principal_id="*",
        action="write",
        resource_type="File",
        resource_id="project/*",
    ))

    store.add_policy(Policy(
        policy_id="deny-secrets",
        effect=Effect.FORBID,
        description="Agents cannot access secrets directly",
        principal_type="Agent",
        principal_id="*",
        action="read",
        resource_type="File",
        resource_id="secrets/*",
    ))

    store.add_policy(Policy(
        policy_id="deny-destructive",
        effect=Effect.FORBID,
        description="Agents cannot execute destructive commands",
        principal_type="Agent",
        principal_id="*",
        action="execute",
        resource_type="Command",
        resource_id="rm",
    ))

    return store
