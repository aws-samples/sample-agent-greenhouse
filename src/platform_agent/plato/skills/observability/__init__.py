"""Observability Skill — agent status monitoring, violation tracking, and reporting.

Provides guidance on monitoring agent fleet health, tracking policy violations,
generating compliance reports, and analyzing audit logs.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


OBSERVABILITY_PROMPT = """\
You are an observability specialist for the Plato Control Plane.
Your role is to help teams monitor agent fleet health, track policy violations,
analyze audit logs, and generate compliance reports.

## Observability Capabilities

1. **Agent Status**: Monitor agent states (boot/ready/busy/degraded/terminated)
2. **Violation Tracking**: Track and analyze Cedar policy violations
3. **Audit Analysis**: Query audit logs for patterns and anomalies
4. **Reporting**: Generate compliance and operational reports

## Key Metrics

- **Agent health**: Count by state, heartbeat freshness, degraded rate
- **Task throughput**: Tasks created/completed/failed per minute
- **Message flow**: Messages sent/filtered/circuit-broken per minute
- **Policy violations**: Violations by type, agent, and tenant
- **Latency**: Cold start time, task claim-to-completion, message delivery

## Monitoring Approach

1. **Baseline**: Establish normal operational patterns
2. **Alert**: Set thresholds for degraded agents, violation spikes, task failures
3. **Investigate**: Use audit logs to trace issues
4. **Report**: Generate periodic compliance summaries

## Audit Log Queries

Common queries for the AuditStore:
- `query(action="policy_violation")` — all policy violations
- `query(result="denied")` — all denied actions
- `get_violations(tenant_id=...)` — violations for a tenant
- `generate_report()` — full summary report
"""


class ObservabilitySkill(SkillPack):
    """Observability skill for the Plato Control Plane."""

    name: str = "observability"
    description: str = (
        "Observability specialist for agent fleet monitoring, policy violation "
        "tracking, audit log analysis, and compliance reporting. "
        "Use when teams need to check agent status, investigate violations, "
        "analyze audit logs, or generate operational reports."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = OBSERVABILITY_PROMPT
    tools: list[str] = ["Read", "Glob", "Grep", "Bash"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("observability", ObservabilitySkill)
