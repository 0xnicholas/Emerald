# ruff: noqa: UP047
"""Utilities for running async code inside sync contexts (e.g. Celery tasks)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def run_async(
    coro_func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, R]:
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
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return asyncio.run(coro_func(*args, **kwargs))
    return wrapper
