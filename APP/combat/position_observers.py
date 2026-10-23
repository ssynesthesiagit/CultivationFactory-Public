"""Context-local, before-assignment observation of live immutable positions.

This module has no engine or extension imports. An observer is transient and
does not become a Pydantic field, a global actor hook, or part of a saved fight.
The observer must bind the exact actor objects it owns; projected copies are
not execution. Exceptions prevent the assignment and propagate to its caller.
"""
from contextlib import contextmanager
from contextvars import ContextVar


_OBSERVER = ContextVar("combat_position_observer", default=None)


def current():
    return _OBSERVER.get()


@contextmanager
def observe(callback):
    token = _OBSERVER.set(callback)
    try:
        yield
    finally:
        _OBSERVER.reset(token)
