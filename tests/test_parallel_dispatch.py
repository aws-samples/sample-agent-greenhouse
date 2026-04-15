"""Tests for ParallelDispatcher — async sub-agent concurrency."""

from __future__ import annotations

import asyncio
import time

import pytest

from platform_agent.foundation.parallel_dispatch import (
    ParallelDispatcher,
    _default_executor,
    _run_task,
)


class TestParallelDispatchSingleTask:
    """Test dispatching a single task."""

    @pytest.mark.asyncio
    async def test_single_task_returns_result(self):
        dispatcher = ParallelDispatcher()
        results = await dispatcher.dispatch_parallel(
            [{"name": "task-1", "prompt": "hello"}],
        )
        assert len(results) == 1
        assert results[0]["name"] == "task-1"
        assert results[0]["success"] is True
        assert results[0]["output"] == "completed: hello"
        assert "duration_seconds" in results[0]

    @pytest.mark.asyncio
    async def test_empty_task_list_returns_empty(self):
        dispatcher = ParallelDispatcher()
        results = await dispatcher.dispatch_parallel([])
        assert results == []


class TestParallelDispatchMultipleTasks:
    """Test multiple tasks run concurrently and all complete."""

    @pytest.mark.asyncio
    async def test_multiple_tasks_all_complete(self):
        dispatcher = ParallelDispatcher()
        tasks = [
            {"name": f"task-{i}", "prompt": f"prompt-{i}"}
            for i in range(5)
        ]
        results = await dispatcher.dispatch_parallel(tasks, max_concurrency=3)
        assert len(results) == 5
        names = {r["name"] for r in results}
        assert names == {"task-0", "task-1", "task-2", "task-3", "task-4"}
        assert all(r["success"] for r in results)

    @pytest.mark.asyncio
    async def test_tasks_run_concurrently(self):
        """Verify that tasks actually run in parallel, not sequentially."""

        async def slow_executor(task):
            await asyncio.sleep(0.1)
            return await _default_executor(task)

        dispatcher = ParallelDispatcher(executor=slow_executor)
        tasks = [
            {"name": f"task-{i}", "prompt": f"p-{i}"}
            for i in range(5)
        ]
        start = time.monotonic()
        results = await dispatcher.dispatch_parallel(tasks, max_concurrency=5)
        elapsed = time.monotonic() - start

        assert len(results) == 5
        assert all(r["success"] for r in results)
        # If sequential, would take ~0.5s. Parallel should be ~0.1s.
        assert elapsed < 0.4

    @pytest.mark.asyncio
    async def test_custom_executor_via_di(self):
        """Verify that a custom executor injected via __init__ is used."""

        async def custom_executor(task):
            return f"custom: {task.get('prompt', '')}"

        dispatcher = ParallelDispatcher(executor=custom_executor)
        results = await dispatcher.dispatch_parallel(
            [{"name": "di-test", "prompt": "hello"}],
        )
        assert results[0]["output"] == "custom: hello"

    @pytest.mark.asyncio
    async def test_sync_executor_via_di(self):
        """Verify that a sync (non-async) executor also works."""

        def sync_executor(task):
            return f"sync: {task.get('prompt', '')}"

        dispatcher = ParallelDispatcher(executor=sync_executor)
        results = await dispatcher.dispatch_parallel(
            [{"name": "sync-di", "prompt": "world"}],
        )
        assert results[0]["output"] == "sync: world"


class TestMaxConcurrency:
    """Test that max_concurrency is respected."""

    @pytest.mark.asyncio
    async def test_concurrency_limited(self):
        """Verify semaphore limits concurrent execution."""
        concurrent_count = 0
        max_observed = 0
        lock = asyncio.Lock()

        async def tracking_executor(task):
            nonlocal concurrent_count, max_observed
            async with lock:
                concurrent_count += 1
                if concurrent_count > max_observed:
                    max_observed = concurrent_count
            await asyncio.sleep(0.05)
            async with lock:
                concurrent_count -= 1
            return await _default_executor(task)

        dispatcher = ParallelDispatcher(executor=tracking_executor)
        tasks = [
            {"name": f"task-{i}", "prompt": f"p-{i}"}
            for i in range(6)
        ]
        results = await dispatcher.dispatch_parallel(tasks, max_concurrency=2)

        assert len(results) == 6
        assert all(r["success"] for r in results)
        assert max_observed <= 2


class TestTaskFailure:
    """Test that individual task failure doesn't crash the batch."""

    @pytest.mark.asyncio
    async def test_failing_task_captured(self):

        async def failing_executor(task):
            if task.get("name") == "bad-task":
                raise ValueError("Something went wrong")
            return await _default_executor(task)

        dispatcher = ParallelDispatcher(executor=failing_executor)
        tasks = [
            {"name": "good-task", "prompt": "ok"},
            {"name": "bad-task", "prompt": "fail"},
            {"name": "another-good", "prompt": "ok2"},
        ]
        results = await dispatcher.dispatch_parallel(tasks)

        by_name = {r["name"]: r for r in results}
        assert by_name["good-task"]["success"] is True
        assert by_name["another-good"]["success"] is True
        assert by_name["bad-task"]["success"] is False
        assert "Something went wrong" in by_name["bad-task"]["error"]


class TestTimeoutHandling:
    """Test that task timeout is properly handled."""

    @pytest.mark.asyncio
    async def test_timeout_marks_task_failed(self):

        async def slow_executor(task):
            if task.get("name") == "slow-task":
                await asyncio.sleep(10)
            return await _default_executor(task)

        dispatcher = ParallelDispatcher(executor=slow_executor)
        tasks = [
            {"name": "fast-task", "prompt": "quick", "timeout_seconds": 5},
            {"name": "slow-task", "prompt": "slow", "timeout_seconds": 0.2},
        ]
        results = await dispatcher.dispatch_parallel(tasks)

        by_name = {r["name"]: r for r in results}
        assert by_name["fast-task"]["success"] is True
        assert by_name["slow-task"]["success"] is False
        assert "timed out" in by_name["slow-task"]["error"]


class TestSyncWrapper:
    """Test the sync wrapper for non-async callers."""

    def test_sync_wrapper_works(self):
        dispatcher = ParallelDispatcher()
        results = dispatcher.dispatch_parallel_sync(
            [{"name": "sync-test", "prompt": "hi"}],
        )
        assert len(results) == 1
        assert results[0]["name"] == "sync-test"
        assert results[0]["success"] is True
        assert results[0]["output"] == "completed: hi"

    def test_sync_wrapper_multiple_tasks(self):
        dispatcher = ParallelDispatcher()
        tasks = [
            {"name": f"t-{i}", "prompt": f"p-{i}"}
            for i in range(3)
        ]
        results = dispatcher.dispatch_parallel_sync(tasks, max_concurrency=2)
        assert len(results) == 3
        assert all(r["success"] for r in results)
