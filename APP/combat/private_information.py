"""Pure source-authorized readings shared by table and automatic-seat contexts.

Providers use private_information(engine, viewer). Each must validate that exact
viewer's durable source and its live subject. No audience/team expansion occurs
here, and no reading is copied into public events or another seat's input.
"""
from __future__ import annotations


def readings(engine, viewer):
    from . import ext

    def primitive(value):
        if type(value) in (str, int, bool) or value is None:
            return True
        if isinstance(value, list):
            return all(primitive(v) for v in value)
        if isinstance(value, dict):
            return all(type(k) is str and primitive(v) for k, v in value.items())
        return False

    out = []
    for rows in ext.run_strict('private_information', engine, viewer):
        if not isinstance(rows, list) or not all(isinstance(r, dict) and primitive(r) for r in rows):
            raise ValueError('private_information requires a list of primitive reading records')
        out.extend(rows)
    return out


def event_value(event, field, default=None):
    """One committed event field, for native models and journal dictionaries."""
    return event.get(field, default) if isinstance(event, dict) else getattr(event, field, default)


def event_audience(engine, event):
    """Intersection of explicit source audiences; None preserves public history.

    Shared by target_knowledge.recent_events and the public tabletop feed.
    This projects retained native inputs; it adds no fact, clock or journal row.
    """
    from . import ext
    audience = None
    for answer in ext.run_strict('event_audience', engine, event):
        if not isinstance(answer, (list, tuple, set, frozenset)) or any(type(a) is not str for a in answer):
            raise ValueError('event_audience requires actor-id strings or None')
        current = frozenset(answer)
        audience = current if audience is None else audience.intersection(current)
    return audience
