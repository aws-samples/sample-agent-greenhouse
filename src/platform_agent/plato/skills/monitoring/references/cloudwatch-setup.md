# CloudWatch Setup Guide

## Table of Contents
- [Log Groups](#log-groups)
- [Custom Metrics](#custom-metrics)
- [Metric Filters](#metric-filters)
- [Log Insights Queries](#log-insights-queries)
- [Embedded Metrics Format](#embedded-metrics-format)

---

## Log Groups

### AgentCore Default Log Groups

AgentCore automatically creates log groups for deployed agents:

```bash
# List agent log groups
aws logs describe-log-groups \
  --log-group-name-prefix /agentcore/agents/

# Get recent logs
aws logs tail /agentcore/agents/<agent-id> --since 1h --follow
```

### Retention Configuration

```bash
# Set retention to 30 days (cost optimization)
aws logs put-retention-policy \
  --log-group-name /agentcore/agents/<agent-id> \
  --retention-in-days 30
```

### Structured Logging Best Practice

```python
import json
import logging

logger = logging.getLogger(__name__)

def log_invocation(session_id, prompt, duration_ms, token_count):
    logger.info(json.dumps({
        "event": "invocation",
        "session_id": session_id,
        "duration_ms": duration_ms,
        "input_tokens": token_count["input"],
        "output_tokens": token_count["output"],
        "prompt_length": len(prompt),
    }))
```

---

## Custom Metrics

### Publishing Custom Metrics

```python
import boto3

cloudwatch = boto3.client("cloudwatch")

def publish_metric(agent_id, metric_name, value, unit="Count"):
    cloudwatch.put_metric_data(
        Namespace="AgentCore/Custom",
        MetricData=[{
            "MetricName": metric_name,
            "Value": value,
            "Unit": unit,
            "Dimensions": [
                {"Name": "AgentId", "Value": agent_id},
            ],
        }],
    )
```

### Recommended Custom Metrics

| Metric | Unit | Description |
|--------|------|-------------|
| ToolExecutionTime | Milliseconds | Time per tool call |
| TokensUsed | Count | Input + output tokens |
| SessionDuration | Seconds | Total session length |
| ErrorCount | Count | Application errors |
| HandoffCount | Count | Human handoff escalations |

---

## Metric Filters

### Create Error Rate Filter

```bash
aws logs put-metric-filter \
  --log-group-name /agentcore/agents/<agent-id> \
  --filter-name AgentErrors \
  --filter-pattern '{ $.level = "ERROR" }' \
  --metric-transformations \
    metricName=ErrorCount,metricNamespace=AgentCore/Custom,metricValue=1
```

### Create Latency Filter

```bash
aws logs put-metric-filter \
  --log-group-name /agentcore/agents/<agent-id> \
  --filter-name InvocationLatency \
  --filter-pattern '{ $.event = "invocation" && $.duration_ms > 0 }' \
  --metric-transformations \
    metricName=InvocationLatency,metricNamespace=AgentCore/Custom,metricValue=$.duration_ms
```

---

## Log Insights Queries

### Error Analysis
```
fields @timestamp, @message
| filter @message like /ERROR/
| sort @timestamp desc
| limit 50
```

### Latency Percentiles
```
fields duration_ms
| filter event = "invocation"
| stats avg(duration_ms) as avg_latency,
        pct(duration_ms, 50) as p50,
        pct(duration_ms, 95) as p95,
        pct(duration_ms, 99) as p99
  by bin(1h)
```

### Token Usage Over Time
```
fields input_tokens, output_tokens
| filter event = "invocation"
| stats sum(input_tokens) as total_input,
        sum(output_tokens) as total_output,
        count(*) as invocations
  by bin(1h)
```

### Top Errors
```
fields @message
| filter @message like /ERROR/
| stats count(*) as error_count by @message
| sort error_count desc
| limit 10
```

---

## Embedded Metrics Format

### Using EMF for Zero-Config Metrics

```python
import json
import sys

def emit_emf_metric(agent_id, metric_name, value, unit="Count"):
    """Emit CloudWatch Embedded Metrics Format log."""
    emf = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "AgentCore/Custom",
                "Dimensions": [["AgentId"]],
                "Metrics": [{"Name": metric_name, "Unit": unit}],
            }],
        },
        "AgentId": agent_id,
        metric_name: value,
    }
    print(json.dumps(emf))
    sys.stdout.flush()
```

Advantages of EMF:
- No boto3 dependency for metric publishing
- Metrics extracted automatically from logs
- Lower latency than PutMetricData API
- No additional cost beyond log ingestion
