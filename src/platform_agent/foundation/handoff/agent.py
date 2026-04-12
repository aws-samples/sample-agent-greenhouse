"""Core handoff agent implementation.

The HandoffAgent manages escalation from any agent to a human reviewer.
It supports pluggable channels (CLI, Slack, webhook, etc.) and maintains
a queue of pending handoff requests.
"""

from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HandoffStatus(Enum):
    """Status of a handoff request."""

    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class HandoffPriority(Enum):
    """Priority levels for handoff requests."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class HandoffRequest:
    """A structured request for human intervention.

    Created by agents when they need human review, approval, or input.
    Contains full context needed for the human to make a decision.
    """

    # Identity
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)

    # Source
    source_agent: str = ""
    source_task: str = ""

    # Reason for handoff
    reason: str = ""
    priority: HandoffPriority = HandoffPriority.MEDIUM

    # Context
    summary: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    conversation_history: list[str] = field(default_factory=list)

    # Evaluation context (from evaluator escalations)
    evaluation_report: str = ""
    iteration_count: int = 0
    last_score: float = 0.0
    threshold: float = 0.0

    # Status
    status: HandoffStatus = HandoffStatus.PENDING

    @property
    def is_evaluator_escalation(self) -> bool:
        """Check if this handoff originated from an evaluator."""
        return bool(self.evaluation_report)

    @property
    def age(self) -> float:
        """Seconds since the request was created."""
        return time.time() - self.timestamp

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "source_agent": self.source_agent,
            "source_task": self.source_task,
            "reason": self.reason,
            "priority": self.priority.value,
            "summary": self.summary,
            "context": self.context,
            "conversation_history": self.conversation_history,
            "evaluation_report": self.evaluation_report,
            "iteration_count": self.iteration_count,
            "last_score": self.last_score,
            "threshold": self.threshold,
            "status": self.status.value,
        }


@dataclass
class HandoffResponse:
    """Human response to a handoff request.

    Contains the human's decision and any instructions for the agent.
    """

    request_id: str
    status: HandoffStatus
    decision: str = ""  # "approve", "reject", "revise", "override"
    instructions: str = ""
    reviewer: str = ""
    timestamp: float = field(default_factory=time.time)


class HandoffChannel(ABC):
    """Abstract channel for delivering handoff requests to humans.

    Implementations handle the actual delivery mechanism (CLI, Slack, webhook, etc.)
    """

    @abstractmethod
    async def send(self, request: HandoffRequest) -> bool:
        """Send a handoff request to a human.

        Returns True if the request was successfully delivered.
        """
        ...

    @abstractmethod
    async def poll(self, request_id: str) -> HandoffResponse | None:
        """Check for a human response to a handoff request.

        Returns None if no response yet.
        """
        ...


class CLIHandoffChannel(HandoffChannel):
    """CLI-based handoff channel.

    Prints handoff requests to stdout and stores them for later resolution.
    Suitable for development and testing.
    """

    def __init__(self) -> None:
        self._pending: dict[str, HandoffRequest] = {}
        self._responses: dict[str, HandoffResponse] = {}

    async def send(self, request: HandoffRequest) -> bool:
        """Print handoff request to CLI and store it."""
        self._pending[request.request_id] = request
        logger.info("Handoff request %s sent to CLI", request.request_id)
        return True

    async def poll(self, request_id: str) -> HandoffResponse | None:
        """Check for CLI response."""
        return self._responses.get(request_id)

    def resolve(
        self,
        request_id: str,
        decision: str,
        instructions: str = "",
        reviewer: str = "cli-user",
    ) -> HandoffResponse:
        """Manually resolve a handoff request (for CLI/testing use).

        Args:
            request_id: The request to resolve.
            decision: One of "approve", "reject", "revise", "override".
            instructions: Additional instructions for the agent.
            reviewer: Who made the decision.

        Returns:
            The HandoffResponse.

        Raises:
            KeyError: If request_id is not found.
            ValueError: If decision is not a valid action.
        """
        valid_decisions = {"approve", "reject", "revise", "override"}
        if decision not in valid_decisions:
            raise ValueError(
                f"Invalid decision: {decision!r}. Must be one of: {', '.join(sorted(valid_decisions))}"
            )
        if request_id not in self._pending:
            raise KeyError(f"No pending handoff request: {request_id}")

        status = HandoffStatus.RESOLVED if decision in ("approve", "override") else HandoffStatus.REJECTED
        response = HandoffResponse(
            request_id=request_id,
            status=status,
            decision=decision,
            instructions=instructions,
            reviewer=reviewer,
        )
        self._responses[request_id] = response
        self._pending[request_id].status = status
        return response

    @property
    def pending_requests(self) -> list[HandoffRequest]:
        """List all pending handoff requests."""
        return [r for r in self._pending.values() if r.status == HandoffStatus.PENDING]


class HandoffAgent:
    """Agent that manages human handoff/escalation.

    Receives escalation requests from other agents, packages context,
    routes to appropriate channel, and returns human decisions.

    Usage:
        agent = HandoffAgent()
        request = agent.create_from_evaluation(session)
        await agent.escalate(request)
        # Later...
        response = await agent.check_status(request.request_id)
    """

    def __init__(
        self,
        channel: HandoffChannel | None = None,
        auto_escalate_threshold: float = 0.5,
    ) -> None:
        self._channel = channel or CLIHandoffChannel()
        self._requests: dict[str, HandoffRequest] = {}
        self.auto_escalate_threshold = auto_escalate_threshold

    @property
    def channel(self) -> HandoffChannel:
        """The current handoff channel."""
        return self._channel

    def create_request(
        self,
        source_agent: str,
        reason: str,
        summary: str,
        priority: HandoffPriority = HandoffPriority.MEDIUM,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> HandoffRequest:
        """Create a new handoff request.

        Args:
            source_agent: Name of the agent requesting handoff.
            reason: Why human review is needed.
            summary: Brief description of what needs review.
            priority: Urgency level.
            context: Additional context dict.
            **kwargs: Additional fields for HandoffRequest.

        Returns:
            A new HandoffRequest.
        """
        request = HandoffRequest(
            source_agent=source_agent,
            reason=reason,
            summary=summary,
            priority=priority,
            context=context or {},
            **kwargs,
        )
        self._requests[request.request_id] = request
        return request

    def create_from_evaluation(
        self,
        session: Any,
        priority: HandoffPriority = HandoffPriority.HIGH,
    ) -> HandoffRequest:
        """Create a handoff request from an evaluator session.

        Extracts evaluation context from an EvaluationSession and packages
        it into a handoff request.

        Args:
            session: An EvaluationSession that resulted in escalation.
            priority: Defaults to HIGH for evaluator escalations.

        Returns:
            A HandoffRequest with evaluation context.
        """
        last_score = 0.0
        threshold = 0.0
        if session.iterations:
            last_eval = session.iterations[-1].evaluation
            last_score = last_eval.overall_score
        # Threshold lives on the rubric, not on individual results
        if hasattr(session, "rubric") and session.rubric is not None:
            threshold = session.rubric.overall_threshold
        elif session.iterations:
            # Fallback for duck-typed sessions (e.g., tests with mock objects)
            last_eval = session.iterations[-1].evaluation
            threshold = getattr(last_eval, "threshold", 0.0)

        # Build evaluation report
        report_lines = [
            f"Evaluator: {session.evaluator_name}",
            f"Iterations: {session.iteration_count}",
            f"Last Score: {last_score:.0%} (threshold: {threshold:.0%})",
            f"Status: {session.final_status}",
        ]

        if session.iterations:
            last_eval = session.iterations[-1].evaluation
            report_lines.append("")
            report_lines.append("Failed items:")
            for score in last_eval.item_scores:
                if not score.passed:
                    report_lines.append(
                        f"  ❌ {score.rubric_item_id}: {score.score:.0%} — {score.feedback}"
                    )

        request = HandoffRequest(
            source_agent=f"evaluator:{session.evaluator_name}",
            source_task=session.session_id,
            reason=f"Evaluator escalation: {session.evaluator_name} failed after {session.iteration_count} iterations",
            priority=priority,
            summary=(
                f"The {session.evaluator_name} evaluator could not achieve passing score "
                f"after {session.iteration_count} iterations. Last score: {last_score:.0%}, "
                f"threshold: {threshold:.0%}. Human review required."
            ),
            evaluation_report="\n".join(report_lines),
            iteration_count=session.iteration_count,
            last_score=last_score,
            threshold=threshold,
        )
        self._requests[request.request_id] = request
        return request

    async def escalate(self, request: HandoffRequest) -> bool:
        """Send a handoff request through the configured channel.

        Args:
            request: The handoff request to escalate.

        Returns:
            True if successfully delivered.
        """
        logger.info(
            "Escalating handoff request %s from %s (priority: %s)",
            request.request_id,
            request.source_agent,
            request.priority.value,
        )
        success = await self._channel.send(request)
        if success:
            request.status = HandoffStatus.PENDING
        return success

    async def check_status(self, request_id: str) -> HandoffResponse | None:
        """Check if a human has responded to a handoff request.

        Args:
            request_id: The request to check.

        Returns:
            HandoffResponse if available, None if still pending.
        """
        response = await self._channel.poll(request_id)
        if response and request_id in self._requests:
            self._requests[request_id].status = response.status
        return response

    def get_request(self, request_id: str) -> HandoffRequest | None:
        """Get a handoff request by ID."""
        return self._requests.get(request_id)

    @property
    def pending_requests(self) -> list[HandoffRequest]:
        """List all pending handoff requests."""
        return [r for r in self._requests.values() if r.status == HandoffStatus.PENDING]

    def format_handoff_report(self, request: HandoffRequest) -> str:
        """Format a handoff request as a human-readable report.

        Args:
            request: The handoff request to format.

        Returns:
            Formatted report string.
        """
        lines = [
            "=" * 60,
            "🚨 HUMAN REVIEW REQUIRED",
            "=" * 60,
            "",
            f"Request ID: {request.request_id}",
            f"Priority: {request.priority.value.upper()}",
            f"Source: {request.source_agent}",
            f"Reason: {request.reason}",
            "",
            "Summary:",
            request.summary,
        ]

        if request.evaluation_report:
            lines.append("")
            lines.append("--- Evaluation Details ---")
            lines.append(request.evaluation_report)

        if request.conversation_history:
            lines.append("")
            lines.append("--- Conversation History ---")
            for msg in request.conversation_history[-5:]:  # Last 5 messages
                lines.append(f"  {msg}")

        lines.append("")
        lines.append("=" * 60)
        lines.append("Actions: approve | reject | revise <instructions> | override")
        lines.append("=" * 60)

        return "\n".join(lines)
