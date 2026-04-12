# Composite Alarms

> Part of the Plato Observability stack (Phase 4).

Composite alarms aggregate multiple SLO alarms into a single actionable signal.
They reduce alert fatigue and provide a single pane for infrastructure health
and quality health.

---

## 1. Infrastructure Composite Alarm

**Purpose**: Fires when ANY infrastructure SLO is breached.

**Trigger rule** (OR logic):
- `ALARM(Plato-InvocationSuccessRate-SLO)` — success rate < 95% for 5 min
- `ALARM(Plato-InvocationLatencyP99-SLO)` — p99 latency > 60s for 10 min
- `ALARM(Plato-ToolErrorRate-SLO)` — tool error rate > 10% for 5 min

**Composite alarm rule expression:**

```
ALARM("Plato-InvocationSuccessRate-SLO") OR ALARM("Plato-InvocationLatencyP99-SLO") OR ALARM("Plato-ToolErrorRate-SLO")
```

**CLI command:**

```bash
aws cloudwatch put-composite-alarm \
  --alarm-name "Plato-Infrastructure-Composite" \
  --alarm-description "Fires when any Plato infrastructure SLO is breached (success rate, latency, or tool errors)" \
  --alarm-rule 'ALARM("Plato-InvocationSuccessRate-SLO") OR ALARM("Plato-InvocationLatencyP99-SLO") OR ALARM("Plato-ToolErrorRate-SLO")' \
  --actions-enabled \
  --alarm-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-alerts-p1" \
  --tags Key=Project,Value=Plato Key=Phase,Value=Observability
```

**Severity**: P1 — pages on-call.

---

## 2. Quality Composite Alarm

**Purpose**: Fires when quality metrics indicate degraded output quality.

**Current trigger** (Phase 4 scope — AIDLC completion only):
- `ALARM(Plato-AIDLCCompletionRate-SLO)` — completion rate < 30% for 7 days

**Future additions** (require metrics not yet available):
- Spec completeness alarm (needs `plato.quality.spec_completeness_score` metric)
- Hallucination rate alarm (needs `plato.quality.hallucination_detected` metric from async Lambda)

**Phase 4 alarm rule expression:**

```
ALARM("Plato-AIDLCCompletionRate-SLO")
```

**Future alarm rule expression** (when spec completeness and hallucination alarms exist):

```
ALARM("Plato-AIDLCCompletionRate-SLO") OR ALARM("Plato-SpecCompleteness-SLO") OR ALARM("Plato-HallucinationRate-SLO")
```

**CLI command (Phase 4):**

```bash
aws cloudwatch put-composite-alarm \
  --alarm-name "Plato-Quality-Composite" \
  --alarm-description "Fires when AIDLC completion rate drops below SLO threshold. Future: spec completeness + hallucination rate." \
  --alarm-rule 'ALARM("Plato-AIDLCCompletionRate-SLO")' \
  --actions-enabled \
  --alarm-actions "arn:aws:sns:us-west-2:ACCOUNT_ID:plato-alerts-p2" \
  --tags Key=Project,Value=Plato Key=Phase,Value=Observability
```

**Severity**: P3 — weekly review.

---

## Prerequisite Alarms

Both composite alarms depend on the underlying SLO alarms defined in
[slo-alarms.md](./slo-alarms.md):

| Alarm Name | Metric | Condition |
|-----------|--------|-----------|
| `Plato-InvocationSuccessRate-SLO` | InvocationSuccessRate | < 95% for 5 min |
| `Plato-InvocationLatencyP99-SLO` | InvocationLatencyP99 | > 60s for 10 min |
| `Plato-ToolErrorRate-SLO` | ToolErrorRate | > 10% for 5 min |
| `Plato-AIDLCCompletionRate-SLO` | AIDLCCompletionRate | < 30% for 7 days |

---

## Alert Routing

```
Composite Alarm → SNS Topic → Lambda → Slack #plato-alerts
                            → Email (P1 only)
                            → PagerDuty (P1 only, future)
```
