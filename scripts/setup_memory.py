#!/usr/bin/env python3
"""Setup AgentCore Memory — create strategies with optional verification.

Creates all 4 built-in strategies (Semantic, UserPreference, Summary, Episodic)
idempotently.

Platform files (SOUL.md, IDENTITY.md) are baked into the container image at
build time — no runtime seeding needed. User memory is handled entirely by
AgentCore Memory with API-level namespace isolation.

Requires:
- boto3 with bedrock-agentcore-control service support
- IAM permissions: bedrock-agentcore-control:UpdateMemory, GetMemory
- AGENTCORE_MEMORY_ID env var or --memory-id argument

Usage:
    python3 scripts/setup_memory.py --memory-id mem-abc123
    python3 scripts/setup_memory.py --memory-id mem-abc123 --verify
    python3 scripts/setup_memory.py --memory-id mem-abc123 --seed
    python3 scripts/setup_memory.py --memory-id mem-abc123 --verify --seed

API notes (learned during deploy):
- Field is "namespaces" not "namespaceTemplates"
- Summary strategy REQUIRES {sessionId} in namespace
- Episodic strategy REQUIRES reflectionConfiguration with matching namespace
  (reflection namespace must be same as or prefix of episodic namespace)
- Adding all strategies at once may fail with generic "Invalid memory strategy input";
  add one at a time to get specific error messages
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


# Namespace patterns with actor isolation
ACTOR_NS = "/strategies/{memoryStrategyId}/actors/{actorId}/"
SESSION_NS = "/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}/"

# All 4 built-in strategy configurations
STRATEGIES: list[tuple[str, dict[str, Any]]] = [
    (
        "Semantic",
        {
            "semanticMemoryStrategy": {
                "name": "semanticKnowledge",
                "description": (
                    "Extracts factual knowledge, technical decisions, and domain "
                    "concepts from conversations for semantic retrieval."
                ),
                "namespaces": [ACTOR_NS],
            }
        },
    ),
    (
        "Summary",
        {
            "summaryMemoryStrategy": {
                "name": "conversationSummary",
                "description": (
                    "Summarizes each conversation session. Used at the start of "
                    "new sessions to provide context about what was previously discussed."
                ),
                "namespaces": [SESSION_NS],
            }
        },
    ),
    (
        "UserPreference",
        {
            "userPreferenceMemoryStrategy": {
                "name": "userPreferences",
                "description": (
                    "Extracts user preferences and working style from conversations. "
                    "E.g., 'prefers serverless', 'uses ECS Fargate', 'team of 5'."
                ),
                "namespaces": [ACTOR_NS],
            }
        },
    ),
    (
        "Episodic",
        {
            "episodicMemoryStrategy": {
                "name": "episodicMemory",
                "description": (
                    "Captures episodic memories — what happened in each interaction. "
                    "Better than summary for 'what did we discuss last time?' queries."
                ),
                "namespaces": [ACTOR_NS],
                "reflectionConfiguration": {
                    "namespaces": [ACTOR_NS],
                },
            }
        },
    ),
]


def create_strategies(
    memory_id: str,
    region: str,
    dry_run: bool = False,
) -> dict[str, str]:
    """Create all 4 strategies on a Memory resource idempotently.

    Adds strategies one at a time for better error isolation.

    Args:
        memory_id: The AgentCore Memory resource ID.
        region: AWS region.
        dry_run: If True, print API calls without executing.

    Returns:
        Dict mapping strategy label to status ("created", "exists", "failed: ...").
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    results: dict[str, str] = {}

    if dry_run:
        for label, strategy in STRATEGIES:
            print(f"\n--- {label} ---")
            print(json.dumps({
                "memoryId": memory_id,
                "memoryStrategies": {"addMemoryStrategies": [strategy]},
            }, indent=2, default=str))
            results[label] = "dry_run"
        return results

    print(f"Adding strategies to memory {memory_id} in {region}...\n")

    for label, strategy in STRATEGIES:
        try:
            client.update_memory(
                memoryId=memory_id,
                memoryStrategies={"addMemoryStrategies": [strategy]},
            )
            print(f"  [OK] {label} added successfully")
            results[label] = "created"
        except client.exceptions.ValidationException as e:
            error_msg = str(e)
            if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                print(f"  [SKIP] {label} already exists")
                results[label] = "exists"
            else:
                print(f"  [FAIL] {label}: {e}")
                results[label] = f"failed: {e}"
        except Exception as e:
            print(f"  [FAIL] {label}: {e}")
            results[label] = f"failed: {e}"

    return results


def verify_strategies(memory_id: str, region: str) -> list[dict[str, str]]:
    """Verify current strategies on a Memory resource.

    Args:
        memory_id: The AgentCore Memory resource ID.
        region: AWS region.

    Returns:
        List of strategy info dicts with name, type, and id.
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)
    strategies_info: list[dict[str, str]] = []

    try:
        mem = client.get_memory(memoryId=memory_id)
        for strategy in mem.get("memoryStrategies", []):
            info = {
                "name": strategy.get("name", "?"),
                "type": strategy.get("type", "?"),
                "id": strategy.get("memoryStrategyId", "?"),
            }
            strategies_info.append(info)
            print(f"  * {info['name']} ({info['type']}): {info['id']}")
    except Exception as e:
        print(f"  Could not verify: {e}")

    return strategies_info


def main() -> None:
    """CLI entry point for memory setup."""
    parser = argparse.ArgumentParser(
        description="Setup AgentCore Memory — create strategies"
    )
    parser.add_argument(
        "--memory-id",
        default=os.environ.get("AGENTCORE_MEMORY_ID", ""),
        help="Memory resource ID (default: AGENTCORE_MEMORY_ID env var)",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("PLATO_REGION", "us-west-2"),
        help="AWS region (default: us-west-2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the API calls without executing",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify current strategies after creation",
    )
    args = parser.parse_args()

    if not args.memory_id:
        print("ERROR: --memory-id or AGENTCORE_MEMORY_ID env var required")
        sys.exit(1)

    # Step 1: Create strategies
    create_strategies(args.memory_id, args.region, args.dry_run)

    # Step 2: Verify (optional)
    if args.verify and not args.dry_run:
        print("\nVerifying strategies...")
        verify_strategies(args.memory_id, args.region)

    if not args.dry_run:
        print("\nDone! Strategies will extract from future events automatically.")
        print("To reprocess existing events: use StartMemoryExtractionJob API.")


if __name__ == "__main__":
    main()
