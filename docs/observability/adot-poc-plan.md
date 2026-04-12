# ADOT SDK Impact PoC Plan

> Part of the Plato Observability stack (Phase 4).

## Objective

Measure the impact of adding the AWS Distro for OpenTelemetry (ADOT) SDK
to the Plato agent container before committing to full integration. The ADOT
SDK enables custom OTEL spans visible in CloudWatch Transaction Search and
the GenAI Observability Dashboard.

---

## Current Baseline

| Metric | Current Value | Source |
|--------|--------------|--------|
| Container image size | ~TBD MB | `docker images plato-agent` |
| Cold start latency | ~TBD s | AgentCore CloudWatch metrics |
| Python dependencies | 4 direct deps | `requirements.txt` |
| Agent invocation latency (p50) | ~TBD ms | CloudWatch Plato/Agent namespace |

**Baseline collection:**

```bash
# Record image size
docker images plato-agent --format "{{.Size}}"

# Record cold start from AgentCore metrics (last 7 days)
aws cloudwatch get-metric-statistics \
  --namespace "AWS/AgentCore" \
  --metric-name "ColdStartLatency" \
  --start-time "$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 3600 \
  --statistics Average p50 p99
```

---

## Test Plan

### Step 1: Add ADOT SDK dependency

Add to `requirements.txt`:

```
aws-opentelemetry-distro>=0.10.0
```

This pulls in transitive dependencies:
- `opentelemetry-api`
- `opentelemetry-sdk`
- `opentelemetry-exporter-otlp`
- `opentelemetry-instrumentation` (various)

### Step 2: Rebuild container

```bash
docker build -t plato-agent:adot-poc .
```

### Step 3: Measure image size delta

```bash
# Compare sizes
docker images plato-agent --format "{{.Repository}}:{{.Tag}} {{.Size}}"

# Calculate delta
echo "Baseline: $(docker inspect plato-agent:latest --format '{{.Size}}')"
echo "With ADOT: $(docker inspect plato-agent:adot-poc --format '{{.Size}}')"
```

### Step 4: Measure cold start delta

Deploy the PoC image to a staging AgentCore endpoint and measure:

```bash
# Invoke agent cold (after scale-to-zero)
time aws bedrock-agent-runtime invoke-agent \
  --agent-id STAGING_AGENT_ID \
  --session-id "poc-coldstart-$(date +%s)" \
  --input-text "Hello"

# Repeat 5 times with fresh sessions, take median
```

### Step 5: Measure warm invocation latency impact

```bash
# 10 sequential invocations on warm container
for i in $(seq 1 10); do
  time aws bedrock-agent-runtime invoke-agent \
    --agent-id STAGING_AGENT_ID \
    --session-id "poc-warm-test" \
    --input-text "What time is it?"
done
```

---

## Accept / Reject Criteria

| Metric | Accept Threshold | Reject Threshold |
|--------|-----------------|------------------|
| Image size increase | < 50 MB | >= 50 MB |
| Cold start increase | < 2 s | >= 2 s |
| Warm latency increase | < 100 ms (p50) | >= 100 ms |

---

## Rollback Plan

If criteria are NOT met:

1. Remove `aws-opentelemetry-distro` from `requirements.txt`
2. Rebuild container without ADOT SDK
3. Continue using CloudWatch EMF for metrics (current approach)
4. Re-evaluate when ADOT SDK size is reduced or AgentCore provides
   built-in OTEL span support

---

## Implementation Steps (If Accepted)

1. **Add dependency**: `aws-opentelemetry-distro>=0.10.0` to `requirements.txt`
2. **Configure OTEL exporter**: Set environment variables in container:
   ```
   OTEL_SERVICE_NAME=plato-agent
   OTEL_EXPORTER_OTLP_ENDPOINT=<AgentCore OTEL endpoint>
   OTEL_TRACES_EXPORTER=otlp
   OTEL_METRICS_EXPORTER=none  # Continue using EMF for metrics
   ```
3. **Enable OTELSpanHook**: Already implemented with graceful degradation.
   With OTEL installed, it automatically creates spans.
4. **Verify in Transaction Search**: Confirm `plato.invoke`, `plato.tool.*`,
   and `plato.model.invoke` spans appear in CloudWatch Transaction Search.
5. **Configure GenAI Dashboard**: Add Plato agent to the GenAI Observability
   Dashboard in CloudWatch console.
6. **Update SLO alarms**: Add trace-based alarms for span error rates.

---

## Timeline

- PoC execution: 1 day
- Results analysis: 0.5 day
- Decision gate: Review with team
- Full integration (if accepted): 2-3 days
