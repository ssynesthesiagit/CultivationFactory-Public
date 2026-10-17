"""Keep asyncio cross-thread wakeups working inside sandboxes that refuse send().

Used by tests/conftest.py, which installs the policy once per pytest session, and by
tests/test_asyncio_wakeup.py, which tests it. Test support only; the app never imports it.

Starlette's TestClient runs the app's event loop in a portal thread and passes every
startup, request and shutdown to it with ``loop.call_soon_threadsafe()``. That call
wakes the loop by writing one byte to the loop's internal socketpair with
``socket.send()``. The Codex ``workspace-write`` sandbox's seccomp filter refuses the
sendto(2) syscall behind ``send()`` with EPERM. asyncio deliberately swallows OSError
there, so the wakeup is lost: a loop parked in select() with no timer never runs the
request, and every TestClient hangs, even for a three-route app (SOL37, 2026-10-01,
tests/test_final_character_workflow_api.py). The same sandbox allows write(2) on that
socket, so this loop writes the wakeup byte with ``os.write()`` instead.

``install_if_needed()`` changes nothing unless a probe shows ``send()`` is refused, so
ordinary runs keep the stock event loop.
"""
from __future__ import annotations

import asyncio
import os
import socket


def socket_send_refused() -> bool:
    """True when this process may not send() on a local socketpair (seccomp EPERM)."""
    left, right = socket.socketpair()
    try:
        left.send(b"\0")
    except PermissionError:
        return True
    finally:
        left.close()
        right.close()
    return False


class WriteWakeupEventLoop(asyncio.SelectorEventLoop):
    """Stock selector loop whose cross-thread wakeup uses write(2), not sendto(2).

    Overrides CPython's private ``_write_to_self`` (3.11/3.12 selector_events); the
    behaviour otherwise matches the stock method, including ignoring a closed socket
    or a full buffer (a wakeup byte is already pending then).
    """

    def _write_to_self(self) -> None:
        csock = self._csock
        if csock is None:
            return
        try:
            os.write(csock.fileno(), b"\0")
        except OSError:
            pass


class WriteWakeupEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        return WriteWakeupEventLoop()


def install_if_needed() -> bool:
    """Install the write(2) wakeup policy when send() is refused; return whether it did."""
    if not socket_send_refused():
        return False
    asyncio.set_event_loop_policy(WriteWakeupEventLoopPolicy())
    return True
