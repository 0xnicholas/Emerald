"""Utilities for running async code inside sync contexts (e.g. Celery tasks)."""

from __future__ import annotations

import asyncio
from functools import wraps


def run_async(coro_func):
    """Decorator that runs an async function inside a fresh event loop.

    Usage in Celery tasks:
        @app.task
        def my_task(...):
            return _run_helper(...)

        @run_async
        async def _run_helper(...):
            ...
    """
    @wraps(coro_func)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_func(*args, **kwargs))
    return wrapper
