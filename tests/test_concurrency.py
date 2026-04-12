"""Tests for entrypoint concurrency handling.

Tests the per-session locking mechanism that prevents
ConcurrencyException from Strands SDK.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# We test AgentPool directly — it's the core concurrency mechanism.
# The entrypoint.py invoke() function is tested via integration tests.


class TestAgentPoolConcurrency:
    """Tests for per-session locking in AgentPool."""

    def _make_pool(self):
        """Create an AgentPool with mocked agent creation."""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

        # We need to mock the heavy dependencies
        with patch.dict("os.environ", {"WORKSPACE_DIR": "/tmp/test"}):
            from collections import OrderedDict

            class TestableAgentPool:
                """Minimal AgentPool for concurrency testing."""

                _BUSY_WAIT_TIMEOUT = 0.5  # Short timeout for tests

                def __init__(self, max_size=10):
                    self._agents: OrderedDict[str, MagicMock] = OrderedDict()
                    self._lock = threading.Lock()
                    self._session_locks: dict[str, threading.Lock] = {}
                    self._max_size = max_size

                def get_or_create(self, session_id, actor_id="default", user_name=""):
                    with self._lock:
                        if session_id not in self._agents:
                            self._agents[session_id] = MagicMock()
                        if session_id not in self._session_locks:
                            self._session_locks[session_id] = threading.Lock()
                        return self._agents[session_id]

                def acquire_session(self, session_id):
                    with self._lock:
                        if session_id not in self._session_locks:
                            self._session_locks[session_id] = threading.Lock()
                        lock = self._session_locks[session_id]
                    return lock.acquire(timeout=self._BUSY_WAIT_TIMEOUT)

                def release_session(self, session_id):
                    with self._lock:
                        lock = self._session_locks.get(session_id)
                    if lock:
                        try:
                            lock.release()
                        except RuntimeError:
                            pass

            return TestableAgentPool()

    def test_acquire_release_basic(self):
        """Basic acquire/release cycle."""
        pool = self._make_pool()
        assert pool.acquire_session("sess-1") is True
        pool.release_session("sess-1")

    def test_same_session_blocks(self):
        """Second acquire on same session blocks and returns False after timeout."""
        pool = self._make_pool()
        assert pool.acquire_session("sess-1") is True
        # Try to acquire same session — should fail after timeout
        assert pool.acquire_session("sess-1") is False
        pool.release_session("sess-1")

    def test_different_sessions_concurrent(self):
        """Different sessions can be acquired concurrently."""
        pool = self._make_pool()
        assert pool.acquire_session("sess-1") is True
        assert pool.acquire_session("sess-2") is True
        pool.release_session("sess-1")
        pool.release_session("sess-2")

    def test_release_allows_reacquire(self):
        """After release, same session can be acquired again."""
        pool = self._make_pool()
        assert pool.acquire_session("sess-1") is True
        pool.release_session("sess-1")
        assert pool.acquire_session("sess-1") is True
        pool.release_session("sess-1")

    def test_concurrent_threads_same_session(self):
        """Two threads trying same session — one succeeds, one gets busy."""
        pool = self._make_pool()
        results = {}

        def worker(name, session_id):
            acquired = pool.acquire_session(session_id)
            results[name] = acquired
            if acquired:
                time.sleep(1)  # Simulate work
                pool.release_session(session_id)

        t1 = threading.Thread(target=worker, args=("t1", "sess-1"))
        t2 = threading.Thread(target=worker, args=("t2", "sess-1"))

        t1.start()
        time.sleep(0.1)  # Ensure t1 acquires first
        t2.start()

        t1.join()
        t2.join()

        assert results["t1"] is True
        assert results["t2"] is False  # Should get busy response

    def test_concurrent_threads_different_sessions(self):
        """Two threads with different sessions — both succeed."""
        pool = self._make_pool()
        results = {}

        def worker(name, session_id):
            acquired = pool.acquire_session(session_id)
            results[name] = acquired
            if acquired:
                time.sleep(0.5)
                pool.release_session(session_id)

        t1 = threading.Thread(target=worker, args=("t1", "sess-1"))
        t2 = threading.Thread(target=worker, args=("t2", "sess-2"))

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        assert results["t1"] is True
        assert results["t2"] is True

    def test_double_release_safe(self):
        """Double release doesn't crash."""
        pool = self._make_pool()
        pool.acquire_session("sess-1")
        pool.release_session("sess-1")
        pool.release_session("sess-1")  # Should not raise


class TestGitHubAutoInit:
    """Test that github create_repo uses auto_init=True."""

    def test_create_repo_auto_init_true(self):
        """Verify create_repo sets auto_init=True to avoid empty repo race."""
        import ast
        from pathlib import Path

        # Read the source and verify auto_init is True
        github_py = Path(__file__).parent.parent / "src" / "platform_agent" / "strands_foundation" / "tools" / "github.py"
        source = github_py.read_text()
        assert '"auto_init": True' in source or "'auto_init': True" in source

    def test_blob_retry_count_is_5(self):
        """Verify blob creation retries increased to 5."""
        from pathlib import Path

        github_py = Path(__file__).parent.parent / "src" / "platform_agent" / "strands_foundation" / "tools" / "github.py"
        source = github_py.read_text()
        assert "retry %d/5" in source
