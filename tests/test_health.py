"""Tests for the health check HTTP endpoint."""

from __future__ import annotations

import json
import urllib.request

import pytest

from platform_agent.health import start_health_server


@pytest.fixture
def health_server():
    """Start a health server on an ephemeral port and tear it down after test."""
    server = start_health_server(port=0, daemon=True)
    yield server
    server.shutdown()


def _get(server, path: str) -> tuple[int, dict]:
    """Helper to make a GET request to the test server."""
    host, port = server.server_address
    url = f"http://127.0.0.1:{port}{path}"
    try:
        resp = urllib.request.urlopen(url)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health_returns_200(health_server) -> None:
    status, body = _get(health_server, "/health")
    assert status == 200
    assert body["status"] == "healthy"
    assert body["service"] == "platform-agent"
    assert "timestamp" in body


def test_health_returns_json_content_type(health_server) -> None:
    host, port = health_server.server_address
    url = f"http://127.0.0.1:{port}/health"
    resp = urllib.request.urlopen(url)
    assert "application/json" in resp.headers.get("Content-Type", "")


def test_unknown_path_returns_404(health_server) -> None:
    status, body = _get(health_server, "/unknown")
    assert status == 404
    assert body["error"] == "not found"
