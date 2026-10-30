"""The named area kinds a rider can stand in, answered by the plug-in that owns the ground.

Some printed conditions are "while standing in *this named area*": your own Air Current, Sand
Terrain, or plain Ash / Fire / supernatural Darkness. Ash, Fire and Darkness are typed
terrain/material words any rider can read. Sand Terrain and an Air Current are rules the Sand and
Air plug-ins already implement, so those plug-ins register their own answer here and a rider asks
the kind, never the plug-in: one combat plug-in must not import another plug-in's rules (BRS1F25
lead review).

A kind is a pure predicate ``(engine, owner, zone) -> bool`` asked for each candidate zone. The
rider's ``:own`` suffix is the caller's ownership filter; a predicate only answers "is this zone
this kind of ground". Registration happens when the owning plug-in is imported, and
combat/ext/__init__.py imports every plug-in, so the registry is complete before any fight.
"""
from __future__ import annotations

from typing import Any, Callable

KINDS: dict[str, Callable[[Any, Any, Any], bool]] = {}


def register(name: str, matches: Callable[[Any, Any, Any], bool]) -> None:
    """Let a rider name ``name`` as a zone; ``matches`` decides one zone of that kind."""
    KINDS[str(name)] = matches


def registered(name: str) -> bool:
    """Whether a plug-in owns a rule for this named ground."""
    return str(name) in KINDS


def matches(engine: Any, owner: Any, zone: Any, name: str) -> bool:
    """Whether ``zone`` is the named kind of ground (no ownership test; the caller filters ``:own``)."""
    kind = KINDS.get(str(name))
    return bool(kind and kind(engine, owner, zone))
