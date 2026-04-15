"""Parallel Dispatch — async sub-agent concurrency for the Generator stage.

Allows the Foundation Agent's Generator stage to dispatch multiple sub-tasks
concurrently with controlled concurrency, timeout handling, and context
isolation per task.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Type alias for the task executor callable.
TaskExecutor = Callable[[dict[str, Any]], Any]

# Default timeout per task in seconds.
_DEFAULT_TIMEOUT_SECONDS = 120


async def _default_executor(task: dict[str, Any]) -> Any:
    """Default task executor that echoes the prompt.

    Useful for testing the dispatch machinery without a real sub-agent backend.

    Args:
        task: Task dict with keys: name, prompt, tools (optional).

    Returns:
        A string echoing the prompt.
    """
    prompt = task.get("prompt", "")
    return f"completed: {prompt}"


async def _run_task(
    task: dict[str, Any],
    semaphore: asyncio.Semaphore,
    executor: TaskExecutor,
) -> dict[str, Any]:
    """Execute a single task with semaphore-based concurrency control.

    Each task runs within its own isolated context (separate message history).
    Failures are captured per-task and do not propagate to the batch.

    Args:
        task: Task dict with keys: name, prompt, tools (optional),
            timeout_seconds (optional).
        semaphore: Concurrency-limiting semaphore.

    Returns:
        Result dict with keys: name, output, success, error (optional),
        duration_seconds.
    """
    name = task.get("name", "unnamed")
    prompt = task.get("prompt", "")
    timeout = task.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)

    start = time.monotonic()
    async with semaphore:
        try:
            result = executor(task)
            # Support both sync and async executors.
            if asyncio.iscoroutine(result):
                output = await asyncio.wait_for(result, timeout=timeout)
            else:
                output = result
            duration = time.monotonic() - start
            return {
                "name": name,
                "output": output,
                "success": True,
                "duration_seconds": round(duration, 3),
            }
        except asyncio.TimeoutError:
            duration = time.monotonic() - start
            logger.warning("Task %r timed out after %.1fs", name, duration)
            return {
                "name": name,
                "output": None,
                "success": False,
                "error": f"Task timed out after {timeout}s",
                "duration_seconds": round(duration, 3),
            }
        except Exception as exc:
            duration = time.monotonic() - start
            logger.warning("Task %r failed: %s", name, exc)
            return {
                "name": name,
                "output": None,
                "success": False,
                "error": str(exc),
                "duration_seconds": round(duration, 3),
            }


class ParallelDispatcher:
    """Dispatches multiple sub-tasks concurrently with controlled concurrency.

    Args:
        executor: An async or sync callable that takes a task dict and returns
            the task output. Defaults to an echo executor useful for testing.

    Usage::

        async def my_executor(task: dict) -> str:
            return await invoke_sub_agent(task["prompt"])

        dispatcher = ParallelDispatcher(executor=my_executor)
        results = await dispatcher.dispatch_parallel([
            {"name": "task-a", "prompt": "Summarize X"},
            {"name": "task-b", "prompt": "Generate Y", "timeout_seconds": 60},
        ], max_concurrency=3)
    """

    def __init__(self, executor: TaskExecutor | None = None) -> None:
        self._executor = executor or _default_executor

    async def dispatch_parallel(
        self,
        tasks: list[dict[str, Any]],
        max_concurrency: int = 3,
    ) -> list[dict[str, Any]]:
        """Run tasks concurrently with a semaphore for max_concurrency.

        Args:
            tasks: List of task dicts. Each has: name, prompt,
                tools (optional), timeout_seconds (optional, default 120).
            max_concurrency: Maximum number of tasks running at once.

        Returns:
            List of result dicts: name, output, success (bool),
            error (optional), duration_seconds.
        """
        if not tasks:
            return []

        semaphore = asyncio.Semaphore(max_concurrency)
        coroutines = [
            _run_task(task, semaphore, self._executor) for task in tasks
        ]
        results = await asyncio.gather(*coroutines, return_exceptions=False)
        return list(results)

    def dispatch_parallel_sync(
        self,
        tasks: list[dict[str, Any]],
        max_concurrency: int = 3,
    ) -> list[dict[str, Any]]:
        """Sync wrapper that runs dispatch_parallel in an event loop.

        For callers that aren't in an async context.

        Args:
            tasks: List of task dicts (same format as dispatch_parallel).
            max_concurrency: Maximum number of tasks running at once.

        Returns:
            List of result dicts (same format as dispatch_parallel).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already inside an event loop — create a new one in a thread.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.dispatch_parallel(tasks, max_concurrency),
                )
                return future.result()

        return asyncio.run(self.dispatch_parallel(tasks, max_concurrency))
