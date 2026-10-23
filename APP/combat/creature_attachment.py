"""Recorded contained attachments used by Scale Foe and creature-body consumers.

Only an explicit receipt waives the carrier/attached creature's mutual collision.
Native collision against all other creatures remains unchanged. Carried position
changes retain integer offsets and publish normal movement receipts. Moving out
of the carrier's volume ends the attachment; removing the carrier ends it too.
"""
from . import ext

CONDITION = 'condition:typed.creature_attachment'


def receipt(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == CONDITION), None)


def carrier(engine, actor):
    c = receipt(actor)
    other = engine.state.actors.get(c.data['carrier_id']) if c else None
    return other if other and other.active and actor.active else None


def contained(engine, actor, other):
    return set(engine._actor_volume(actor)) <= set(engine._actor_volume(other))


def release_path(engine, actor, other):
    """Nearest collision-safe physical path outside the carrier, for dislodging.

    All six neighbouring placements are searched, so the release is not limited to
    the four horizontal sides: a clinger can also be shaken free into the clear
    space above or below the carrier's occupied volume (a walled shaft, say).
    Every step must pass the same volume legality the forced route rechecks.
    """
    from collections import deque
    occupied = engine._occupied_volumes_except(actor.entity_id)
    host = set(engine._actor_volume(other))
    footprint = engine._footprint(actor)
    start = actor.position
    queue, seen = deque([(start, (start,))]), {(start.x, start.y, start.z)}
    while queue:
        at, path = queue.popleft()
        if not set(engine._actor_volume(actor, at)) & host:
            return path
        for dx, dy, dz in ((-1, 0, 0), (0, -1, 0), (0, 1, 0), (1, 0, 0), (0, 0, -1), (0, 0, 1)):
            x, y, z = at.x + dx, at.y + dy, at.z + dz
            key = (x, y, z)
            if z < 0 or x < 0 or y < 0 or x >= engine.grid.width or y >= engine.grid.height or key in seen:
                continue
            nxt = at.model_copy(update={'x': x, 'y': y, 'z': z})
            if engine.grid.volume_step_legal(at, nxt, footprint=footprint, occupied_cells=occupied):
                seen.add(key)
                queue.append((nxt, (*path, nxt)))
    return None


def bind(engine, actor, other, source):
    engine._apply_condition(actor, CONDITION, source, actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'carrier_id': other.entity_id, 'offset_x': 0, 'offset_y': 0, 'offset_z': 0,
              'label': f'Clinging to {other.display_name}; move outside its space or be dislodged to let go.'})


@ext.hook('shared_occupancy')
def shared(engine, left, right):
    for actor, other in ((left, right), (right, left)):
        if carrier(engine, actor) is other:
            return {'rider_id': actor.entity_id, 'mount_id': other.entity_id, 'contained': True}


@ext.hook('support_surface')
def carrier_support(engine, actor, position):
    host = carrier(engine, actor)
    if host and set(engine._actor_volume(actor, position)) <= set(engine._actor_volume(host)):
        return True


def reconcile(engine, moved):
    c = receipt(moved)
    host = carrier(engine, moved)
    if c:
        if host and contained(engine, moved, host):
            data = {**c.data, **{f'offset_{axis}': getattr(moved.position, axis) - getattr(host.position, axis)
                               for axis in ('x', 'y', 'z')}}
            if data != c.data:
                engine._update_condition_data(moved, c, data, c.source_definition_id)
        else:
            engine._remove_condition(moved, CONDITION, c.source_definition_id)
    for actor in list(engine.state.actors.values()):
        if actor is moved or carrier(engine, actor) is not moved:
            continue
        c = receipt(actor)
        at = moved.position.model_copy(update={axis: getattr(moved.position, axis) + c.data[f'offset_{axis}']
                                              for axis in ('x', 'y', 'z')})
        if at != actor.position:
            before = actor.position
            actor.position = at
            engine._append_event('MOVEMENT_COMMITTED', c.source_definition_id, actor_id=actor.entity_id,
                payload={'destination': at.model_dump(mode='json'), 'cost_ft': 0, 'forced': True,
                         'carried_by': moved.entity_id, 'path': [before.model_dump(mode='json'), at.model_dump(mode='json')]})
            # Placement is forced: entry/leave effects apply, willing-travel
            # thresholds do not. This strict seam preserves transaction pauses.
            from . import zones
            zones.on_moved(engine, actor, before, at, forced=True)


@ext.hook('movement_landed')
def moved_step(engine, actor, previous, destination, intent, forced):
    reconcile(engine, actor)


@ext.hook('event', nested=True)
def committed_position(engine, kind, kwargs):
    if kind not in ('MOVEMENT_COMMITTED', 'ENTITY_DEFEATED', 'SUMMON_DISMISSED'):
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    if actor.active:
        if (kwargs.get('payload') or {}).get('teleport'):
            # A self-teleport does not also teleport another creature clinging
            # to the caster. The caster's selected destination stays unchanged.
            for other in engine.state.actors.values():
                c = receipt(other)
                if c and c.data['carrier_id'] == actor.entity_id and not contained(engine, other, actor):
                    engine._remove_condition(other, CONDITION, c.source_definition_id)
        reconcile(engine, actor)
    else:
        for other in engine.state.actors.values():
            c = receipt(other)
            if c and c.data['carrier_id'] == actor.entity_id:
                engine._remove_condition(other, CONDITION, c.source_definition_id)
