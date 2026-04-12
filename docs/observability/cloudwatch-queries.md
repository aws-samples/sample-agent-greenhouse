# CloudWatch Log Insights Queries — Plato Agent

Pre-built queries for monitoring Plato agent observability data.

---

## 1. Top Skills by Usage (Last 7 Days)

```sql
fields @timestamp, skill_name
| filter skill_name != ""
| stats count(*) as invocations by skill_name
| sort invocations desc
| limit 10
```

## 2. Slowest Tool Calls (p99)

```sql
fields @timestamp, tool_name, duration_ms
| filter event = "tool_call_complete"
| stats percentile(duration_ms, 99) as p99,
        percentile(duration_ms, 50) as p50,
        avg(duration_ms) as avg_ms,
        count(*) as calls
  by tool_name
| sort p99 desc
```

## 3. Token Usage by Skill per Day

```sql
fields @timestamp, skill_name, input_tokens, output_tokens
| filter event = "model_call_complete"
| stats sum(input_tokens) as total_input,
        sum(output_tokens) as total_output,
        count(*) as model_calls
  by skill_name, bin(1d)
| sort bin(1d) desc
```

## 4. Error Rate by Tool

```sql
fields @timestamp, tool_name, status
| filter event = "tool_call_complete"
| stats count(*) as total,
        sum(case when status = "error" then 1 else 0 end) as errors
  by tool_name
| display tool_name, total, errors, (errors * 100.0 / total) as error_rate_pct
| sort error_rate_pct desc
```

## 5. Invocation Duration Distribution

```sql
fields @timestamp, duration_ms, skill_name
| filter event = "invocation_complete"
| stats percentile(duration_ms, 50) as p50,
        percentile(duration_ms, 90) as p90,
        percentile(duration_ms, 99) as p99,
        avg(duration_ms) as avg_ms,
        min(duration_ms) as min_ms,
        max(duration_ms) as max_ms,
        count(*) as invocations
  by skill_name
| sort avg_ms desc
```
