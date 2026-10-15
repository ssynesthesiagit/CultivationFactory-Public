"""Evented, owner-bound marks on objects, shared by Stars and object consumers.

An object is not an actor. Its marks live on the native object component and
use the same explicit turn tokens as creature conditions. Unknown marks and
objects without marks are inert; no object is given turns, senses or consent.
"""
from . import hook

KEY = 'object_marks'


def key(name, owner_id):
    return name + ':' + owner_id


def has(obj, name, owner_id):
    return key(name, owner_id) in (obj.component or {}).get(KEY, {})


def apply(engine, obj, name, owner, source, expires):
    """Commit one named mark with an explicit recognized turn expiry token."""
    from .effect_durations import token, parse_round
    if engine.state.actors.get(owner.entity_id) is not owner:
        raise ValueError('Object marks require their actual native source owner.')
    if not isinstance(expires, str) or not (expires == 'CONCENTRATION_END' or parse_round(expires)
            or any(expires.startswith(token(edge, owner.entity_id, 0).rsplit(':', 1)[0] + ':')
                and expires.rsplit(':', 1)[-1].isdigit() for edge in ('start', 'end'))):
        raise ValueError('Object marks require a recognized source turn, counted or concentration expiry.')
    current = engine.state.objects[obj.object_id]
    marks = dict((current.component or {}).get(KEY, {}))
    marks[key(name, owner.entity_id)] = {'name': name, 'owner_id': owner.entity_id,
                                       'source': source, 'expires': expires,
                                       'applied_sequence': int(engine.state.event_sequence + 1)}
    engine._update_object(current.model_copy(update={'component': {**(current.component or {}), KEY: marks}}),
                          source, owner.entity_id)


def remove(engine, obj, name, owner_id, source):
    current = engine.state.objects[obj.object_id]
    marks = dict((current.component or {}).get(KEY, {}))
    if marks.pop(key(name, owner_id), None) is None:
        return
    engine._update_object(current.model_copy(update={'component': {**(current.component or {}), KEY: marks}}),
                          source, owner_id)


def expire(engine, actor, edge):
    from .effect_durations import token, due
    expiry = token(edge, actor.entity_id, actor.turns_started) if edge in ('start', 'end') else None
    for obj in list(engine.state.objects.values()):
        for mark in list((obj.component or {}).get(KEY, {}).values()):
            concentration_ended = (mark['expires'] == 'CONCENTRATION_END' and not getattr(
                engine.state.actors.get(mark['owner_id']), 'concentration', None))
            if mark['expires'] == expiry or due(engine, mark['expires']) or concentration_ended:
                remove(engine, obj, mark['name'], mark['owner_id'], mark['source'])


def resolved_expiry(ctx, effect):
    """Use the executor's actual default/talent timing without creature storage."""
    from ..typed_executor import mark_timing
    from .effect_durations import token
    expires, data = mark_timing(ctx, effect)
    if expires in ('START_OF_MARKER_NEXT_TURN', 'END_OF_MARKER_NEXT_TURN'):
        edge = 'start' if expires.startswith('START') else 'end'
        return token(edge, ctx.actor.entity_id, int((data or {}).get('marker_turn', ctx.actor.turns_started)) + 1)
    return expires


@hook('event', nested=True)
def concentration_ends(engine, event_type, kwargs):
    if event_type == 'CONCENTRATION_ENDED':
        actor = engine.state.actors.get(kwargs.get('actor_id'))
        if actor is not None:
            expire(engine, actor, 'concentration')


@hook('turn_start')
def starts(engine, actor):
    expire(engine, actor, 'start')


@hook('turn_end')
def ends(engine, actor):
    expire(engine, actor, 'end')
