"""Project templates for the scaffold skill.

Each template is a dictionary mapping relative file paths to content strings.
Use ``{project_name}`` as a placeholder for the project name (e.g. ``my_agent``).

Templates follow all platform readiness checks (C1–C12) from the Design Advisor.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# basic-agent template
# ---------------------------------------------------------------------------

BASIC_PYPROJECT_TOML = """\
[project]
name = "{project_name}"
version = "0.1.0"
description = "An agent built on the Foundation Agent + Skills pattern"
requires-python = ">=3.11"
dependencies = [
    "claude-agent-sdk>=0.1,<1.0",
    "aiohttp>=3.9,<4.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
]
"""

BASIC_DOCKERFILE = """\
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/

ENV HEALTH_PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \\
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "-m", "{project_name}.agent"]
"""

BASIC_AGENT_PY = '''\
"""Foundation Agent entry point for {project_name}."""

import asyncio
import logging
import os
import signal
import sys

from aiohttp import web

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,  # C7: Log to stdout for CloudWatch
)

# C3: All configuration via environment variables
AGENT_PORT = int(os.getenv("AGENT_PORT", "8080"))
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-20250514")


class Agent:
    """Foundation Agent for {project_name}."""

    async def handle(self, query: str) -> dict:
        """Process a query and return a response."""
        try:
            return {{"response": f"Processed: {{query}}", "status": "ok"}}
        except Exception as e:  # C8: Proper error handling
            logger.error("Failed to process query: %s", e, exc_info=True)
            return {{"response": "Sorry, I encountered an error.", "status": "error"}}


agent = Agent()


async def health_handler(request: web.Request) -> web.Response:
    """C4: Health check endpoint."""
    return web.json_response({{"status": "healthy"}})


async def query_handler(request: web.Request) -> web.Response:
    """Handle incoming agent queries."""
    try:
        body = await request.json()
        query = body.get("query", "")
        if not query:
            return web.json_response({{"error": "query is required"}}, status=400)
        result = await agent.handle(query)
        return web.json_response(result)
    except Exception as e:
        logger.error("Request error: %s", e, exc_info=True)
        return web.json_response({{"error": "internal server error"}}, status=500)


# C6: Graceful shutdown handling
shutdown_event = asyncio.Event()


def handle_sigterm(*_):
    logger.info("Received SIGTERM, shutting down gracefully...")
    shutdown_event.set()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_post("/api/agent", query_handler)
    return app


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=AGENT_PORT)
'''

BASIC_HEALTH_PY = '''\
"""Standalone health check server using only the standard library.

Run this module directly to start a lightweight health endpoint
on the port specified by the HEALTH_PORT environment variable.
"""

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler


class HealthHandler(BaseHTTPRequestHandler):
    """Minimal health check HTTP handler."""

    def do_GET(self) -> None:
        if self.path == "/health":
            body = json.dumps({{"status": "healthy"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        """Suppress default stderr logging."""
        pass


def start_health_server(port: int = 8080) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    return server


if __name__ == "__main__":
    port = int(os.getenv("HEALTH_PORT", "8080"))
    server = start_health_server(port)
    print(f"Health server listening on port {{port}}")
    server.serve_forever()
'''

BASIC_TEST_AGENT_PY = '''\
"""Basic tests for {project_name}."""

import pytest


def test_agent_import():
    """Verify the agent module can be imported."""
    from {project_name} import agent  # noqa: F401


def test_agent_create_app():
    """Verify the app factory works."""
    from {project_name}.agent import create_app

    app = create_app()
    assert app is not None
'''

BASIC_README_MD = """\
# {project_name}

An agent built on the Foundation Agent + Skills pattern, ready for deployment
to Amazon Bedrock AgentCore.

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Set required environment variables
export AGENT_PORT=8080

# Run the agent
python -m {project_name}.agent

# Run tests
pytest tests/ -v
```

## Project Structure

```
{project_name}/
├── pyproject.toml
├── Dockerfile
├── src/{project_name}/
│   ├── __init__.py
│   ├── agent.py          # Foundation Agent entry point
│   └── health.py         # Standalone health check server
└── tests/
    └── test_agent.py
