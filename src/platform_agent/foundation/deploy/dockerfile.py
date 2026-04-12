"""Dockerfile generation for AgentCore deployment."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DockerfileConfig:
    """Configuration for Dockerfile generation.

    Args:
        base_image: Base Docker image. Default: python:3.11-slim.
        include_claude_code: Whether to install Claude Code CLI.
        port: Port to expose. Default: 8080.
        extra_packages: Additional pip packages to install.
    """

    base_image: str = "python:3.11-slim"
    include_claude_code: bool = False
    port: int = 8080
    extra_packages: list[str] = field(default_factory=list)


def generate_dockerfile(config: DockerfileConfig | None = None) -> str:
    """Generate a Dockerfile for AgentCore deployment.

    Args:
        config: Dockerfile configuration. Uses defaults if None.

    Returns:
        Dockerfile content as string.
    """
    if config is None:
        config = DockerfileConfig()

    lines = [
        f"FROM {config.base_image}",
        "",
        "WORKDIR /app",
        "",
        "# Install system dependencies",
        "RUN apt-get update && apt-get install -y --no-install-recommends \\",
        "    git curl && \\",
        "    rm -rf /var/lib/apt/lists/*",
        "",
    ]

    if config.include_claude_code:
        lines.extend([
            "# Install Node.js (required for Claude Code CLI)",
            "RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \\",
            "    apt-get install -y nodejs && \\",
            "    rm -rf /var/lib/apt/lists/*",
            "",
            "# Install Claude Code CLI (pinned version for reproducibility)",
            "RUN npm install -g @anthropic-ai/claude-code@latest",
            "",
        ])

    lines.extend([
        "# Install Python dependencies",
        "COPY requirements.txt .",
        "RUN pip install --no-cache-dir -r requirements.txt",
        "",
        "# Install strands-agents",
        "RUN pip install --no-cache-dir strands-agents strands-agents-tools",
        "",
    ])

    if config.extra_packages:
        pkgs = " ".join(config.extra_packages)
        lines.extend([
            f"RUN pip install --no-cache-dir {pkgs}",
            "",
        ])

    lines.extend([
        "# Copy application code",
        "COPY . .",
        "",
        f"EXPOSE {config.port}",
        "",
        'ENTRYPOINT ["python", "entrypoint.py"]',
    ])

    return "\n".join(lines)
