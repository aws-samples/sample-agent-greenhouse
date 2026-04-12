"""Platform Policy Engine — extends Cedar guardrails with platform-level policies.

Adds agent lifecycle policies (cold-start denial, rate limiting, cross-boundary
enforcement) and content filtering on top of the base PolicyEngine.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from platform_agent.foundation.guardrails import (
    AuthorizationDecision,
    AuthorizationRequest,
    Decision,
    Effect,
    Policy,
    PolicyEngine,
    PolicyStore,
)

logger = logging.getLogger(__name__)

# Patterns that indicate thinking/reasoning leaks
THINKING_LEAK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<thinking>.*?</thinking>", re.DOTALL),
    re.compile(r"<reasoning>.*?</reasoning>", re.DOTALL),
    re.compile(r"<internal>.*?</internal>", re.DOTALL),
    re.compile(r"\[INTERNAL\].*?\[/INTERNAL\]", re.DOTALL),
    re.compile(r"(?i)^(let me think|thinking:|my reasoning:)", re.MULTILINE),
]


@dataclass
class RateLimitConfig:
    """Rate limit configuration for an agent or action."""

    max_requests: int = 100
    window_seconds: float = 60.0


@dataclass
class ContentFilterResult:
    """Result of content filtering."""

    is_clean: bool = True
    filtered_text: str = ""
    patterns_found: list[str] = field(default_factory=list)


class PlatformPolicyEngine:
    """Enhanced policy engine with platform-level policies.

    Extends the base Cedar PolicyEngine with:
    - Cold-start denial: agents must be in READY state to act
    - Rate limiting: configurable request rate limits
    - Cross-boundary denial: agents cannot access other tenants
    - Content filtering: strips thinking/reasoning leak patterns
    """

    def __init__(self, store: PolicyStore | None = None) -> None:
        self._store = store or PolicyStore()
        self._base_engine = PolicyEngine(self._store)
        self._rate_limits: dict[str, RateLimitConfig] = {}
        self._request_log: dict[str, list[float]] = {}

    @property
    def store(self) -> PolicyStore:
        """Access the underlying policy store."""
        return self._store

    def evaluate(self, request: AuthorizationRequest) -> AuthorizationDecision:
        """Evaluate request with platform policies applied first.

        Checks platform-level policies before delegating to Cedar engine:
        1. Cold-start check (agent must be ready)
        2. Cross-boundary check (tenant isolation)
        3. Rate limit check
        4. Cedar policy evaluation
        """
        # Cold-start denial
        agent_state = request.context.get("agent_state")
        if agent_state and agent_state != "ready":
            return AuthorizationDecision(
                decision=Decision.DENY,
                reasons=[
                    f"Cold-start denial: agent state is '{agent_state}', must be 'ready'"
                ],
                matching_policies=["platform:cold_start_deny"],
            )

        # Cross-boundary denial
        request_tenant = request.context.get("tenant_id")
        resource_tenant = request.context.get("resource_tenant_id")
        if (
            request_tenant
            and resource_tenant
            and request_tenant != resource_tenant
        ):
            return AuthorizationDecision(
                decision=Decision.DENY,
                reasons=[
                    f"Cross-boundary denial: tenant '{request_tenant}' cannot access "
                    f"resources of tenant '{resource_tenant}'"
                ],
                matching_policies=["platform:cross_boundary_deny"],
            )

        # Rate limit check
        rate_key = request.context.get("rate_limit_key", request.principal_id)
        if rate_key and rate_key in self._rate_limits:
            if not self._check_rate_limit(rate_key):
                return AuthorizationDecision(
                    decision=Decision.DENY,
                    reasons=[f"Rate limit exceeded for '{rate_key}'"],
                    matching_policies=["platform:rate_limit"],
                )

        # Delegate to Cedar engine
        return self._base_engine.evaluate(request)

    def set_rate_limit(self, key: str, config: RateLimitConfig) -> None:
        """Configure rate limiting for a key (agent ID or action)."""
        self._rate_limits[key] = config
        self._request_log[key] = []

    def _check_rate_limit(self, key: str) -> bool:
        """Check if a request is within rate limits. Records the request if allowed."""
        config = self._rate_limits.get(key)
        if config is None:
            return True

        now = time.monotonic()
        window_start = now - config.window_seconds

        # Clean old entries
        log = self._request_log.get(key, [])
        log = [t for t in log if t > window_start]
        self._request_log[key] = log

        if len(log) >= config.max_requests:
            return False

        log.append(now)
        return True

    def check_content(self, text: str) -> ContentFilterResult:
        """Check text for thinking/reasoning leak patterns.

        Returns a ContentFilterResult with the cleaned text and
        a list of patterns that were found.
        """
        patterns_found: list[str] = []
        filtered = text

        for pattern in THINKING_LEAK_PATTERNS:
            if pattern.search(filtered):
                patterns_found.append(pattern.pattern)
                filtered = pattern.sub("", filtered)

        # Clean up extra whitespace from removals
        if patterns_found:
            filtered = re.sub(r"\n{3,}", "\n\n", filtered).strip()

        return ContentFilterResult(
            is_clean=len(patterns_found) == 0,
            filtered_text=filtered,
            patterns_found=patterns_found,
        )


def create_agent_policies(agent_role: str) -> list[Policy]:
    """Generate default Cedar policies based on agent role.

    Each role gets a baseline set of permissions. More privileged roles
    get additional access.

    Args:
        agent_role: Role name (e.g., "developer", "reviewer", "admin", "monitor").

    Returns:
        List of Policy objects for the role.
    """
    policies: list[Policy] = []

    # All roles can read files
    policies.append(Policy(
        policy_id=f"{agent_role}:read-files",
        effect=Effect.PERMIT,
        description=f"{agent_role} can read files",
        principal_type="Agent",
        principal_id="*",
        action="read",
        resource_type="File",
        resource_id="*",
        conditions={"role": agent_role},
    ))

    # All roles can send messages
    policies.append(Policy(
        policy_id=f"{agent_role}:send-messages",
        effect=Effect.PERMIT,
        description=f"{agent_role} can send messages",
        principal_type="Agent",
        principal_id="*",
        action="send_message",
        resource_type="Message",
        resource_id="*",
        conditions={"role": agent_role},
    ))

    if agent_role in ("developer", "admin"):
        policies.append(Policy(
            policy_id=f"{agent_role}:write-project",
            effect=Effect.PERMIT,
            description=f"{agent_role} can write to project files",
            principal_type="Agent",
            principal_id="*",
            action="write",
            resource_type="File",
            resource_id="project/*",
            conditions={"role": agent_role},
        ))

    if agent_role == "admin":
        policies.append(Policy(
            policy_id=f"{agent_role}:manage-agents",
            effect=Effect.PERMIT,
            description="Admin can manage agents",
            principal_type="Agent",
            principal_id="*",
            action="manage",
            resource_type="Agent",
            resource_id="*",
            conditions={"role": agent_role},
        ))
        policies.append(Policy(
            policy_id=f"{agent_role}:manage-policies",
            effect=Effect.PERMIT,
            description="Admin can manage policies",
            principal_type="Agent",
            principal_id="*",
            action="manage",
            resource_type="Policy",
            resource_id="*",
            conditions={"role": agent_role},
        ))

    if agent_role == "monitor":
        policies.append(Policy(
            policy_id=f"{agent_role}:read-metrics",
            effect=Effect.PERMIT,
            description="Monitor can read metrics",
            principal_type="Agent",
            principal_id="*",
            action="read",
            resource_type="Metrics",
            resource_id="*",
            conditions={"role": agent_role},
        ))
        policies.append(Policy(
            policy_id=f"{agent_role}:read-audit",
            effect=Effect.PERMIT,
            description="Monitor can read audit logs",
            principal_type="Agent",
            principal_id="*",
            action="read",
            resource_type="AuditLog",
            resource_id="*",
            conditions={"role": agent_role},
        ))

    if agent_role == "reviewer":
        policies.append(Policy(
            policy_id=f"{agent_role}:review-code",
            effect=Effect.PERMIT,
            description="Reviewer can review code",
            principal_type="Agent",
            principal_id="*",
            action="review",
            resource_type="Code",
            resource_id="*",
            conditions={"role": agent_role},
        ))

    # All roles denied secrets
    policies.append(Policy(
        policy_id=f"{agent_role}:deny-secrets",
        effect=Effect.FORBID,
        description=f"{agent_role} cannot access secrets",
        principal_type="Agent",
        principal_id="*",
        action="read",
        resource_type="File",
        resource_id="secrets/*",
        conditions={"role": agent_role},
    ))

    return policies
