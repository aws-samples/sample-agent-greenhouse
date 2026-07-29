#!/usr/bin/env python3
"""Render the bundled Slack adapter template into an AgentCore project."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".toml",
    ".ts",
    ".yml",
    ".yaml",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError("App name must contain at least one letter or digit")
    if not slug[0].isalpha():
        slug = f"app-{slug}"
    return slug[:36].rstrip("-")


def identifier(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    result = "".join(word[:1].upper() + word[1:] for word in words)
    if not result:
        raise ValueError("App name must contain at least one letter or digit")
    if not result[0].isalpha():
        result = f"App{result}"
    return result[:48]


def render_tree(destination: Path, replacements: dict[str, str]) -> None:
    for path in destination.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        content = path.read_text()
        for marker, value in replacements.items():
            content = content.replace(marker, value)
        path.write_text(content)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy the AgentCore Harness Slack adapter into a customer project."
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="AgentCore project root (default: current directory)",
    )
    parser.add_argument("--app-name", required=True, help="Slack app display name")
    parser.add_argument(
        "--destination",
        default="slack-adapter",
        help="Directory relative to project root (default: slack-adapter)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= len(args.app_name) <= 35:
        print("error: --app-name must contain 1 to 35 characters", file=sys.stderr)
        return 2
    if any(ord(character) < 32 for character in args.app_name):
        print("error: --app-name cannot contain control characters", file=sys.stderr)
        return 2
    project_root = Path(args.project_root).expanduser().resolve()
    if not (project_root / "agentcore" / "agentcore.json").is_file():
        print(
            f"error: {project_root} does not contain agentcore/agentcore.json",
            file=sys.stderr,
        )
        return 2

    destination_arg = Path(args.destination)
    if destination_arg.is_absolute() or ".." in destination_arg.parts:
        print("error: --destination must stay inside --project-root", file=sys.stderr)
        return 2
    destination = project_root / destination_arg
    if destination.exists():
        print(f"error: refusing to overwrite existing {destination}", file=sys.stderr)
        return 2

    template = Path(__file__).resolve().parents[1] / "assets" / "slack-adapter-template"
    if not template.is_dir():
        print(f"error: bundled template is missing: {template}", file=sys.stderr)
        return 2

    app_slug = slugify(args.app_name)
    app_id = identifier(args.app_name)
    yaml_display_name = json.dumps(args.app_name, ensure_ascii=True)[1:-1]
    shutil.copytree(template, destination)
    render_tree(
        destination,
        {
            "__APP_DISPLAY_NAME__": yaml_display_name,
            "__APP_SLUG__": app_slug,
            "__APP_ID__": app_id,
        },
    )

    print(f"Created {destination}")
    print(f"  app display name: {args.app_name}")
    print(f"  AWS resource prefix: {app_slug}")
    print(f"  CDK stack id: {app_id}SlackAdapter")
    print()
    print("Next:")
    print(f"  cd {destination}")
    print("  python -m venv .venv")
    print("  .venv/bin/python -m pip install -r requirements-dev.txt")
    print("  .venv/bin/python -m pytest -q")
    print("  cd infra && npm install && npm run build && npm test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
