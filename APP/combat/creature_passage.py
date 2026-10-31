"""Pure voluntary movement geometry, shared by native movement and rider pathfinders.

Passage alone never grants an occupied destination, passage through walls,
or knowledge of unseen creatures. An explicit pass_through_stop reply can
admit a shared endpoint; its provider owns transactional entry checks and a
validated shared_space relationship. Otherwise stopped transit returns to
the last free cell.

A passage grant is one cost plus the exact occupied voxels it covers
------------------------------------------------------------------
Every provider states its own grant: a cost ('free'/'difficult') and the voxels
it covers, or None to cover the whole footprint. Legacy ``pass_through`` replies
are whole-footprint grants; a provider that must not grant more than part of a
footprint answers ``pass_through_grant`` with one ``(cost, scope)`` pair instead.
Pairing the cost with its own scope is what lets independent abilities compose:
a restricted grant can no longer narrow another ability's unrestricted one.
Several grants union their volumes, an unrestricted grant covers the whole
footprint outright, and a voxel several grants cover keeps the cheapest cost.
"""
from . import ext


def _cost(value):
    if value not in ('free', 'difficult'):
        raise ValueError('A passage grant must be free or difficult')
    return value


def _cells(scope):
    if scope is None:
        return None
    if not isinstance(scope, (set, frozenset, tuple, list)):
        raise ValueError('A passage scope must be None or integer 3D cells')
    out = set()
    for cell in scope:
        if (not isinstance(cell, (tuple, list)) or len(cell) != 3
                or any(type(value) is not int for value in cell)):
            raise ValueError('A passage scope must be integer x/y/z triples')
        out.add(tuple(cell))
    return out


def grants(engine, mover, occupant):
    """Every provider's passage grant for one occupant, as (cost, scope) pairs.

    A None scope means the whole occupied footprint. Hook order is preserved but
    carries no meaning: grants union rather than compete.
    """
    out = []
    from .movement_passage import passable
    if passable(engine, mover, occupant):
        out.append(('difficult', None))
    for reply in ext.run('movement_pass_through', engine, mover, occupant):
        if reply is not True:
            raise ValueError('movement_pass_through must return True or None')
        out.append(('difficult', None))
    for reply in ext.run('pass_through', engine, mover, occupant):
        out.append((_cost(reply), None))
    for reply in ext.run('pass_through_grant', engine, mover, occupant):
        if not isinstance(reply, (tuple, list)) or len(reply) != 2:
            raise ValueError('pass_through_grant must return a (cost, scope) pair')
        out.append((_cost(reply[0]), _cells(reply[1])))
    return out


def permission(engine, mover, occupant):
    """Best cost any provider grants through this occupant, or None."""
    costs = [cost for cost, _ in grants(engine, mover, occupant)]
    if not costs:
        return None
    return 'free' if 'free' in costs else 'difficult'


def _ground(cell):
    """The map projection of an occupied voxel, for ground pathfinding."""
    return (cell[0], cell[1])


def _volume(cell):
    """The occupied voxel itself, for height-aware consumers."""
    return cell


def _covered(engine, mover, occupant, cells, *, keys=_ground, unimpeded=False):
    """Return {cell: cost} for each of ``cells`` some current grant covers.

    Each grant is applied to its own scope, so one provider's subset never
    removes another provider's right. ``cells`` is the occupancy the caller is
    actually resolving -- the ground projection or the exact volume -- so a
    grant is never read against a different creature space than the one the
    caller priced. A creator that ignores difficult terrain pays no surcharge,
    matching the shared ignores_difficult query.
    """
    out = {}
    for cost, scope in grants(engine, mover, occupant):
        covered = cells if scope is None else cells & {keys(cell) for cell in scope}
        for cell in covered:
            if cost == 'free' or cell not in out:
                out[cell] = cost
    if unimpeded:
        out = {cell: 'free' for cell in out}
    return out


def geometry(engine, mover, *, observed=False):
    """Return blocked, forbidden endpoints, extra difficult cells and permissions.

    An explicit free grant wins over a difficult grant, but cannot remove map
    terrain costs. Unseen contacts stay blocked until actually observed.
    """
    occupied = engine._occupied_cells_except(mover.entity_id, observed=observed)
    from .movement_passage import passable_occupants
    if not (ext.has('pass_through') or ext.has('pass_through_grant') or ext.has('movement_pass_through')) \
            and not passable_occupants(engine, mover):
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
        costs = _covered(engine, mover, other, cells, unimpeded=unimpeded)
        if not costs:
            blocked |= cells
            continue
        allowed |= set(costs)
        difficult |= {cell for cell, cost in costs.items() if cost == 'difficult'}
        record[other.entity_id] = 'free' if 'free' in costs.values() else 'difficult'
    end_blocked = set()
    for who in record:
        if not any(reply is True for reply in ext.run_strict('pass_through_stop', engine, mover, engine.state.actors[who])):
            end_blocked |= set(engine._actor_cells(engine.state.actors[who])) & allowed
    return (occupied - allowed) | blocked, end_blocked, difficult, record


