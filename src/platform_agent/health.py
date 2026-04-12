"""Lightweight HTTP health check endpoint using stdlib only.

Run standalone:
    python -m platform_agent.health          # serves on :8080
    HEALTH_PORT=9090 python -m platform_agent.health  # custom port

Or start programmatically:
    from platform_agent.health import start_health_server
    server = start_health_server(port=8080)
    # ... later ...
    server.shutdown()
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class HealthHandler(BaseHTTPRequestHandler):
    """Responds to GET /health with 200 OK + JSON status."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            body: dict[str, Any] = {
                "status": "healthy",
                "service": "platform-agent",
                "timestamp": time.time(),
            }
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            body_404 = json.dumps({"error": "not found"}).encode()
            self.send_header("Content-Length", str(len(body_404)))
            self.end_headers()
            self.wfile.write(body_404)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr logging."""
        pass


def start_health_server(port: int = 8080, daemon: bool = True) -> HTTPServer:
    """Start the health check HTTP server in a background thread.

    Args:
        port: Port to listen on.
        daemon: Whether the server thread is a daemon thread.

    Returns:
        The HTTPServer instance (call .shutdown() to stop).
    """
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=daemon)
    thread.start()
    return server


if __name__ == "__main__":
    import os

    port = int(os.environ.get("HEALTH_PORT", "8080"))
    print(f"Health check server listening on :{port}")
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
