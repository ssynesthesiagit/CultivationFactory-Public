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
    from .effect_durations import token
    if not any(expires.startswith(token(edge, owner.entity_id, 0).rsplit(':', 1)[0] + ':')
               for edge in ('start', 'end')):
        raise ValueError('Object marks require an explicit owner turn expiry')
    current = engine.state.objects[obj.object_id]
    marks = dict((current.component or {}).get(KEY, {}))
    marks[key(name, owner.entity_id)] = {'name': name, 'owner_id': owner.entity_id,
                                       'source': source, 'expires': expires}
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
    from .effect_durations import token
    expiry = token(edge, actor.entity_id, actor.turns_started)
    for obj in list(engine.state.objects.values()):
        for mark in list((obj.component or {}).get(KEY, {}).values()):
            if mark['expires'] == expiry:
                remove(engine, obj, mark['name'], mark['owner_id'], mark['source'])


@hook('turn_start')
def starts(engine, actor):
    expire(engine, actor, 'start')


@hook('turn_end')
def ends(engine, actor):
    expire(engine, actor, 'end')
