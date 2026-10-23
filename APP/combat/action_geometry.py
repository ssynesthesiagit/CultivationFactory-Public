"""Scoped activation geometry; shared by native menus, attacks and typed areas.

An origin changes effect geometry, never the actor's physical position, footprint,
movement, auras or reaction reach. Candidate identity binds the selected record.
"""
from contextlib import contextmanager
from .gate2_runtime_models import Position


def origins(engine, actor, action):
    from . import ext
    out = []
    for rows in ext.run_strict('effect_origins', engine, actor, action):
        if not isinstance(rows, (list, tuple)):
            raise ValueError('effect_origins must return a list of origin records')
        for row in rows:
            if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k] for k in ('id', 'label')):
                raise ValueError('an origin requires a stable id and readable label')
            pos = row.get('position')
            if (not isinstance(pos, dict) or not {'x', 'y'} <= set(pos) <= {'x', 'y', 'z'}
                    or any(type(v) is not int for v in pos.values()) or pos.get('z', 0) < 0):
                raise ValueError('origin positions require integer x/y cells and optional nonnegative altitude z')
            if not engine.grid.in_bounds((pos['x'], pos['y'])):
                raise ValueError('origin must be inside the battlefield')
            record = {'id': row['id'], 'label': row['label'], 'position': dict(pos)}
            if any(old['id'] == row['id'] for old in out):
                raise ValueError('effect origin ids must be unique')
            out.append(record)
    return sorted(out, key=lambda row: row['id'])


@contextmanager
def activate(engine, actor, source, record):
    old = getattr(engine, '_effect_origin', None)
    engine._effect_origin = (actor.entity_id, source, record) if record else None
    try:
        yield
    finally:
        engine._effect_origin = old


def record_for(engine, actor, source=None):
    active = getattr(engine, '_effect_origin', None)
    return active[2] if active and active[0] == actor.entity_id and (source is None or active[1] == source) else None


def point(engine, actor):
    row = record_for(engine, actor)
    return Position(**row['position']) if row else actor.position


def cells(engine, actor):
    row = record_for(engine, actor)
    return {(row['position']['x'], row['position']['y'])} if row else engine._actor_cells(actor)


def distance(engine, actor, target):
    if point(engine, actor).z or target.position.z:
        return engine.grid.distance_between_cell_sets_ft(volume(engine, actor), engine._actor_volume(target))
    return engine.grid.distance_between_cell_sets_ft(cells(engine, actor), engine._actor_cells(target))


def volume(engine, actor):
    """Activation origin in three dimensions; an unshifted creature keeps its body."""
    from .space import point as coordinates
    row = record_for(engine, actor)
    return {coordinates(point(engine, actor))} if row else engine._actor_volume(actor)


def valid(engine, actor, action):
    row = record_for(engine, actor, action.source_definition_id)
    if row is None:
        return True
    # Providers validate against the actor's physical sight/range, not themselves.
    with activate(engine, actor, action.source_definition_id, None):
        return row in origins(engine, actor, action)


def valid_for_source(engine, actor, source):
    if record_for(engine, actor, source) is None:
        return True
    action = engine.action_catalog.get(source)
    return action is not None and valid(engine, actor, action)


@contextmanager
def attack(engine, actor, source):
    """Scope the whole typed effect/attack, including pre-roll queries and hooks."""
    row = record_for(engine, actor, source)
    with activate(engine, actor, source, row):
        yield
