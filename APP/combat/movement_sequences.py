"""Scoped feature selection for one accepted movement sequence.

Consumers: native movement, motion passives and Athletics. No selection means
no restriction. Bind inside movement_begin or teleport_begin; nested moves and pauses restore the
enclosing scope. A primitive receipt on MOVEMENT_COMMITTED survives reload.
"""
from contextlib import contextmanager


@contextmanager
def sequence(engine, actor, *, context=None):
    old = getattr(engine, '_movement_sequence', None)
    old_context = getattr(engine, '_movement_context', None)
    engine._movement_sequence = {'actor_id': actor.entity_id}
    engine._movement_context = dict(context or {})
    try:
        yield
    finally:
        engine._movement_sequence = old
        engine._movement_context = old_context


def context(engine, actor):
    """Read this mover's initiating feature metadata; nested moves start fresh.

    Native and granted movement providers may supply ``feature_id`` for the
    ability already executing. This is context, never a feature selection or
    permission; owned plug-ins decide how it constrains their own binding.
    """
    scope = getattr(engine, '_movement_sequence', None) or {}
    if scope.get('actor_id') != actor.entity_id:
        return {}
    return dict(getattr(engine, '_movement_context', None) or {})


def bind(engine, actor, family, available, selected):
    scope = getattr(engine, '_movement_sequence', None)
    if scope is None or scope['actor_id'] != actor.entity_id:
        raise ValueError('Movement selection must belong to the accepted sequence')
    if not set(selected) <= set(available) or len(set(selected)) != len(selected):
        raise ValueError('Movement selection must name distinct available features')
    scope[family] = {'available': tuple(available), 'selected': tuple(selected)}


def enabled(engine, actor, feature_id):
    scope = getattr(engine, '_movement_sequence', None) or {}
    if scope.get('actor_id') != actor.entity_id:
        return True
    return all(feature_id not in row['available'] or feature_id in row['selected']
               for key, row in scope.items() if key != 'actor_id')


def receipt(engine, actor):
    scope = getattr(engine, '_movement_sequence', None) or {}
    if scope.get('actor_id') != actor.entity_id:
        return {}
    return {key: list(row['selected']) for key, row in scope.items() if key != 'actor_id'}


def moved_ft(engine, actor, feature_id):
    """This turn's willing feet on sequences where this feature was selected.

    Unrestricted routes preserve their existing meaning. Forced movement never
    earns a movement feature; data is read from persisted movement receipts.
    """
    total = 0
    for event in reversed(engine.events):
        if event.event_type == 'TURN_STARTED' and event.actor_id == actor.entity_id:
            break
        if event.event_type != 'MOVEMENT_COMMITTED' or event.actor_id != actor.entity_id:
            continue
        payload = event.payload or {}
        if payload.get('forced'):
            continue
        selected = payload.get('movement_selections', {}).get('motion')
        if selected is not None and feature_id not in selected:
            continue
        path = payload.get('path') or ()
        from .gate2_runtime_models import Position
        total += sum(engine.grid.distance_ft(Position(**a), Position(**b)) for a, b in zip(path, path[1:]))
    return total
