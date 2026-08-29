"""Tests for async utilities."""

import asyncio
import threading

from emerald.async_utils import run_async


def test_run_async_decorator():
    """run_async wraps an async function for sync contexts."""
    @run_async
    async def _hello():
        await asyncio.sleep(0)
        return "hello"

    # Run in a fresh thread to avoid nested event loop issues in pytest
    result = []
    def _run():
        result.append(_hello())
    t = threading.Thread(target=_run)
    t.start()
    t.join()
    assert result[0] == "hello"
