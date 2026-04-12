"""BusinessMetricsHook — tracks business-level metrics across invocations.

Uses Strands HookProvider API for proper lifecycle integration.
Emits CloudWatch EMF metrics under the Plato/Business namespace.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import (
        BeforeInvocationEvent,
        AfterInvocationEvent,
        AfterToolCallEvent,
    )

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



# Tool names that indicate artifact generation by type.
_ARTIFACT_STAGE_MAP: dict[str, str] = {
    "requirements": "spec",
    "user_stories": "spec",
    "workflow_planning": "spec",
    "app_design": "spec",
    "units": "test_cases",
}

_REVIEW_TOOL = "create_pull_request_review"
_ISSUE_TOOL = "create_github_issue"
_SUBMIT_TOOL = "aidlc_submit_answers"


class BusinessMetricsHook(HookBase):
    """Hook that tracks business-level metrics across invocations.

    Tracks skill usage, unique developers, session depth, artifact counts,
    and flow completion rates. Emits CloudWatch EMF under the Plato/Business
    namespace.

    Implements strands.hooks.HookProvider for native integration.
    """

    def __init__(self, *, auto_emit: bool = True) -> None:
        self.auto_emit = auto_emit
        self.skill_usage_count: dict[str, int] = {}
        self.unique_developers: set[str] = set()
        self.session_depths: dict[str, int] = {}
        self.artifact_counts: dict[str, int] = {}
        self.invocation_completions: dict[str, int] = {"started": 0, "completed": 0}

        # Internal tracking for current invocation context.
        self._current_session_id: str | None = None
        self._current_skill_name: str | None = None

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)
            registry.add_callback(AfterInvocationEvent, self.on_after_invocation)
            registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    def on_before_invocation(self, event) -> None:
        """Extract developer identity and track skill usage.

        Args:
            event: BeforeInvocationEvent from Strands.
        """
        try:
            # Extract developer identity — use session_id hash as proxy.
            developer_id = self._extract_developer_id(event)
            self.unique_developers.add(developer_id)

            # Extract skill name from agent/session context.
            skill_name = self._extract_skill_name(event)
            self._current_skill_name = skill_name
            self.skill_usage_count[skill_name] = (
                self.skill_usage_count.get(skill_name, 0) + 1
            )

            # Extract session ID for depth tracking.
            session_id = self._extract_session_id(event)
            self._current_session_id = session_id

            # Track flow start.
            self.invocation_completions["started"] += 1
        except Exception:
            logger.debug("BusinessMetricsHook: error in on_before_invocation", exc_info=True)

    def on_after_invocation(self, event) -> None:
        """Track flow completion and emit EMF if enabled.

        Args:
            event: AfterInvocationEvent from Strands.
        """
        try:
            self.invocation_completions["completed"] += 1

            if self.auto_emit:
                self.emit_cloudwatch_emf()
        except Exception:
            logger.debug("BusinessMetricsHook: error in on_after_invocation", exc_info=True)

    def on_after_tool_call(self, event) -> None:
        """Increment session depth and detect artifacts.

        Args:
            event: AfterToolCallEvent from Strands.
        """
        try:
            # Increment session depth.
            session_id = self._current_session_id or "unknown"
            self.session_depths[session_id] = (
                self.session_depths.get(session_id, 0) + 1
            )

            # Detect artifacts from tool calls.
            tool_use = getattr(event, "tool_use", {})
            tool_name = (
                tool_use.get("name", "unknown")
                if isinstance(tool_use, dict)
                else "unknown"
            )
            tool_input = (
                tool_use.get("input", {})
                if isinstance(tool_use, dict)
                else {}
            )

            if tool_name == _SUBMIT_TOOL:
                # aidlc_submit_answers — detect artifact type from stage_id.
                stage_id = tool_input.get("stage_id", "") if isinstance(tool_input, dict) else ""
                artifact_type = _ARTIFACT_STAGE_MAP.get(stage_id)
                if artifact_type:
                    self.artifact_counts[artifact_type] = (
                        self.artifact_counts.get(artifact_type, 0) + 1
                    )
            elif tool_name == _ISSUE_TOOL:
                self.artifact_counts["issue"] = (
                    self.artifact_counts.get("issue", 0) + 1
                )
            elif tool_name == _REVIEW_TOOL:
                self.artifact_counts["review"] = (
                    self.artifact_counts.get("review", 0) + 1
                )
        except Exception:
            logger.debug("BusinessMetricsHook: error in on_after_tool_call", exc_info=True)

    def get_business_metrics(self) -> dict[str, Any]:
        """Return all tracked business metrics.

        Returns:
            Dictionary with skill_usage_count, unique_developer_count,
            avg_session_depth, artifact_counts, and invocation_completion_rate.
        """
        depths = list(self.session_depths.values())
        avg_depth = sum(depths) / len(depths) if depths else 0.0

        started = self.invocation_completions["started"]
        completed = self.invocation_completions["completed"]
        completion_rate = (completed / started * 100) if started > 0 else 0.0

        return {
            "skill_usage_count": dict(self.skill_usage_count),
            "unique_developer_count": len(self.unique_developers),
            "avg_session_depth": avg_depth,
            "artifact_counts": dict(self.artifact_counts),
            "invocation_completion_rate": completion_rate,
        }

    def emit_cloudwatch_emf(self) -> None:
        """Emit CloudWatch Embedded Metric Format JSON to stdout.

        Namespace: Plato/Business, Dimensions: SkillName, ArtifactType.
        """
        metrics = self.get_business_metrics()
        skill = self._current_skill_name or "unknown"

        emf_log: dict[str, Any] = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "Plato/Business",
                        "Dimensions": [["SkillName"]],
                        "Metrics": [
                            {"Name": "SkillUsageCount", "Unit": "Count"},
                            {"Name": "UniqueDevCount", "Unit": "Count"},
                            {"Name": "SessionDepth", "Unit": "Count"},
                            {"Name": "InvocationCompletionRate", "Unit": "Percent"},
                        ],
                    }
                ],
            },
            "SkillName": skill,
            "SkillUsageCount": metrics["skill_usage_count"].get(skill, 0),
            "UniqueDevCount": metrics["unique_developer_count"],
            "SessionDepth": metrics["avg_session_depth"],
            "InvocationCompletionRate": metrics["invocation_completion_rate"],
        }
        print(json.dumps(emf_log))

        # Emit per-artifact-type metrics separately.
        for artifact_type, count in metrics["artifact_counts"].items():
            artifact_emf: dict[str, Any] = {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "Plato/Business",
                            "Dimensions": [["ArtifactType"]],
                            "Metrics": [
                                {"Name": "ArtifactGeneratedCount", "Unit": "Count"},
                            ],
                        }
                    ],
                },
                "ArtifactType": artifact_type,
                "ArtifactGeneratedCount": count,
            }
            print(json.dumps(artifact_emf))

    def clear(self) -> None:
        """Reset all tracked state."""
        self.skill_usage_count.clear()
        self.unique_developers.clear()
        self.session_depths.clear()
        self.artifact_counts.clear()
        self.invocation_completions = {"started": 0, "completed": 0}
        self._current_session_id = None
        self._current_skill_name = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_developer_id(event) -> str:
        """Extract developer identity from event context.

        Uses session_id hash as a proxy for developer identity.

        TODO(Phase 4): Strands Agent doesn't have session_id/skill_name by
        default. FoundationStrandsAgent should set these as agent attributes
        or pass via invocation_state for meaningful DAU tracking.
        """
        try:
            # Try agent attributes or invocation state.
            agent = getattr(event, "agent", None)
            if agent is not None:
                session_id = getattr(agent, "session_id", None)
                if session_id:
                    return hashlib.sha256(session_id.encode()).hexdigest()[:12]
        except Exception:
            pass

        # Fallback: try messages for any developer hint.
        try:
            messages = getattr(event, "messages", [])
            if messages:
                return hashlib.sha256(str(id(messages)).encode()).hexdigest()[:12]
        except Exception:
            pass

        return "unknown"

    @staticmethod
    def _extract_skill_name(event) -> str:
        """Extract skill name from event context."""
        try:
            agent = getattr(event, "agent", None)
            if agent is not None:
                skill = getattr(agent, "skill_name", None)
                if skill:
                    return skill
        except Exception:
            pass
        return "unknown"

    @staticmethod
    def _extract_session_id(event) -> str:
        """Extract session ID from event context."""
        try:
            agent = getattr(event, "agent", None)
            if agent is not None:
                session_id = getattr(agent, "session_id", None)
                if session_id:
                    return session_id
        except Exception:
            pass
        return "default"
