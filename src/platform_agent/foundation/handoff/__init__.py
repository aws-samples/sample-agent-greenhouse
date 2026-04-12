"""Human Handoff Agent — escalation handler for low-confidence or policy-required situations.

Any agent can invoke human handoff when:
- Confidence score below threshold (e.g., evaluator escalation)
- Security-critical decision required
- Custom policy requires human approval
- Developer explicitly requests human review

The handoff agent packages conversation context, creates a structured
handoff request, and routes it to the appropriate channel (CLI, Slack, etc.).
"""

from platform_agent.foundation.handoff.agent import (
    HandoffAgent,
    HandoffChannel,
    HandoffRequest,
    HandoffResponse,
    HandoffStatus,
    CLIHandoffChannel,
)

__all__ = [
    "HandoffAgent",
    "HandoffChannel",
    "HandoffRequest",
    "HandoffResponse",
    "HandoffStatus",
    "CLIHandoffChannel",
]
