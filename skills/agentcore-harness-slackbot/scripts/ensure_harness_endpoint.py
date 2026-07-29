#!/usr/bin/env python3
"""Create or update a named AgentCore Harness endpoint and wait for readiness."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as error:
        raise ValueError(f"Required file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error


def project_values(
    project_root: Path,
    *,
    target: str,
    harness_name: str | None,
) -> tuple[str, str, str]:
    state_path = project_root / "agentcore" / ".cli" / "deployed-state.json"
    state = load_json(state_path)
    target_state = state.get("targets", {}).get(target, {})
    resources = target_state.get("resources", {})
    harnesses = resources.get("harnesses", {})
    if not isinstance(harnesses, dict) or not harnesses:
        raise ValueError(
            f"No deployed Harness found for target {target!r} in {state_path}"
        )

    if harness_name is None:
        if len(harnesses) != 1:
            names = ", ".join(sorted(harnesses))
            raise ValueError(f"Select --harness-name from: {names}")
        harness_name = next(iter(harnesses))
    details = harnesses.get(harness_name)
    if not isinstance(details, dict):
        names = ", ".join(sorted(harnesses))
        raise ValueError(f"Harness {harness_name!r} not found. Available: {names}")

    harness_id = details.get("harnessId")
    version = details.get("harnessVersion")
    if not isinstance(harness_id, str) or not harness_id:
        raise ValueError(f"Harness {harness_name!r} has no harnessId in deployed state")
    if not isinstance(version, (str, int)):
        raise ValueError(
            f"Harness {harness_name!r} has no harnessVersion in deployed state"
        )

    targets_path = project_root / "agentcore" / "aws-targets.json"
    targets = load_json(targets_path)
    if not isinstance(targets, list):
        raise ValueError(f"{targets_path} must contain an array")
    region = next(
        (
            item.get("region")
            for item in targets
            if isinstance(item, dict) and item.get("name") == target
        ),
        None,
    )
    if not isinstance(region, str) or not region:
        raise ValueError(f"Target {target!r} has no region in {targets_path}")
    return harness_id, str(version), region


def endpoint_payload(response: dict[str, Any]) -> dict[str, Any]:
    endpoint = response.get("endpoint")
    return endpoint if isinstance(endpoint, dict) else response


def require_ready_harness(client: Any, harness_id: str, version: str) -> None:
    response = client.get_harness(harnessId=harness_id, harnessVersion=version)
    harness = response.get("harness")
    if not isinstance(harness, dict):
        harness = response
    status = str(harness.get("status", "UNKNOWN"))
    live_version = str(harness.get("harnessVersion", version))
    if status != "READY":
        raise RuntimeError(
            f"Harness {harness_id} version {live_version} is not READY: {status}"
        )
    print(f"Harness {harness_id} version {live_version}: READY")


def get_endpoint(
    client: Any, harness_id: str, endpoint_name: str
) -> dict[str, Any] | None:
    try:
        return endpoint_payload(
            client.get_harness_endpoint(
                harnessId=harness_id,
                endpointName=endpoint_name,
            )
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return None
        raise


def wait_ready(
    client: Any,
    *,
    harness_id: str,
    endpoint_name: str,
    target_version: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        endpoint = get_endpoint(client, harness_id, endpoint_name)
        if endpoint is None:
            time.sleep(poll_seconds)
            continue
        status = str(endpoint.get("status", "UNKNOWN"))
        live_version = str(endpoint.get("liveVersion", ""))
        print(
            f"Endpoint {endpoint_name}: status={status}, liveVersion={live_version or '-'}"
        )
        if status == "READY" and live_version == target_version:
            return endpoint
        if status in {"FAILED", "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"}:
            raise RuntimeError(f"Endpoint entered terminal status {status}: {endpoint}")
        time.sleep(poll_seconds)
    raise TimeoutError(
        f"Timed out waiting for {endpoint_name} to serve Harness version {target_version}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--target", default="default")
    parser.add_argument("--harness-name")
    parser.add_argument("--endpoint-name", default="PROD")
    parser.add_argument("--region", help="Override the region in aws-targets.json")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        harness_id, target_version, configured_region = project_values(
            Path(args.project_root).expanduser().resolve(),
            target=args.target,
            harness_name=args.harness_name,
        )
        region = args.region or configured_region
        client = boto3.client("bedrock-agentcore-control", region_name=region)
        require_ready_harness(client, harness_id, target_version)
        current = get_endpoint(client, harness_id, args.endpoint_name)

        if (
            current is not None
            and current.get("status") == "READY"
            and str(current.get("liveVersion", "")) == target_version
        ):
            print(
                f"Endpoint {args.endpoint_name} is already READY on version {target_version}"
            )
            return 0

        if current is None:
            print(
                f"Creating endpoint {args.endpoint_name} for Harness {harness_id} "
                f"at version {target_version}"
            )
            client.create_harness_endpoint(
                harnessId=harness_id,
                endpointName=args.endpoint_name,
                targetVersion=target_version,
                description="Stable endpoint for the Slack channel adapter",
            )
        else:
            print(
                f"Updating endpoint {args.endpoint_name} for Harness {harness_id} "
                f"to version {target_version}"
            )
            client.update_harness_endpoint(
                harnessId=harness_id,
                endpointName=args.endpoint_name,
                targetVersion=target_version,
            )

        endpoint = wait_ready(
            client,
            harness_id=harness_id,
            endpoint_name=args.endpoint_name,
            target_version=target_version,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        print(
            f"READY: {args.endpoint_name} serves Harness version "
            f"{endpoint.get('liveVersion')} in {region}"
        )
        return 0
    except (ClientError, TimeoutError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
