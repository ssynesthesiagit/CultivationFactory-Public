"""Authored sensory provenance, shared by information providers (currently Bloodsense).

The sealed arena's optional sensory_sources describes actual sources, not
omniscient findings. Each has a medium/kind, optional source_key, and exactly
one entity_id, object_id or position. Attached sources follow live positions;
destroyed objects and off-battlefield creatures are excluded. Integer seconds
are relative to encounter start (negative timestamps describe earlier events).
expires_at_seconds is exclusive. studied_by records historical, observer-owned
sample study; it never implies that an ally also studied that sample.
"""
from .gate2_runtime_models import Position


def elapsed_seconds(engine):
    return (engine.state.round_number - 1) * 6


def studied_sources(engine, observer, medium):
    """Historical study survives disappearance/expiry of the physical source."""
    for row in (getattr(engine, 'battlefield_document', None) or {}).get('sensory_sources', []):
        if (isinstance(row, dict) and row.get('medium') == medium
                and isinstance(row.get('studied_by'), list)
                and observer.entity_id in row['studied_by']):
            yield row


def sources(engine, medium):
    now = elapsed_seconds(engine)
    for row in (getattr(engine, 'battlefield_document', None) or {}).get('sensory_sources', []):
        if not isinstance(row, dict) or row.get('medium') != medium:
            continue
        expiry = row.get('expires_at_seconds')
        if expiry is not None and (type(expiry) is not int or now >= expiry):
            continue
        if sum(key in row for key in ('entity_id', 'object_id', 'position')) != 1:
            continue
        actor = engine.state.actors.get(row.get('entity_id'))
        obj = engine.state.objects.get(row.get('object_id'))
        if 'entity_id' in row:
            if actor is None or not engine._on_battlefield(actor):
                continue
            position = actor.position
        elif 'object_id' in row:
            if obj is None or obj.destroyed:
                continue
            position = obj.position
        else:
            try:
                position = Position.model_validate(row['position'])
            except (ValueError, TypeError):
                continue
            if not engine.grid.in_bounds((position.x, position.y)):
                continue
        yield row, position, actor, obj
