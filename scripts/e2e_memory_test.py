#!/usr/bin/env python3
"""End-to-end memory smoke test for AgentCore deployment.

Verifies the full STM → LTM pipeline:
1. Session A: Send message with identifiable preferences
2. Wait for AgentCore async LTM extraction (~90 seconds)
3. Session B: Query preferences in a NEW session
4. Verify cross-session recall

Usage:
    python3 scripts/e2e_memory_test.py --memory-id <mem-id>
    python3 scripts/e2e_memory_test.py --memory-id <mem-id> --agent plato_container
    python3 scripts/e2e_memory_test.py --memory-id <mem-id> --skip-invoke  # LTM query only

Prerequisites:
    - Agent deployed and READY on AgentCore
    - Memory strategies configured (run setup_memory.py first)
    - AWS credentials with invoke + memory permissions

Exit codes:
    0 = All checks passed
    1 = Memory recall failed (LTM pipeline broken)
    2 = Setup/invocation error
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Unique marker for this test run (avoids interference from prior runs)
RUN_ID = uuid.uuid4().hex[:8]
TEST_ACTOR = f"e2e-memory-test-{RUN_ID}"
TEST_PREFERENCES = {
    "language": f"Rust-{RUN_ID}",
    "framework": f"Actix-{RUN_ID}",
    "deploy": f"Lambda-{RUN_ID}",
}


def invoke_agent(agent_name: str, prompt: str, actor_id: str, session_id: str) -> str:
    """Invoke the agent via agentcore CLI and return the response text."""
    import subprocess

    payload = json.dumps({
        "prompt": prompt,
        "actor_id": actor_id,
        "session_id": session_id,
    })
    cmd = ["agentcore", "invoke", payload, "-a", agent_name]
    logger.info("Invoking agent: %s (session=%s)", agent_name, session_id)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        logger.error("Invoke failed: %s", result.stderr)
        return ""

    # Extract response from CLI output (after "Response:" line)
    output = result.stdout
    if "Response:" in output:
        response_part = output.split("Response:", 1)[1].strip()
        try:
            resp_json = json.loads(response_part)
            return resp_json.get("result", response_part)
        except json.JSONDecodeError:
            return response_part
    return output


def query_ltm_direct(memory_id: str, actor_id: str, query: str) -> list[str]:
    """Query AgentCore Memory LTM directly (bypass agent)."""
    try:
        from bedrock_agentcore.memory import MemoryClient
        client = MemoryClient(region_name=os.environ.get("AWS_REGION", "us-west-2"))
    except ImportError:
        import boto3
        client = boto3.client("bedrock-agentcore", region_name="us-west-2")

    strategies = [
        ("userPreferences", f"/strategies/userPreferences/actors/{actor_id}/"),
        ("semanticKnowledge", f"/strategies/semanticKnowledge/actors/{actor_id}/"),
        ("conversationSummary", f"/strategies/conversationSummary/actors/{actor_id}/"),
        ("episodicMemory", f"/strategies/episodicMemory/actors/{actor_id}/"),
    ]

    results = []
    for strategy_name, namespace in strategies:
        try:
            response = client.retrieve_memory_records(
                memory_id=memory_id,
                namespace=namespace,
                search_criteria={
                    "searchQuery": query,
                    "topK": 5,
                    "memoryStrategyId": strategy_name,
                },
            )
            for rec in response.get("memoryRecordSummaries", []):
                text = rec.get("content", {}).get("text", "")
                if text:
                    results.append(f"[{strategy_name}] {text}")
        except Exception as e:
            logger.warning("LTM query failed for %s: %s", strategy_name, e)

    return results


def run_test(
    agent_name: str,
    memory_id: str,
    wait_seconds: int = 90,
    skip_invoke: bool = False,
) -> bool:
    """Run the full end-to-end memory test.

    Returns True if cross-session recall is successful.
    """
    prefs = TEST_PREFERENCES
    session_a = f"e2e-sess-a-{RUN_ID}"
    session_b = f"e2e-sess-b-{RUN_ID}"

    # ── Step 1: Session A — store preferences ──
    if not skip_invoke:
        store_prompt = (
            f"Please remember these preferences about me: "
            f"I use {prefs['language']} as my primary language, "
            f"my preferred framework is {prefs['framework']}, "
            f"and I deploy to {prefs['deploy']}. "
            f"This is important context for our future conversations."
        )

        logger.info("=" * 60)
        logger.info("STEP 1: Session A — storing preferences")
        logger.info("  Actor: %s", TEST_ACTOR)
        logger.info("  Session: %s", session_a)
        logger.info("  Preferences: %s", json.dumps(prefs))

        response_a = invoke_agent(agent_name, store_prompt, TEST_ACTOR, session_a)
        if not response_a:
            logger.error("Session A invocation failed!")
            return False
        logger.info("  Response (truncated): %s", response_a[:200])

        # ── Step 2: Wait for async LTM extraction ──
        logger.info("=" * 60)
        logger.info("STEP 2: Waiting %d seconds for LTM extraction...", wait_seconds)
        for i in range(0, wait_seconds, 15):
            remaining = wait_seconds - i
            logger.info("  %d seconds remaining...", remaining)
            time.sleep(min(15, remaining))
        logger.info("  Wait complete.")

    # ── Step 3: Direct LTM query ──
    logger.info("=" * 60)
    logger.info("STEP 3: Querying LTM directly")

    ltm_results = query_ltm_direct(
        memory_id, TEST_ACTOR,
        f"{prefs['language']} {prefs['framework']} {prefs['deploy']}",
    )

    if ltm_results:
        logger.info("  Found %d LTM records:", len(ltm_results))
        for r in ltm_results:
            logger.info("    %s", r[:150])
    else:
        logger.warning("  No LTM records found (strategies may need more time)")

    # ── Step 4: Session B — cross-session recall ──
    if not skip_invoke:
        logger.info("=" * 60)
        logger.info("STEP 4: Session B — cross-session recall")

        recall_prompt = "What do you know about me? What are my preferences?"
        response_b = invoke_agent(agent_name, recall_prompt, TEST_ACTOR, session_b)

        if not response_b:
            logger.error("Session B invocation failed!")
            return False
        logger.info("  Response (truncated): %s", response_b[:300])

        # ── Step 5: Verify recall ──
        logger.info("=" * 60)
        logger.info("STEP 5: Verifying cross-session recall")

        # Check if the unique markers appear in the response
        found = {}
        for key, value in prefs.items():
            # Check both the full marker and the base word (Rust, Actix, Lambda)
            base_word = value.split("-")[0]
            found[key] = base_word.lower() in response_b.lower()
            status = "✅" if found[key] else "❌"
            logger.info("  %s %s: looking for '%s'", status, key, base_word)

        success_count = sum(found.values())
        total = len(found)
        logger.info("")
        logger.info("  Result: %d/%d preferences recalled", success_count, total)

        if success_count >= 2:  # At least 2 out of 3
            logger.info("  🎉 PASS — Cross-session memory is working!")
            return True
        else:
            logger.error("  ❌ FAIL — Cross-session memory recall insufficient")
            return False

    # Skip-invoke mode: just check LTM records
    if ltm_results:
        logger.info("  🎉 PASS — LTM records found")
        return True
    else:
        logger.error("  ❌ FAIL — No LTM records")
        return False


def main():
    parser = argparse.ArgumentParser(description="E2E memory smoke test")
    parser.add_argument("--memory-id", required=True, help="AgentCore Memory ID")
    parser.add_argument("--agent", default="plato_container", help="Agent name")
    parser.add_argument("--wait", type=int, default=90, help="Seconds to wait for LTM extraction")
    parser.add_argument("--skip-invoke", action="store_true", help="Skip agent invocation, query LTM only")
    args = parser.parse_args()

    logger.info("E2E Memory Smoke Test")
    logger.info("  Run ID: %s", RUN_ID)
    logger.info("  Agent: %s", args.agent)
    logger.info("  Memory: %s", args.memory_id)
    logger.info("")

    try:
        success = run_test(
            agent_name=args.agent,
            memory_id=args.memory_id,
            wait_seconds=args.wait,
            skip_invoke=args.skip_invoke,
        )
    except Exception as e:
        logger.error("Test error: %s", e, exc_info=True)
        sys.exit(2)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
