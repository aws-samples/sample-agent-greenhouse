# Plato Agent — SLO Alarm Definitions

> **Status**: Active
> **Date**: 2026-04-04
> **Traces to**: observability-design.md (all layers)

---

## Overview

Five SLO-based CloudWatch alarms covering agent reliability, latency, tool health, AIDLC completion, and cost control. Each alarm routes to an SNS topic for Slack notification.

### SNS Topic (shared)

```bash
aws sns create-topic --name plato-slo-alerts
# Subscribe a Slack webhook or AWS Chatbot channel to this topic.
```

---

## 1. Invocation Success Rate SLO (Metric Math)

**Target**: >99% success rate
**Alert**: <95% for 5 consecutive minutes

Uses metric math: `100 - (ToolErrorCount / ToolCallCount * 100)`.
Requires both `ToolCallCount` and `ToolErrorCount` from TelemetryHook (`Plato/Agent` namespace).

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "Plato-InvocationSuccessRate-SLO" \
  --alarm-description "Invocation success rate dropped below 95% for 5 minutes (SLO target: >99%)" \
  --metrics '[
    {"Id":"errors","MetricStat":{"Metric":{"Namespace":"Plato/Agent","MetricName":"ToolErrorCount"},"Period":60,"Stat":"Sum"},"ReturnData":false},
    {"Id":"total","MetricStat":{"Metric":{"Namespace":"Plato/Agent","MetricName":"ToolCallCount"},"Period":60,"Stat":"Sum"},"ReturnData":false},
    {"Id":"success_rate","Expression":"100 - (errors / total * 100)","Label":"SuccessRate","ReturnData":true}
  ]' \
  --evaluation-periods 5 \
  --threshold 95 \
  --comparison-operator LessThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts" \
  --ok-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts"
```

---

## 2. Invocation Latency p99 SLO

**Target**: p99 < 30s (30,000ms)
**Alert**: p99 > 60s (60,000ms) for 10 consecutive minutes

Uses `SkillInvocationDuration` (Milliseconds) from TelemetryHook.

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "Plato-InvocationLatencyP99-SLO" \
  --alarm-description "Invocation p99 latency exceeded 60s for 10 minutes (SLO target: p99 < 30s)" \
  --namespace "Plato/Agent" \
  --metric-name "SkillInvocationDuration" \
  --extended-statistic p99 \
  --period 60 \
  --evaluation-periods 10 \
  --threshold 60000 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts" \
  --ok-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts"
```

---

## 3. Tool Error Rate SLO (Metric Math)

**Target**: <5% tool error rate
**Alert**: >10% for 5 consecutive minutes

Uses metric math: `ToolErrorCount / ToolCallCount * 100`.

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "Plato-ToolErrorRate-SLO" \
  --alarm-description "Tool error rate exceeded 10% for 5 minutes (SLO target: <5%)" \
  --metrics '[
    {"Id":"errors","MetricStat":{"Metric":{"Namespace":"Plato/Agent","MetricName":"ToolErrorCount"},"Period":60,"Stat":"Sum"},"ReturnData":false},
    {"Id":"total","MetricStat":{"Metric":{"Namespace":"Plato/Agent","MetricName":"ToolCallCount"},"Period":60,"Stat":"Sum"},"ReturnData":false},
    {"Id":"error_rate","Expression":"errors / total * 100","Label":"ErrorRate","ReturnData":true}
  ]' \
  --evaluation-periods 5 \
  --threshold 10 \
  --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts" \
  --ok-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts"
```

---

## 4. AIDLC Completion Rate SLO

**Target**: >50% of started workflows complete
**Alert**: <30% for 7 consecutive days

Uses `AIDLCWorkflowCompleted` (Count) from AIDLCTelemetryHook (`Plato/AIDLC` namespace).

> **Note**: This alarm compares raw completion count against a threshold.
> For true rate-based alerting, a separate `AIDLCWorkflowStarted` metric
> (emitted by the hook on `workflow_started` events) would be needed.
> Phase 3 enhancement.

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "Plato-AIDLCCompletionRate-SLO" \
  --alarm-description "AIDLC completion count dropped below 30 for 7 days (SLO target: >50%)" \
  --namespace "Plato/AIDLC" \
  --metric-name "AIDLCWorkflowCompleted" \
  --statistic Sum \
  --period 86400 \
  --evaluation-periods 7 \
  --threshold 30 \
  --comparison-operator LessThanThreshold \
  --treat-missing-data breaching \
  --alarm-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts" \
  --ok-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts"
```

---

## 5. Token Cost Per Day SLO

**Status**: ⏸️ Deferred to Phase 4 (OTEL integration)

**Target**: <$500/day
**Alert**: >$1000 for 1 day

> **Blocked**: Token usage tracking was removed in Phase 1 P0 fix — Strands
> `AfterModelCallEvent` does not expose `usage` data. The `ModelEstimatedCostUSD`
> metric will be available once OTEL-based token tracking is implemented in
> Phase 4. This alarm definition is preserved for future activation.

```bash
# Phase 4 — uncomment when ModelEstimatedCostUSD metric is available:
# aws cloudwatch put-metric-alarm \
#   --alarm-name "Plato-TokenCostPerDay-SLO" \
#   --alarm-description "Daily token cost exceeded $1000 (SLO target: <$500/day)" \
#   --namespace "Plato/Agent" \
#   --metric-name "ModelEstimatedCostUSD" \
#   --statistic Sum \
#   --period 86400 \
#   --evaluation-periods 1 \
#   --threshold 1000 \
#   --comparison-operator GreaterThanThreshold \
#   --treat-missing-data notBreaching \
#   --alarm-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts" \
#   --ok-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-slo-alerts"
```

---

## Summary

| # | Alarm | Namespace | Metric(s) | SLO Target | Alert Threshold | Eval Window | Status |
|---|-------|-----------|-----------|------------|----------------|-------------|--------|
| 1 | Invocation Success Rate | Plato/Agent | ToolErrorCount / ToolCallCount (math) | >99% | <95% | 5 min | ✅ Active |
| 2 | Invocation Latency p99 | Plato/Agent | SkillInvocationDuration | <30s | >60s | 10 min | ✅ Active |
| 3 | Tool Error Rate | Plato/Agent | ToolErrorCount / ToolCallCount (math) | <5% | >10% | 5 min | ✅ Active |
| 4 | AIDLC Completion Rate | Plato/AIDLC | AIDLCWorkflowCompleted | >50% | <30 count | 7 days | ✅ Active |
| 5 | Token Cost Per Day | Plato/Agent | ModelEstimatedCostUSD | <$500 | >$1000 | 1 day | ⏸️ Phase 4 |

### Actual Metrics Emitted (reference)

| Hook | Namespace | Metrics |
|------|-----------|---------|
| TelemetryHook | Plato/Agent | SkillInvocationDuration (ms), SkillInvocationCount, ToolCallDuration (ms), ToolCallCount, ToolErrorCount |
| ModelMetricsHook | Plato/Agent | ModelCallLatency (ms), ModelCallCount |
| AIDLCTelemetryHook | Plato/AIDLC | AIDLCStageDuration (ms), AIDLCApprovalWaitTime (ms), AIDLCReworkCount, AIDLCWorkflowCompleted |
