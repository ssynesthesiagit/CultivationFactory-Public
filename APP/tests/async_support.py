"""Run ASGI tests with the shared write-based sandbox wakeup implementation.

Used by API-choice and roster tests. Both worker completion and Runner shutdown
use the same cross-thread wakeup as TestClient; no polling timer is needed.
"""
import asyncio
from tests.asyncio_wakeup import WriteWakeupEventLoop


def run_asgi(coroutine):
    """Run actual ASGI transport with working worker-thread socket wakeups."""
    with asyncio.Runner(loop_factory=WriteWakeupEventLoop) as runner:
        return runner.run(coroutine)
