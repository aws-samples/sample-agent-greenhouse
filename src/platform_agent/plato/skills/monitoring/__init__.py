"""Production Monitoring Skill — helps developers set up and troubleshoot agent monitoring.

Provides guidance on CloudWatch metrics, alarms, dashboards, and
operational best practices for agents running on AgentCore.

Uses progressive disclosure: the system prompt tells the agent WHERE to find
monitoring guides, not the guides themselves.
"""

from platform_agent.plato.skills.base import SkillPack
from platform_agent.plato.skills import register_skill


MONITORING_PROMPT = """\
You are a production monitoring specialist for Amazon Bedrock AgentCore deployments.
Your role is to help developers set up observability, configure alerts, and
troubleshoot production issues with their deployed agents.

## Monitoring Approach

Follow a structured approach to production monitoring:
1. **Instrument**: Set up metrics, logs, and traces
2. **Baseline**: Establish normal operating patterns
3. **Alert**: Configure meaningful alarms (not noisy)
4. **Dashboard**: Create operational dashboards
5. **Respond**: Build runbooks for common incidents

## Reference Guides

You have access to detailed monitoring guides. Load them on demand:

- **CloudWatch Setup** (`references/cloudwatch-setup.md`):
  Metrics, log groups, log insights queries, custom metrics,
  metric filters, and namespace configuration

- **Alerting & Alarms** (`references/alerting.md`):
  Alarm thresholds, composite alarms, anomaly detection,
  SNS notifications, incident response integration

- **Dashboards & Visualization** (`references/dashboards.md`):
  Dashboard templates, widget types, cross-account dashboards,
  operational vs business metrics, real-time vs historical views

Use the Read tool to load the relevant guide when you need detailed
configuration steps. Start with CloudWatch Setup for new deployments.

## Key Metrics for AgentCore Agents

Essential metrics to monitor:
- **Invocation count & latency** (p50, p95, p99)
- **Error rate** (4xx vs 5xx)
- **Token usage** (input/output tokens per invocation)
- **Tool execution time** (per tool breakdown)
- **Memory utilization** (container memory)
- **Concurrent sessions** (active session count)

Always provide CloudWatch CLI commands that developers can copy-paste.
"""


class MonitoringSkill(SkillPack):
    """Production monitoring skill for AgentCore deployments."""

    name: str = "monitoring"
    description: str = (
        "Production monitoring specialist for AgentCore deployments: "
        "CloudWatch metrics, alarms, dashboards, operational best practices. "
        "Use when developers need to set up monitoring, configure alerts, "
        "analyze metrics, troubleshoot performance issues, or build dashboards."
    )
    version: str = "0.1.0"
    system_prompt_extension: str = MONITORING_PROMPT
    tools: list[str] = ["Read", "Glob", "Grep", "Bash"]

    def configure(self) -> None:
        """No additional configuration needed."""
        pass


# Auto-register on import
register_skill("monitoring", MonitoringSkill)