def volume_geometry(engine, mover, *, observed=False):
    """Height-aware transit occupancy and difficult volumes for flight consumers.

    Only current observed passage grants remove an occupant. Contact blockers and
    other creatures remain; callers use raw occupancy to reject occupied stops.
    """
    from .motion import ignores_difficult
    unimpeded = ignores_difficult(engine, mover)
    record = geometry(engine, mover, observed=observed)[3]
    occupied = engine._occupied_volumes_except(mover.entity_id, observed=observed)
    permitted_volumes, difficult = set(), set()
    for who in record:
        costs = _covered(engine, mover, engine.state.actors[who],
                         set(engine._actor_volume(engine.state.actors[who])),
                         keys=_volume, unimpeded=unimpeded)
        permitted_volumes |= set(costs)
        difficult |= {cell for cell, cost in costs.items() if cost == 'difficult'}
    occupied -= permitted_volumes
    return occupied, difficult


def endpoint_volumes(engine, mover, *, observed=False):
    """Native 3D endpoint collisions, with explicit scoped stop permissions.

    Flight, roof walking, climbing and jumping use this query. Transit grants
    alone never remove endpoint collisions; an independent occupant without a
    stop grant keeps its collision even when another grant covers that voxel.
    Terrain and hidden/remembered contacts retain their ordinary authority.
    """
    occupied = engine._occupied_volumes_except(mover.entity_id, observed=observed)
    record = geometry(engine, mover, observed=observed)[3]
    if not record:
        return occupied
    from .target_knowledge import actors_for
    actors = actors_for(engine, mover) if observed else engine.state.actors.values()
    allowed, protected = set(), set()
    for other in actors:
        if not other.active or other.entity_id == mover.entity_id or engine._shared_occupancy_pair(mover.entity_id, other.entity_id):
            continue
        cells = set(engine._actor_volume(other))
        covered = set()
        if other.entity_id in record and any(reply is True for reply in ext.run_strict('pass_through_stop', engine, mover, other)):
            covered = set(_covered(engine, mover, other, cells, keys=_volume))
        allowed |= covered
        protected |= (cells - covered) & occupied
    return (occupied - allowed) | protected


def finish(engine, mover, traversed, intent, *, mode='walk'):
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
    from .opening_passage import legal_transit_position
    if legal_transit_position(engine, mover):
        return
    from .terrain_materials import placement_legal
    if placement_legal(engine, mover, mover.position, mode):
        return
    for i in range(len(traversed) - 2, -1, -1):
        cell = traversed[i]
        if placement_legal(engine, mover, cell, mode):
            traversed.extend(reversed(traversed[i:-1]))
            mover.position = cell
            engine._remove_zone_leave_conditions(mover)
            engine._append_event('PASSIVE_TRIGGERED', 'system:combat.move', actor_id=mover.entity_id,
                payload={'log': f'{mover.display_name} cannot stop in the occupied or blocked space and returns to the last free space.'})
            return
    raise engine._intent_error('GATE2_PASSAGE_NO_EXIT', 'No free space remains along this movement; choose a different move.', intent)


def entered(engine, mover, previous, intent):
    """Transactional passage notices for the step just taken.

    ``pass_through_entered`` keeps its original first-entry contract: it runs
    once, when a mover's volume begins overlapping a creature it may pass
    through. A player is asked a crossing question exactly once per crossing.

    ``pass_through_entered_cells`` is the general scoped-entry notification: it
    runs with the exact occupied voxels this step newly entered inside that
    creature, narrowed to the volumes the current grants actually cover. A
    consumer that bills per entry or per region reads what was entered instead
    of re-deriving geometry, and several providers can each answer for their own
    region of one crossing.
    """
    if not (ext.has('pass_through_entered') or ext.has('pass_through_entered_cells')):
        return
    before, after = set(engine._actor_volume(mover, previous)), set(engine._actor_volume(mover))
    for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not other.active or other.entity_id == mover.entity_id:
            continue
        cells = set(engine._actor_volume(other))
        if not grants(engine, mover, other):
            continue
        if cells & after and not cells & before:
            if ext.has('pass_through_entered'):
                ext.run_strict('pass_through_entered', engine, mover, other, intent)
        if not ext.has('pass_through_entered_cells'):
            continue
        entered_cells = cells & (after - before) & set(
            _covered(engine, mover, other, cells, keys=_volume))
        if entered_cells:
            ext.run_strict('pass_through_entered_cells', engine, mover, other, frozenset(entered_cells), intent)