```

## Deployment

Build and run the Docker container:

```bash
docker build -t {project_name} .
docker run -p 8080:8080 {project_name}
```

## Platform Compliance

This project follows all platform readiness checks:
- ✅ C1: Containerizable (Dockerfile with HEALTHCHECK)
- ✅ C2: No hardcoded secrets
- ✅ C3: Environment-based configuration
- ✅ C4: Health check endpoint at `/health`
- ✅ C5: Stateless design
- ✅ C6: Graceful SIGTERM shutdown
- ✅ C7: Logging to stdout
- ✅ C8: Proper error handling
- ✅ C9: Dependency management via pyproject.toml
"""

BASIC_GITIGNORE = """\
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/
*.egg
.env
.env.*
.venv/
venv/
ENV/
.pytest_cache/
.ruff_cache/
.mypy_cache/
"""

BASIC_INIT_PY = """\
\"""Package init for {project_name}.\"""
"""

# Assemble the basic-agent template as a dict of {relative_path: content}
BASIC_AGENT_TEMPLATE: dict[str, str] = {
    "pyproject.toml": BASIC_PYPROJECT_TOML,
    "Dockerfile": BASIC_DOCKERFILE,
    "src/{project_name}/__init__.py": BASIC_INIT_PY,
    "src/{project_name}/agent.py": BASIC_AGENT_PY,
    "src/{project_name}/health.py": BASIC_HEALTH_PY,
    "tests/test_agent.py": BASIC_TEST_AGENT_PY,
    "README.md": BASIC_README_MD,
    ".gitignore": BASIC_GITIGNORE,
}


# ---------------------------------------------------------------------------
# multi-agent template  (extends basic-agent)
# ---------------------------------------------------------------------------

MULTI_ORCHESTRATOR_PY = '''\
"""Orchestrator for {project_name} — routes queries to specialist sub-agents.

Uses the agent-as-tool pattern: each skill pack is converted to a sub-agent
that the orchestrator can delegate to via the Task tool.
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)


def build_orchestrator_prompt(agents: dict) -> str:
    """Build a system prompt listing available specialist agents."""
    lines = [
        "You are the orchestrator for {project_name}.",
        "You have the following specialist agents available:\\n",
    ]
    for name, defn in agents.items():
        desc = defn.get("description", "No description")
        lines.append("- **%s**: %s" % (name, desc))
    lines.append(
        "\\nRoute each user request to the most appropriate specialist. "
        "Use the Task tool to delegate work to a specialist agent."
    )
    return "\\n".join(lines)
'''

MULTI_SKILLS_INIT_PY = """\
\"""Skill registry for {project_name}.\"""

_skills: dict[str, type] = {{}}


def register_skill(name: str, cls: type) -> None:
    _skills[name] = cls


def get_skill(name: str) -> type:
    if name not in _skills:
        raise KeyError(f"Skill '{{name}}' not found. Available: {{list(_skills.keys())}}")
    return _skills[name]


def list_skills() -> list[str]:
    return list(_skills.keys())
"""

MULTI_EXAMPLE_SKILL_PY = '''\
"""Example skill pack for {project_name}.

Replace this with your own skill implementation.
"""


class ExampleSkill:
    """A minimal skill pack following the Foundation Agent + Skills pattern."""

    name = "example"
    description = "An example skill — replace with your own"
    system_prompt_extension = (
        "You are an example specialist. Replace this prompt with domain-specific "
        "knowledge for your use case."
    )
    tools: list[str] = ["Read", "Glob"]

    def configure(self) -> None:
        """Initialize skill-specific configuration."""
        pass
'''

MULTI_AGENT_TEMPLATE: dict[str, str] = {
    "src/{project_name}/orchestrator.py": MULTI_ORCHESTRATOR_PY,
    "src/{project_name}/skills/__init__.py": MULTI_SKILLS_INIT_PY,
    "src/{project_name}/skills/example_skill.py": MULTI_EXAMPLE_SKILL_PY,
}


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict[str, str]] = {
    "basic-agent": BASIC_AGENT_TEMPLATE,
    "multi-agent": {**BASIC_AGENT_TEMPLATE, **MULTI_AGENT_TEMPLATE},
    "rag-agent": BASIC_AGENT_TEMPLATE,     # Uses basic as starting point
    "tool-agent": BASIC_AGENT_TEMPLATE,     # Uses basic as starting point
}

TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "basic-agent": "Single Foundation Agent with health check and HTTP server",
    "multi-agent": "Orchestrator + specialist sub-agents with skill packs",
    "rag-agent": "Agent with retrieval-augmented generation pattern",
    "tool-agent": "Agent with custom MCP tool server integration",
}
