"""Good Weather Agent — a well-designed agent app that passes all platform checks.

This is an example of a properly structured agent application ready for
deployment to Amazon Bedrock AgentCore.
"""

import asyncio
import logging
import os
import signal
import sys
from contextlib import asynccontextmanager

from aiohttp import web

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,  # C7: Log to stdout for CloudWatch
)

# C3: All configuration via environment variables
AGENT_PORT = int(os.getenv("AGENT_PORT", "8080"))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")  # C2: No hardcoded secrets
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-20250514")


class WeatherAgent:
    """A simple weather assistant agent."""

    def __init__(self):
        if not WEATHER_API_KEY:
            raise EnvironmentError("WEATHER_API_KEY environment variable is required")

    async def handle_query(self, query: str) -> dict:
        """Process a weather query and return a response.

        Args:
            query: Natural language weather question.

        Returns:
            Dict with 'response' key containing the answer.
        """
        try:
            # In production, this would call the weather API and use the LLM
            # For demo purposes, return a structured response
            return {
                "response": f"Processing weather query: {query}",
                "model": AGENT_MODEL,
                "status": "ok",
            }
        except Exception as e:  # C8: Proper error handling
            logger.error("Failed to process query: %s", e, exc_info=True)
            return {"response": "Sorry, I encountered an error.", "status": "error"}


# --- HTTP Server ---

agent = WeatherAgent()


async def health_handler(request: web.Request) -> web.Response:
    """C4: Health check endpoint for AgentCore."""
    return web.json_response({"status": "healthy"})


async def query_handler(request: web.Request) -> web.Response:
    """Handle incoming agent queries."""
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


# C6: Graceful shutdown handling
shutdown_event = asyncio.Event()


def handle_sigterm(*_):
    logger.info("Received SIGTERM, shutting down gracefully...")
    shutdown_event.set()


@asynccontextmanager
async def lifespan(app: web.Application):
    signal.signal(signal.SIGTERM, handle_sigterm)
    logger.info("Weather Agent started on port %d", AGENT_PORT)
    yield
    logger.info("Weather Agent shutting down")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_post("/api/agent", query_handler)
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=AGENT_PORT)
