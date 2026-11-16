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
            if 'attack_limit' in row:
                if type(row['attack_limit']) is not int or row['attack_limit'] <= 0:
                    raise ValueError('effect origin attack_limit must be a positive integer')
                record['attack_limit'] = row['attack_limit']
            if any(old['id'] == row['id'] for old in out):
                raise ValueError('effect origin ids must be unique')
            out.append(record)
    return sorted(out, key=lambda row: row['id'])


@contextmanager
def activate(engine, actor, source, record, *, action=None):
    old = getattr(engine, '_effect_origin', None)
    # Nested blocks of the same activation share its limited-origin budget.
    if record and old and old == (actor.entity_id, source, record):
        yield
        return
    remaining = getattr(engine, '_effect_origin_remaining', None)
    committed = getattr(engine, '_effect_origin_committed', False)
    old_action = getattr(engine, '_effect_origin_action', None)
    engine._effect_origin_action = action
    engine._effect_origin = (actor.entity_id, source, record) if record else None
    engine._effect_origin_remaining = record.get('attack_limit') if record else None
    engine._effect_origin_committed = False
    try:
        yield
    finally:
        engine._effect_origin = old
        engine._effect_origin_remaining = remaining
        engine._effect_origin_committed = committed
        engine._effect_origin_action = old_action


def record_for(engine, actor, source=None):
    active = getattr(engine, '_effect_origin', None)
    return active[2] if (active and active[0] == actor.entity_id
                         and (source is None or active[1] == source)
                         and getattr(engine, '_effect_origin_remaining', None) != 0) else None


def commit_usage(engine, actor, source):
    """Seal a limited origin's actual use before consuming its owning grant.

    A real attack roll or entered touch effect now owns this origin snapshot.
    Attached effects retain it even after the next-use condition is removed;
    a nested independent activation cannot borrow the consumed grant.
    """
    row = record_for(engine, actor, source)
    if row and 'attack_limit' in row:
        engine._effect_origin_committed = True


def finish_attack(engine, actor, source):
    """Spend one strike of an explicitly limited origin after its attached effects.

    Typed sequences use this before the next strike. Nested other-source attacks
    retain their own scope; unrestricted remote origins are unchanged.
    """
    if record_for(engine, actor, source) is not None:
        remaining = getattr(engine, '_effect_origin_remaining', None)
        if remaining is not None:
            engine._effect_origin_remaining = max(0, remaining - 1)


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
    if row is None or getattr(engine, '_effect_origin_committed', False):
        return True
    # Providers validate against the actor's physical sight/range, not themselves.
    with activate(engine, actor, action.source_definition_id, None):
        return row in origins(engine, actor, action)


def valid_for_source(engine, actor, source):
    if record_for(engine, actor, source) is None:
        return True
    action = engine.action_catalog.get(source) or getattr(engine, '_effect_origin_action', None)
    return action is not None and action.source_definition_id == source and valid(engine, actor, action)


@contextmanager
def attack(engine, actor, source, *, new_strike=False):
    """Scope typed geometry; a nested new attack cannot reuse a committed limit.

    Attached non-attack effects keep their parent's point. A nested attack block
    after the actual use instead opens physical geometry and restores its parent.
    """
    row = record_for(engine, actor, source)
    if new_strike and row and 'attack_limit' in row and getattr(engine, '_effect_origin_committed', False):
        row = None
    with activate(engine, actor, source, row):
        yield
