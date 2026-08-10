"""Distributed lock — prevents duplicate execution of Celery Beat tasks.

When Celery Beat runs in multiple instances (misconfiguration, K8s pod
duplication), the same scheduled task can fire concurrently.  This module
provides a Redis-based lock so only one instance processes each scheduled
invocation.

Usage::

    from emerald.core.lock import beat_lock

    @shared_task
    @beat_lock(ttl_seconds=600)
    def my_scheduled_task():
        ...

Protocol: ``SET lock-key instance-id NX EX ttl`` with automatic release.
"""

from __future__ import annotations

import asyncio
import os
import socket
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, Callable

import redis.exceptions as redis_exceptions
import structlog

logger = structlog.get_logger(__name__)

# Unique per-process instance id so we only release our own locks
_instance_id = f"{socket.gethostname()}:{os.getpid()}"

# Default lock TTL (seconds) — long enough to finish typical tasks,
# short enough that a crashed worker won't block others forever.
DEFAULT_TTL_SECONDS = 600


class DistributedLock:
    """Async context manager for Redis-based distributed locks.

    Uses ``SET key value NX EX ttl`` — an atomic check-and-set operation.
    """

    def __init__(
        self,
        name: str,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        instance_id: str | None = None,
    ) -> None:
        self._name = f"emerald:lock:{name}"
        self._ttl = ttl_seconds
        self._instance_id = instance_id or _instance_id
        self._acquired = False

    @property
    def name(self) -> str:
        return self._name

    async def acquire(self) -> bool:
        """Try to acquire the lock.  Returns True on success."""
        try:
            from emerald.db.redis import ensure_redis_for_loop

            redis = await ensure_redis_for_loop()
        except (RuntimeError, OSError, redis_exceptions.ConnectionError):
            # Redis not available in this loop — fail open (let the task run)
            logger.debug("lock.redis_unavailable", lock=self._name)
            self._acquired = True
            return True

        try:
            # SET key value NX EX ttl → returns True if key was set
            result = await redis.set(
                self._name,
                self._instance_id,
                nx=True,
                ex=self._ttl,
            )
            self._acquired = bool(result)
            if self._acquired:
                logger.debug("lock.acquired", lock=self._name, instance=self._instance_id)
            else:
                logger.debug("lock.contention", lock=self._name, instance=self._instance_id)
            return self._acquired
        except Exception:
            # Redis error — fail open
            logger.warning("lock.acquire_error", lock=self._name, exc_info=True)
            self._acquired = True
            return True

    async def release(self) -> None:
        """Release the lock if we hold it."""
        if not self._acquired:
            return

        try:
            from emerald.db.redis import ensure_redis_for_loop

            redis = await ensure_redis_for_loop()
        except (RuntimeError, OSError, redis_exceptions.ConnectionError):
            self._acquired = False
            return

        try:
            # Only delete if we still hold the lock (value match).
            # Prefer atomic Lua script; fall back to check-then-delete
            # for environments where EVAL is not available (e.g. fakeredis).
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            try:
                await redis.eval(script, 1, self._name, self._instance_id)
            except Exception:
                # EVAL not supported — use non-atomic fallback
                current = await redis.get(self._name)
                if isinstance(current, bytes):
                    current = current.decode()
                if current == self._instance_id:
                    await redis.delete(self._name)
            logger.debug("lock.released", lock=self._name, instance=self._instance_id)
        except Exception:
            logger.warning("lock.release_error", lock=self._name, exc_info=True)
        finally:
            self._acquired = False

    async def __aenter__(self) -> "DistributedLock":
        await self.acquire()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.release()


def beat_lock(
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    name: str | None = None,
) -> Callable:
    """Decorator for Celery Beat tasks: acquire a distributed lock before running.

    If the lock cannot be acquired, the task invocation is silently skipped.
    This prevents concurrent execution when Beat runs in multiple instances.

    :param ttl_seconds: Lock auto-expiry time (prevents dead workers from
        holding the lock forever).
    :param name: Lock name override (default: ``task_{func_name}``).
    """

    def decorator(func: Callable) -> Callable:
        lock_name = name or f"task_{func.__name__}"

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            lock = DistributedLock(lock_name, ttl_seconds=ttl_seconds)

            async def _locked() -> Any:
                if not await lock.acquire():
                    logger.info(
                        "beat.skipped",
                        task=func.__name__,
                        reason="lock_contention",
                    )
                    return None
                try:
                    return func(*args, **kwargs)
                finally:
                    await lock.release()

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # In async context — create a task
                    import concurrent.futures

                    future = asyncio.run_coroutine_threadsafe(_locked(), loop)
                    return future.result(timeout=ttl_seconds)
                else:
                    return asyncio.run(_locked())
            except RuntimeError:
                return asyncio.run(_locked())

        return wrapper

    return decorator
