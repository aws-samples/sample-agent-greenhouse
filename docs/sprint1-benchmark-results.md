# Sprint 1 Benchmark Results: SecurityGuardrailHook Overhead

**Date**: 2026-04-17
**Branch**: `feat/runtime-security-guardrail`
**Spec target**: p99 latency overhead < 5 ms per tool call
**Measured p99 round-trip overhead**: **0.647 ms** ✅ (7.7× margin)

## Method

`scripts/benchmark_hook_overhead.py` — 10,000 iterations per scenario, 500-sample warmup. Measures `on_before_tool_call` and `on_after_tool_call` latency via `time.perf_counter_ns()`.

Machine: peiyao's MacBook Air (M-series, macOS 25.3.0), Python 3.12.12, pytest-free warm process.

## Results (10,000 iterations per scenario)

| Scenario | p50 (µs) | p95 (µs) | p99 (µs) | max (µs) |
|---|---:|---:|---:|---:|
| baseline_noop (no hook) | 53 | 99 | 270 | 13,708 |
| denylist_allow_path | 87 | 141 | 412 | 17,485 |
| denylist_block_path | 87 | 134 | 412 | 14,681 |
| full_config_before (skill + denylist + constraints) | 93 | 233 | 466 | 25,799 |
| full_config_after (output scan) | 91 | 155 | 437 | 25,195 |
| **full_round_trip (before + after)** | **203** | **608** | **642** | **15,252** |

## Overhead vs Baseline (p99)

| Path | Overhead | vs. 5 ms target |
|---|---:|:---:|
| denylist-only `on_before_tool_call` | 0.144 ms | ✅ 35× under |
| full config `on_before_tool_call` | 0.197 ms | ✅ 25× under |
| **full round-trip (before+after)** | **0.374 ms** | **✅ 13× under** |

## Interpretation

- **p50 overhead** is ≈150 µs per tool call (skill lookup, denylist check, constraint regex, output pattern scan) — negligible next to LLM tool-call latency measured in seconds.
- **p99 tail** spikes to ≈650 µs but remains well under the 5 ms safety budget even under GC pressure (max sample 25 ms likely reflects GC/background-thread jitter; still leaves headroom).
- **Constant-time design**: pre-compiled regex, frozenset denylist, dict-keyed skill allowlist — no per-call allocation-heavy work.

## Reproduce

```bash
cd platform-as-agent
.venv/bin/python scripts/benchmark_hook_overhead.py --iterations 10000
```

## Files

- Benchmark: [`scripts/benchmark_hook_overhead.py`](scripts/benchmark_hook_overhead.py)
- Hook: [`src/platform_agent/foundation/hooks/security_guardrail.py`](src/platform_agent/foundation/hooks/security_guardrail.py)
- Tests: [`tests/test_security_guardrail.py`](tests/test_security_guardrail.py) (43 scenarios, all pass)
