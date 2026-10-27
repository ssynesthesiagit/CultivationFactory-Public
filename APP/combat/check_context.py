"""Explicit sensory source provenance shared by ability and skill check hooks.

Callers state source_actor_id or source_position, observer_id, senses, purpose,
issues and ordinary. Nothing is inferred from unrelated talents or a roster.
The resolver's metadata is ephemeral; CHECK_ROLLED retains the primitive receipt.
Sound uses this for source-zone hearing and sound-only quiet movement.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_CHECK = ContextVar('source_check', default=None)


def metadata_document(value):
    """Copy only canonical primitive provenance; never persist floats/objects."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('Check metadata must be a primitive mapping')

    def primitive(item):
        if type(item) in (str, int):
            return item
        if type(item) is bool:
            return int(item)
        if isinstance(item, list):
            return [primitive(child) for child in item]
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            return {key: primitive(child) for key, child in item.items()}
        raise ValueError('Check metadata must contain only strings, integers and primitive containers')

    return primitive(value)


@contextmanager
def checking(engine, actor, metadata):
    document = metadata_document(metadata)
    token = _CHECK.set((engine, actor.entity_id, document) if document else None)
    try:
        yield
    finally:
        _CHECK.reset(token)


def current(engine, actor):
    """Only this engine/roller's explicit metadata; missing context is inert."""
    frame = _CHECK.get()
    return dict(frame[2]) if frame and frame[:2] == (engine, actor.entity_id) else {}
