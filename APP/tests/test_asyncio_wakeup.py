"""TestClient must not hang where the sandbox refuses socket send() (tests/asyncio_wakeup.py).

The refusal is simulated by swapping the loop's wakeup socket for one whose send()
raises EPERM, exactly what the Codex workspace-write seccomp filter does. With the stock
SelectorEventLoop the wakeup is lost; the waits below are bounded so a regression fails
instead of hanging the run.
"""
from __future__ import annotations

import asyncio
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.asyncio_wakeup import WriteWakeupEventLoop, WriteWakeupEventLoopPolicy, socket_send_refused


class _SendRefusingSocket:
    """The loop's wakeup socket as the sandbox sees it: write(2) works, send() is EPERM."""

    def __init__(self, sock):
        self._sock = sock

    def send(self, _data):
        raise PermissionError(1, "Operation not permitted")

    def fileno(self):
        return self._sock.fileno()

    def close(self):
        self._sock.close()


def _sandboxed(loop: asyncio.AbstractEventLoop) -> asyncio.AbstractEventLoop:
    loop._csock = _SendRefusingSocket(loop._csock)
    return loop


class _SandboxedPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self):
        return _sandboxed(WriteWakeupEventLoop())


def test_cross_thread_wakeup_reaches_a_parked_loop_when_send_is_refused():
    async def main():
        loop = asyncio.get_running_loop()
        woken = loop.create_future()

        def from_other_thread():
            time.sleep(0.3)  # let the loop park in select() with no timer of its own
            loop.call_soon_threadsafe(woken.set_result, "woken")

        threading.Thread(target=from_other_thread, daemon=True).start()
        # The 10 s timer only bounds a failure; a working wakeup returns in ~0.3 s.
        return await asyncio.wait_for(woken, 10)

    loop = _sandboxed(WriteWakeupEventLoop())
    try:
        started = time.monotonic()
        assert loop.run_until_complete(main()) == "woken"
        assert time.monotonic() - started < 5
    finally:
        loop.close()


def test_testclient_startup_requests_and_shutdown_complete_when_send_is_refused():
    app = FastAPI()
    seen = []

    @app.on_event("startup")
    def startup():
        seen.append("startup")

    @app.on_event("shutdown")
    def shutdown():
        seen.append("shutdown")

    @app.get("/sync")
    def sync_route():
        return {"route": "sync"}

    @app.get("/async")
    async def async_route():
        return {"route": "async"}

    results = []

    def drive():
        with TestClient(app) as client:
            results.append(client.get("/sync").json())
            results.append(client.get("/async").json())

    previous = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(_SandboxedPolicy())
    try:
        worker = threading.Thread(target=drive, daemon=True)
        worker.start()
        worker.join(60)  # bounds a regression; passing runs take well under a second
        assert not worker.is_alive(), "TestClient hung: the cross-thread wakeup was lost"
    finally:
        asyncio.set_event_loop_policy(previous)
    assert results == [{"route": "sync"}, {"route": "async"}]
    assert seen == ["startup", "shutdown"]


def test_conftest_installs_the_policy_exactly_when_send_is_refused():
    installed = isinstance(asyncio.get_event_loop_policy(), WriteWakeupEventLoopPolicy)
    assert installed == socket_send_refused()
