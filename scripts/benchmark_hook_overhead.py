#!/usr/bin/env python3
"""Benchmark SecurityGuardrailHook overhead on tool-call path.

Measures p50/p99 latency for `on_before_tool_call` + `on_after_tool_call`
under three configurations:
  1. Baseline (no hook)                      — establishes tool-call overhead
  2. Hook with harness denylist only         — the minimum-work path
  3. Hook with skill + denylist + constraints — realistic production config

Target per spec (sprint1-task1-spec.md): < 5 ms p99 overhead per tool call.

Run:
    python scripts/benchmark_hook_overhead.py [--iterations 10000]

Outputs JSON + human-readable summary to stdout.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

# Make src/ importable when run from repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from platform_agent.foundation.hooks.security_guardrail import (  # noqa: E402
    Constraint,
    RuleSet,
    SecurityGuardrailHook,
)


# --------------------------------------------------------------------------
# Test fixtures (mirrors tests/test_security_guardrail.py)
# --------------------------------------------------------------------------


@dataclass
class FakeSkill:
    name: str
    allowed_tools: list[str] | None = None


class FakeSkillsPlugin:
    def __init__(self, skills: list[FakeSkill]) -> None:
        self._skills = skills

    def get_available_skills(self) -> list[FakeSkill]:
        return list(self._skills)


def make_event(tool_name: str = "Read", activated_skills: list[str] | None = None,
               tool_input: dict | None = None) -> MagicMock:
    event = MagicMock()
    event.tool_use = {
        "toolUseId": "tu_bench",
        "name": tool_name,
        "input": tool_input or {"path": "/tmp/foo.txt"},
    }
    event.cancel_tool = False
    agent = MagicMock()
    state: dict = {}
    if activated_skills is not None:
        state["agent_skills"] = {"activated_skills": list(activated_skills)}
    agent.state = state
    event.agent = agent
    return event


def make_after_event(tool_name: str = "Read",
                     activated_skills: list[str] | None = None,
                     tool_result: str = "file contents here") -> MagicMock:
    event = make_event(tool_name, activated_skills)
    event.result = tool_result
    return event


def make_harness(denylist: list[str] | None = None) -> MagicMock:
    harness = MagicMock()
    policies = MagicMock()
    policies.tool_denylist = denylist or []
    harness.policies = policies
    return harness


# --------------------------------------------------------------------------
# Benchmark drivers
# --------------------------------------------------------------------------


def bench(label: str, fn, iterations: int, warmup: int = 500) -> dict:
    # warmup to stabilize JIT/caches
    for _ in range(warmup):
        fn()

    samples_ns: list[int] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fn()
        samples_ns.append(time.perf_counter_ns() - t0)

    samples_us = [n / 1_000.0 for n in samples_ns]  # microseconds
    samples_ms = [n / 1_000_000.0 for n in samples_ns]  # milliseconds

    return {
        "label": label,
        "iterations": iterations,
        "p50_us": round(statistics.median(samples_us), 3),
        "p95_us": round(sorted(samples_us)[int(0.95 * len(samples_us))], 3),
        "p99_us": round(sorted(samples_us)[int(0.99 * len(samples_us))], 3),
        "max_us": round(max(samples_us), 3),
        "mean_us": round(statistics.mean(samples_us), 3),
        "p50_ms": round(statistics.median(samples_ms), 4),
        "p99_ms": round(sorted(samples_ms)[int(0.99 * len(samples_ms))], 4),
    }


def main(iterations: int) -> int:
    print(f"Benchmarking SecurityGuardrailHook (iterations={iterations})...")
    print()

    # --- Scenario 1: baseline no-op (measures harness dispatch floor) ---
    def baseline_noop():
        ev = make_event(tool_name="Read")
        # simulate what happens when no hook is present — just a dict read
        _ = ev.cancel_tool

    b1 = bench("baseline_noop", baseline_noop, iterations)

    # --- Scenario 2: denylist-only hook ---
    hook_deny = SecurityGuardrailHook(
        harness=make_harness(denylist=["dangerous_tool", "another_bad"]),
    )

    def deny_before_allow():
        ev = make_event(tool_name="Read")
        hook_deny.on_before_tool_call(ev)

    def deny_before_block():
        ev = make_event(tool_name="dangerous_tool")
        hook_deny.on_before_tool_call(ev)

    b2 = bench("denylist_allow_path", deny_before_allow, iterations)
    b3 = bench("denylist_block_path", deny_before_block, iterations)

    # --- Scenario 3: production config (skill + denylist + constraints) ---
    plugin = FakeSkillsPlugin([
        FakeSkill("code-review", ["Read", "Glob", "Grep"]),
        FakeSkill("scaffold", ["Read", "Write", "Edit", "Bash", "Glob"]),
        FakeSkill("deployment-config",
                  ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]),
    ])
    ruleset = RuleSet(
        parameter_constraints={
            "Read": [Constraint(param_name="path", constraint_type="regex", pattern=r"^/.*")],
            "Write": [Constraint(param_name="path", constraint_type="regex", pattern=r"^/.*")],
        },
    )
    hook_full = SecurityGuardrailHook(
        harness=make_harness(denylist=["dangerous_tool"]),
        skills_plugin=plugin,
        ruleset=ruleset,
    )

    def full_before_allow():
        ev = make_event(
            tool_name="Read",
            activated_skills=["code-review"],
            tool_input={"path": "/tmp/foo.txt"},
        )
        hook_full.on_before_tool_call(ev)

    def full_after():
        ev = make_after_event(
            tool_name="Read",
            activated_skills=["code-review"],
            tool_result="normal text output without any injection patterns whatsoever",
        )
        hook_full.on_after_tool_call(ev)

    b4 = bench("full_config_before", full_before_allow, iterations)
    b5 = bench("full_config_after", full_after, iterations)

    # --- Combined: before + after (full tool-call overhead) ---
    def full_round_trip():
        ev_b = make_event(
            tool_name="Read",
            activated_skills=["code-review"],
            tool_input={"path": "/tmp/foo.txt"},
        )
        hook_full.on_before_tool_call(ev_b)
        ev_a = make_after_event(
            tool_name="Read",
            activated_skills=["code-review"],
            tool_result="clean output",
        )
        hook_full.on_after_tool_call(ev_a)

    b6 = bench("full_round_trip", full_round_trip, iterations)

    results = [b1, b2, b3, b4, b5, b6]

    # --- Overhead analysis ---
    baseline_p99 = b1["p99_us"]
    overhead = {
        "denylist_allow_p99_overhead_us": round(b2["p99_us"] - baseline_p99, 3),
        "full_before_p99_overhead_us": round(b4["p99_us"] - baseline_p99, 3),
        "full_round_trip_p99_overhead_us": round(b6["p99_us"] - baseline_p99, 3),
    }

    # --- Pretty output ---
    print(f"{'Scenario':<28} {'p50 (µs)':>10} {'p95 (µs)':>10} {'p99 (µs)':>10} {'max (µs)':>10}")
    print("-" * 70)
    for r in results:
        print(f"{r['label']:<28} {r['p50_us']:>10.2f} {r['p95_us']:>10.2f} "
              f"{r['p99_us']:>10.2f} {r['max_us']:>10.2f}")

    print()
    print("Overhead vs. baseline (p99):")
    for k, v in overhead.items():
        ms = v / 1000
        status = "✅ PASS" if ms < 5 else "❌ FAIL"
        print(f"  {k:<40} {v:>8.2f} µs  ({ms:.4f} ms)  [{status}]")

    full_round_p99_ms = b6["p99_ms"]
    print()
    print(f"Target: p99 < 5 ms per tool call (before+after).")
    print(f"Measured: p99 = {full_round_p99_ms:.4f} ms  "
          f"({'✅ PASS' if full_round_p99_ms < 5 else '❌ FAIL'})")

    # --- JSON block for machine-readable log ---
    print()
    print("=== JSON RESULTS ===")
    print(json.dumps({
        "iterations": iterations,
        "scenarios": results,
        "overhead_vs_baseline": overhead,
        "target_p99_ms": 5.0,
        "measured_full_round_trip_p99_ms": full_round_p99_ms,
        "pass": full_round_p99_ms < 5,
    }, indent=2))

    return 0 if full_round_p99_ms < 5 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark SecurityGuardrailHook overhead")
    parser.add_argument("--iterations", type=int, default=10_000,
                        help="Number of samples per scenario (default: 10000)")
    args = parser.parse_args()
    sys.exit(main(args.iterations))
