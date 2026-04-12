# Alerting & Alarms Guide

## Table of Contents
- [Essential Alarms](#essential-alarms)
- [Composite Alarms](#composite-alarms)
- [Anomaly Detection](#anomaly-detection)
- [SNS Notifications](#sns-notifications)
- [Runbook Templates](#runbook-templates)

---

## Essential Alarms

### High Error Rate

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "AgentHighErrorRate-<agent-id>" \
  --metric-name ErrorCount \
  --namespace AgentCore/Custom \
  --statistic Sum \
  --period 300 \
  --threshold 10 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --alarm-actions arn:aws:sns:<region>:<account>:agent-alerts \
  --dimensions Name=AgentId,Value=<agent-id>
```

### High Latency (p95 > 30s)

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "AgentHighLatency-<agent-id>" \
  --metric-name InvocationLatency \
  --namespace AgentCore/Custom \
  --extended-statistic p95 \
  --period 300 \
  --threshold 30000 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 3 \
  --alarm-actions arn:aws:sns:<region>:<account>:agent-alerts
```

### Memory Utilization > 80%

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "AgentHighMemory-<agent-id>" \
  --metric-name MemoryUtilization \
  --namespace AgentCore \
  --statistic Average \
  --period 60 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 5 \
  --alarm-actions arn:aws:sns:<region>:<account>:agent-alerts
```

### Zero Invocations (Agent Down?)

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "AgentNoTraffic-<agent-id>" \
  --metric-name InvocationCount \
  --namespace AgentCore \
  --statistic Sum \
  --period 900 \
  --threshold 0 \
  --comparison-operator LessThanOrEqualToThreshold \
  --evaluation-periods 4 \
  --treat-missing-data breaching \
  --alarm-actions arn:aws:sns:<region>:<account>:agent-alerts
```

---

## Composite Alarms

### Critical: High Errors AND High Latency

```bash
aws cloudwatch put-composite-alarm \
  --alarm-name "AgentCritical-<agent-id>" \
  --alarm-rule 'ALARM("AgentHighErrorRate-<agent-id>") AND ALARM("AgentHighLatency-<agent-id>")' \
  --alarm-actions arn:aws:sns:<region>:<account>:critical-alerts
```

### Warning: Any Single Alarm

```bash
aws cloudwatch put-composite-alarm \
  --alarm-name "AgentWarning-<agent-id>" \
  --alarm-rule 'ALARM("AgentHighErrorRate-<agent-id>") OR ALARM("AgentHighLatency-<agent-id>") OR ALARM("AgentHighMemory-<agent-id>")' \
  --alarm-actions arn:aws:sns:<region>:<account>:agent-alerts
```

---

## Anomaly Detection

### Enable Anomaly Detection on Latency

```bash
aws cloudwatch put-anomaly-detector \
  --namespace AgentCore/Custom \
  --metric-name InvocationLatency \
  --stat Average \
  --dimensions Name=AgentId,Value=<agent-id>
```

### Alarm on Anomalous Latency

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "AgentAnomalousLatency-<agent-id>" \
  --metrics '[{"Id":"m1","MetricStat":{"Metric":{"Namespace":"AgentCore/Custom","MetricName":"InvocationLatency","Dimensions":[{"Name":"AgentId","Value":"<agent-id>"}]},"Period":300,"Stat":"Average"}},{"Id":"ad1","Expression":"ANOMALY_DETECTION_BAND(m1,2)"}]' \
  --threshold-metric-id ad1 \
  --comparison-operator GreaterThanUpperThreshold \
  --evaluation-periods 3 \
  --alarm-actions arn:aws:sns:<region>:<account>:agent-alerts
```

---

## SNS Notifications

### Create Alert Topic

```bash
# Create topic
aws sns create-topic --name agent-alerts

# Subscribe email
aws sns subscribe \
  --topic-arn arn:aws:sns:<region>:<account>:agent-alerts \
  --protocol email \
  --notification-endpoint ops@example.com

# Subscribe Slack webhook (via Lambda)
aws sns subscribe \
  --topic-arn arn:aws:sns:<region>:<account>:agent-alerts \
  --protocol lambda \
  --notification-endpoint arn:aws:lambda:<region>:<account>:function:slack-notifier
```

---

## Runbook Templates

### High Error Rate Runbook

1. Check CloudWatch Logs for error details:
   ```bash
   aws logs tail /agentcore/agents/<agent-id> --since 30m --filter-pattern "ERROR"
   ```
2. Check if deployment changed recently
3. Verify IAM permissions still valid
4. Check model availability in the region
5. If tool errors: check external service health
6. If persistent: roll back to last known good deployment

### High Latency Runbook

1. Check if latency is model-side or tool-side:
   ```bash
   # Log Insights query for tool breakdown
   ```
2. Check concurrent session count (throttling?)
3. Verify no external API degradation
4. Check memory utilization (GC pauses?)
5. Consider increasing container resources
