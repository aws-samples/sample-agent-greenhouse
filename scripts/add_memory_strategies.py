#!/usr/bin/env python3
"""Add Summary + UserPreference + Episodic strategies to existing Memory resource.

Phase 2 of AgentCore Memory integration. Requires:
- boto3 with bedrock-agentcore-control service support
- IAM permissions: bedrock-agentcore-control:UpdateMemory
- AGENTCORE_MEMORY_ID env var or --memory-id argument

Usage:
    python3 scripts/add_memory_strategies.py
    python3 scripts/add_memory_strategies.py --memory-id plato_agent_memory-WV8Ei557t4
    python3 scripts/add_memory_strategies.py --region us-west-2 --dry-run

API notes (learned during deploy):
- Field is "namespaces" not "namespaceTemplates"
- Summary strategy REQUIRES {sessionId} in namespace
- Episodic strategy REQUIRES reflectionConfiguration with matching namespace
  (reflection namespace must be same as or prefix of episodic namespace)
- Adding all 3 at once may fail with generic "Invalid memory strategy input";
  add one at a time to get specific error messages
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def add_strategies(memory_id: str, region: str, dry_run: bool = False) -> None:
    """Add Summary, UserPreference, and Episodic strategies to a Memory resource.

    Adds strategies one at a time for better error isolation.
    """
    import boto3

    client = boto3.client("bedrock-agentcore-control", region_name=region)

    # Namespace patterns with actor isolation
    actor_ns = "/strategies/{memoryStrategyId}/actors/{actorId}/"
    # Summary requires {sessionId} in namespace
    session_ns = "/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}/"

    strategies = [
        (
            "Summary",
            {
                "summaryMemoryStrategy": {
                    "name": "conversationSummary",
                    "description": (
                        "Summarizes each conversation session. Used at the start of "
                        "new sessions to provide context about what was previously discussed."
                    ),
                    "namespaces": [session_ns],
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
                    "namespaces": [actor_ns],
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
                    "namespaces": [actor_ns],
                    # reflectionConfiguration is required; namespace must match
                    # or be a prefix of the episodic namespace
                    "reflectionConfiguration": {
                        "namespaces": [actor_ns],
                    },
                }
            },
        ),
    ]

    if dry_run:
        for label, strategy in strategies:
            print(f"\n--- {label} ---")
            print(json.dumps({
                "memoryId": memory_id,
                "memoryStrategies": {"addMemoryStrategies": [strategy]},
            }, indent=2, default=str))
        return

    print(f"Adding strategies to memory {memory_id} in {region}...\n")

    for label, strategy in strategies:
        try:
            client.update_memory(
                memoryId=memory_id,
                memoryStrategies={"addMemoryStrategies": [strategy]},
            )
            print(f"  ✅ {label} added successfully")
        except client.exceptions.ValidationException as e:
            error_msg = str(e)
            if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                print(f"  ⏭️  {label} already exists, skipping")
            else:
                print(f"  ❌ {label} failed: {e}")
        except Exception as e:
            print(f"  ❌ {label} failed: {e}")

    print("\nDone! Verifying final state...")

    # Show current strategies
    try:
        mem = client.get_memory(memoryId=memory_id)
        for strategy in mem.get("memoryStrategies", []):
            name = strategy.get("name", "?")
            stype = strategy.get("type", "?")
            sid = strategy.get("memoryStrategyId", "?")
            print(f"  • {name} ({stype}): {sid}")
    except Exception as e:
        print(f"  Could not verify: {e}")

    print("\nStrategies will extract from future events automatically.")
    print("To reprocess existing events: use StartMemoryExtractionJob API.")


def main():
    parser = argparse.ArgumentParser(
        description="Add memory strategies to AgentCore Memory resource"
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
    args = parser.parse_args()

    if not args.memory_id:
        print("ERROR: --memory-id or AGENTCORE_MEMORY_ID env var required")
        sys.exit(1)

    add_strategies(args.memory_id, args.region, args.dry_run)


if __name__ == "__main__":
    main()
