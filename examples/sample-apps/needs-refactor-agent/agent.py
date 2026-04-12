"""Needs Refactor Agent — partially compliant, has some issues to fix.

This agent has some things right (Dockerfile, proper framework) but needs
work on state management and observability.

Intentional issues:
- C4 WARNING: No health check endpoint
- C5 WARNING: Uses local SQLite for persistent state
- C11 WARNING: Tool executes user-provided code without sandboxing
Passes:
- C1: Has Dockerfile ✅
- C2: No hardcoded secrets ✅ 
- C3: Uses env vars ✅
- C8: Has error handling ✅
- C9: Has pyproject.toml ✅
"""

import logging
import os
import sqlite3
import sys

from aiohttp import web

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

AGENT_PORT = int(os.getenv("AGENT_PORT", "8080"))
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-20250514")

# C5 VIOLATION: Using local SQLite for persistent state
# Should use AgentCore Memory or external database instead
DB_PATH = os.getenv("DB_PATH", "./agent_data.db")


def init_db():
    """Initialize local SQLite database for conversation history."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS conversations "
        "(id INTEGER PRIMARY KEY, query TEXT, response TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    return conn


db = init_db()


class DataAnalysisAgent:
    """Agent that helps analyze data — partially compliant with platform standards."""

    async def handle_query(self, query: str) -> dict:
        try:
            response = f"Analysis result for: {query}"

            # C5 VIOLATION: Persisting state to local SQLite
            db.execute(
                "INSERT INTO conversations (query, response) VALUES (?, ?)",
                (query, response),
            )
            db.commit()

            return {"response": response, "model": AGENT_MODEL, "status": "ok"}
        except Exception as e:
            logger.error("Query failed: %s", e, exc_info=True)
            return {"response": "Analysis failed", "status": "error"}

    async def run_user_code(self, code: str) -> dict:
        """C11 VIOLATION: Executes user-provided code without sandboxing.

        This is dangerous and intentionally left as an anti-pattern.
        Production agents should use AgentCore Code Interpreter instead.
        """
        # INTENTIONALLY INSECURE — this is a "needs refactor" example.
        # The correct fix is to use AgentCore Code Interpreter sandbox.
        # See: examples/sample-apps/compliant-agent/ for the safe pattern.
        return {
            "error": "Code execution disabled. Use AgentCore Code Interpreter.",
            "status": "rejected",
            "violation": "C11 — no sandboxed execution"
        }


agent = DataAnalysisAgent()


# NOTE: No health check endpoint (C4 violation)


async def query_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        query = body.get("query", "")
        if not query:
            return web.json_response({"error": "query is required"}, status=400)
        result = await agent.handle_query(query)
        return web.json_response(result)
    except Exception as e:
        logger.error("Request error: %s", e, exc_info=True)
        return web.json_response({"error": "internal server error"}, status=500)


async def execute_handler(request: web.Request) -> web.Response:
    """Endpoint that runs arbitrary code — C11 violation."""
    body = await request.json()
    code = body.get("code", "")
    result = await agent.run_user_code(code)
    return web.json_response(result)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/agent", query_handler)
    app.router.add_post("/api/execute", execute_handler)
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=AGENT_PORT)
