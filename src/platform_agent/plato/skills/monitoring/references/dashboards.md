# Dashboards & Visualization Guide

## Table of Contents
- [Dashboard Templates](#dashboard-templates)
- [Operational Dashboard](#operational-dashboard)
- [Business Metrics Dashboard](#business-metrics-dashboard)
- [Cross-Account Dashboards](#cross-account-dashboards)
- [Dashboard as Code](#dashboard-as-code)

---

## Dashboard Templates

### Agent Operations Dashboard (JSON)

```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "title": "Invocation Count",
        "metrics": [
          ["AgentCore", "InvocationCount", "AgentId", "<agent-id>"]
        ],
        "period": 300,
        "stat": "Sum",
        "view": "timeSeries"
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Latency (p50, p95, p99)",
        "metrics": [
          ["AgentCore/Custom", "InvocationLatency", "AgentId", "<agent-id>", {"stat": "p50"}],
          ["...", {"stat": "p95"}],
          ["...", {"stat": "p99"}]
        ],
        "period": 300,
        "view": "timeSeries"
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Error Rate",
        "metrics": [
          ["AgentCore/Custom", "ErrorCount", "AgentId", "<agent-id>"]
        ],
        "period": 300,
        "stat": "Sum",
        "view": "timeSeries"
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Memory Utilization",
        "metrics": [
          ["AgentCore", "MemoryUtilization", "AgentId", "<agent-id>"]
        ],
        "period": 60,
        "stat": "Average",
        "view": "timeSeries",
        "annotations": {
          "horizontal": [{"value": 80, "label": "Warning"}]
        }
      }
    }
  ]
}
```

### Create Dashboard via CLI

```bash
aws cloudwatch put-dashboard \
  --dashboard-name "Agent-<agent-id>" \
  --dashboard-body file://dashboard.json
```

---

## Operational Dashboard

### Key Widgets

1. **Health Overview** (Single value)
   - Active alarms count
   - Current error rate
   - P95 latency

2. **Traffic** (Time series)
   - Invocations per minute
   - Concurrent sessions
   - Request distribution by type

3. **Performance** (Time series)
   - Latency percentiles (p50, p95, p99)
   - Tool execution times
   - Model response times

4. **Resources** (Time series)
   - Memory utilization
   - CPU utilization
   - Network I/O

5. **Errors** (Log widget)
   - Recent error messages
   - Error rate by type
   - Top error patterns

---

## Business Metrics Dashboard

### Cost Tracking

```json
{
  "type": "metric",
  "properties": {
    "title": "Token Usage (Cost Proxy)",
    "metrics": [
      ["AgentCore/Custom", "InputTokens", "AgentId", "<agent-id>"],
      ["AgentCore/Custom", "OutputTokens", "AgentId", "<agent-id>"]
    ],
    "period": 3600,
    "stat": "Sum",
    "view": "timeSeries"
  }
}
```

### Usage Patterns

- Invocations by hour of day (heatmap)
- Average tokens per session (trend)
- Handoff rate (human escalation frequency)
- Session completion rate

---

## Cross-Account Dashboards

### Share Dashboard Across Accounts

```bash
# Enable cross-account sharing
aws cloudwatch put-dashboard \
  --dashboard-name "Multi-Account-Agents" \
  --dashboard-body '{
    "widgets": [{
      "type": "metric",
      "properties": {
        "title": "All Agents - Error Rate",
        "metrics": [
          ["AgentCore/Custom", "ErrorCount", "AgentId", "agent-1", {"accountId": "111111111111"}],
          ["AgentCore/Custom", "ErrorCount", "AgentId", "agent-2", {"accountId": "222222222222"}]
        ],
        "period": 300,
        "stat": "Sum"
      }
    }]
  }'
```

---

## Dashboard as Code

### CloudFormation Template

```yaml
Resources:
  AgentDashboard:
    Type: AWS::CloudWatch::Dashboard
    Properties:
      DashboardName: !Sub "Agent-${AgentId}"
      DashboardBody: !Sub |
        {
          "widgets": [
            {
              "type": "metric",
              "properties": {
                "title": "Invocations",
                "metrics": [["AgentCore", "InvocationCount", "AgentId", "${AgentId}"]],
                "period": 300,
                "stat": "Sum"
              }
            }
          ]
        }
```

### CDK Example

```python
from aws_cdk import aws_cloudwatch as cw

dashboard = cw.Dashboard(self, "AgentDashboard",
    dashboard_name=f"Agent-{agent_id}"
)

dashboard.add_widgets(
    cw.GraphWidget(
        title="Invocations",
        left=[invocation_metric],
    ),
    cw.GraphWidget(
        title="Latency",
        left=[latency_p50, latency_p95, latency_p99],
    ),
)
```
