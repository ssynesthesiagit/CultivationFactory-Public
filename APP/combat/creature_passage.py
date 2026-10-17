"""Pure voluntary movement geometry, shared by native movement and rider pathfinders.

Passing permission never grants an occupied destination, passage through walls,
or knowledge of unseen creatures. A stopped transit returns to the last free cell.
"""
from . import ext


def permission(engine, mover, occupant):
    replies = ext.run('pass_through', engine, mover, occupant)
    if any(reply not in ('free', 'difficult') for reply in replies):
        raise ValueError('pass_through must return None, free or difficult')
    return 'free' if 'free' in replies else 'difficult' if replies else None


def geometry(engine, mover, *, observed=False):
    """Return blocked, forbidden endpoints, extra difficult cells and permissions.

    An explicit free grant wins over a difficult grant, but cannot remove map
    terrain costs. Unseen contacts stay blocked until actually observed.
    """
    occupied = engine._occupied_cells_except(mover.entity_id, observed=observed)
    if not ext.has('pass_through'):
        return occupied, set(), set(), {}
    from .target_knowledge import actors_for, knowledge
    from .motion import ignores_difficult
    actors = actors_for(engine, mover) if observed else engine.state.actors.values()
    unimpeded = ignores_difficult(engine, mover)
    allowed, blocked, difficult, record = set(), set(), set(), {}
    for other in actors:
        if not other.active or other.entity_id == mover.entity_id or engine._shared_occupancy_pair(mover.entity_id, other.entity_id):
            continue
        known = knowledge(engine, mover, engine.state.actors[other.entity_id])
        if known is None or known.mode != 'DIRECT':
            # Candidate geometry must not reveal them; actual execution must
            # retain their collision so native contact can stop and locate them.
            continue
        cells = set(engine._actor_cells(other))
        result = permission(engine, mover, other)
        if result == 'difficult' and unimpeded:
            result = 'free'
        if result:
            allowed |= cells
            if result == 'difficult':
                difficult |= cells
            record[other.entity_id] = result
        else:
            blocked |= cells
    return (occupied - allowed) | blocked, allowed, difficult, record


def volume_geometry(engine, mover, *, observed=False):
    """Height-aware transit occupancy and difficult volumes for flight consumers.

    Only current observed passage grants remove an occupant. Contact blockers and
    other creatures remain; callers use raw occupancy to reject occupied stops.
    """
    record = geometry(engine, mover, observed=observed)[3]
    occupied = engine._occupied_volumes_except(mover.entity_id, observed=observed, ignore_actor_ids=record)
    difficult = {cell for who, cost in record.items() if cost == 'difficult'
                 for cell in engine._actor_volume(engine.state.actors[who])}
    return occupied, difficult


def finish(engine, mover, traversed, intent):
    """A reaction stopping transit cannot leave overlapping creatures on the map.

    Return along the already traversed path to its last unoccupied placement,
    retaining movement already spent. The correction is part of the recorded move.
    Callers capture willing distance before recovery extends the path: returning
    to a free space cannot qualify willing-movement triggers or Afterimage.
    """
    # Inactive creatures have no occupied volume. In particular, dying during
    # transit can end a rider/mount sharing grant: the surviving mount then
    # occupies every traversed cell, but the dead rider needs no free endpoint.
    if not mover.active:
        return
    occupied = engine._occupied_volumes_except(mover.entity_id)
    if engine.grid.volume_legal(mover.position, footprint=engine._footprint(mover), occupied_cells=occupied):
        return
    for i in range(len(traversed) - 2, -1, -1):
        cell = traversed[i]
        if engine.grid.volume_legal(cell, footprint=engine._footprint(mover), occupied_cells=occupied):
            traversed.extend(reversed(traversed[i:-1]))
            mover.position = cell
            engine._remove_zone_leave_conditions(mover)
            engine._append_event('PASSIVE_TRIGGERED', 'system:combat.move', actor_id=mover.entity_id,
                payload={'log': f'{mover.display_name} cannot stop in the occupied or blocked space and returns to the last free space.'})
            return
    raise engine._intent_error('GATE2_PASSAGE_NO_EXIT', 'No free space remains along this movement; choose a different move.', intent)


def entered(engine, mover, previous, intent):
    """Transactional notice for a newly entered creature footprint, after a step."""
    if not ext.has('pass_through_entered'):
        return
    before, after = set(engine._actor_volume(mover, previous)), set(engine._actor_volume(mover))
    for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not other.active or other.entity_id == mover.entity_id:
            continue
        cells = set(engine._actor_volume(other))
        if cells & after and not cells & before and permission(engine, mover, other):
            ext.run_strict('pass_through_entered', engine, mover, other, intent)
