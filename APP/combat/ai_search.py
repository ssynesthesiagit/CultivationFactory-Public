"""Deterministic exploration using public terrain and the mover's own history.

Used by gate4_context and ext.ai_search_policy.

No enemy truth is used to plan routes. The knowledge projection supplies only
perceived or remembered hostiles; the public perception predicate distinguishes
current observations from remembered copies. Legal walking
candidates remain the authority for occupancy, hazards and movement costs.
"""
from collections import Counter, deque

KEY = 'ai_search_policy'
VERSION = 1


def saved_policy(events):
    for event in reversed(events):
        kind = event.event_type if hasattr(event, 'event_type') else event['event_type']
        payload = event.payload if hasattr(event, 'payload') else event.get('payload', {})
        if kind == 'MATCH_CREATED':
            value = payload.get(KEY, 0)
            if type(value) is not int or value not in (0, VERSION):
                raise ValueError('Unknown saved AI search policy')
            return value
    return 0


def search_move(engine, viewer, candidates, policy, known, recent, *, sightings=None):
    """Return one legal ordinary MOVE id, or None (legacy/visible foe/no safe walk).

    Remembered locations are investigated after their latest recorded sighting,
    even if travelled through earlier. After reaching them, search widens
    using the public map centre and then nearest unvisited reachable cells.
    A searcher with flight commits the whole move to the farthest reachable
    frontier, so a flier does not spend one decision per square (owner
    2026-10-20). Ground searchers keep the nearest-frontier goal, which the
    saved AI replays pin decision for decision. Perceived event destinations
    may guide a search, but only the caller's redacted recent journal is
    accepted. Cover breaks equally advancing routes for defensive/stealthy
    policies. Queries add no events or stored state. Every answer passes the
    spent-turn contact guard, including the sweep-restart and obstruction
    fallbacks (owner 2026-10-20: do not shuffle once in reach).

    ``sightings`` optionally supplies an authoritative mapping of actor id to
    ((x, y), observation sequence), consistent with ``known``. An explicit
    mapping (even empty) replaces team receipts entirely. Callers with personal
    knowledge must also supply only personally observed recent hints, or ().
    None retains native team search for callers without a personal projection.
    """
    if saved_policy(engine.events) != VERSION:
        return None
    from .relations import relation, ENEMY
    from .target_knowledge import located
    hostiles = [a for a in known if a.active and relation(engine, viewer, a) == ENEMY]
    if any(located(engine, viewer, engine.state.actors[a.entity_id]) for a in hostiles):
        return None
    chosen = _search_step(engine, viewer, candidates, policy, hostiles, recent, sightings=sightings)
    if chosen is None or _paces_in_contact(engine, viewer, hostiles, chosen.destination):
        return None
    return chosen.candidate_id


def _search_step(engine, viewer, candidates, policy, hostiles, recent, *, sightings=None):
    """Plan one exploration step; return the chosen candidate row, or None.

    The public search rules live here: remembered-goal investigation, sweep
    restart, obstruction fallback. Returning the row (not the id) lets
    ``search_move`` apply the spent-turn contact guard to every path, including
    both ``fallback()`` returns, which previously bypassed it.
    """
    from .movement_history import endpoints
    previous = endpoints(engine, viewer.entity_id)
    rows = [c for c in candidates if c.kind == 'MOVE' and c.destination is not None
            and c.destination.z == viewer.position.z
            and c.source_definition_id == 'system:combat.movement'
            and c.movement_cost_ft > 0 and not c.metadata.get('hazard_exposure')
            and not c.metadata.get('reaction_exposure') and c.destination not in previous
            and c.destination != viewer.position]
    if not rows:
        return None
    start = (viewer.position.x, viewer.position.y)
    visited = {start}
    visits = Counter({start: 1})
    last_visit = {}
    observations = {} if sightings is None else dict(sightings)
    for event in engine.events:
        # Legacy callers share team receipts. Projected callers supply their
        # own scope; team sightings must never replace its position or time.
        if sightings is None:
            for key in ('observations', 'observations_after'):
                for actor_id, cell in event.payload.get(key, {}).get(viewer.team_id, {}).items():
                    observations[actor_id] = ((cell['x'], cell['y']), event.sequence)
        if event.actor_id == viewer.entity_id and event.event_type == 'MOVEMENT_COMMITTED':
            path = event.payload.get('path') or ()
            for cell in path:
                visited.add((cell['x'], cell['y']))
                visits[(cell['x'], cell['y'])] += 1
                last_visit[(cell['x'], cell['y'])] = event.sequence
            cell = event.payload.get('destination')
            if cell:
                visited.add((cell['x'], cell['y']))
                last_visit[(cell['x'], cell['y'])] = event.sequence
                if cell not in path:
                    visits[(cell['x'], cell['y'])] += 1
    careful = any(word in ' '.join(policy.role).lower() for word in ('defen', 'stealth', 'guard', 'skirmish'))
    def fallback():
        # Public routes cannot predict occupied passages or every temporary
        # movement restriction. Explore another safe, authoritative endpoint.
        # The row, not the id: search_move still applies the spent-turn
        # contact guard to this answer.
        return min(rows, key=lambda c: (visits[(c.destination.x, c.destination.y)],
            -max(abs(c.destination.x-start[0]), abs(c.destination.y-start[1])),
            -int(careful and (c.destination.x, c.destination.y) in grid.cover),
            c.candidate_id))
    # Public terrain only, including footprint and diagonal corner legality.
    # Never call live occupancy. The final step is an existing legal candidate.
    grid = engine.grid
    footprint = engine._footprint(viewer)
    def step_legal(a, b):
        if grid.qi_hazard and any(cell in grid.qi_hazard for cell in grid.footprint_cells(b, footprint)):
            return False
        if viewer.position.z:
            return grid.volume_step_legal((*a, viewer.position.z), (*b, viewer.position.z), footprint=footprint)
        return grid.step_legal(a, b, footprint=footprint)
    distance = {start: 0}
    queue = deque([start])
    neighbors = tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
    while queue:
        cell = queue.popleft()
        for dx, dy in neighbors:
            nxt = (cell[0] + dx, cell[1] + dy)
            if nxt in distance or not step_legal(cell, nxt):
                continue
            distance[nxt] = distance[cell] + 1
            queue.append(nxt)
    frontier = set(distance) - visited
    swept = not frontier
    if not frontier:
        # A completed sweep restarts, with its farthest cell as the next goal.
        frontier = set(distance) - {start}
    if not frontier:
        return fallback()
    def order(cell):
        return (distance[cell], cell[1], cell[0])
    def uninvestigated(cell, sequence):
        # observations_after is written after the movement path in that same
        # receipt. Crossing a cell before that observation is not investigation.
        return cell in distance and cell != start and last_visit.get(cell, -1) <= sequence
    goals = []
    for actor in hostiles:
        cell = (actor.position.x, actor.position.y)
        observed_cell, sequence = observations.get(actor.entity_id, (cell, 0))
        if observed_cell == cell and uninvestigated(cell, sequence):
            goals.append(cell)
    if not goals:
        hints = [(tuple(e['payload']['destination'][k] for k in ('x', 'y')), e['sequence'])
                 for e in recent if e.get('event_type') == 'MOVEMENT_COMMITTED'
                 and e.get('actor_id') in {a.entity_id for a in hostiles}
                 and isinstance(e.get('payload', {}).get('destination'), dict)
                 and all(k in e['payload']['destination'] for k in ('x', 'y'))]
        goals = [cell for cell, sequence in hints if uninvestigated(cell, sequence)]
    if goals:
        goal = min(goals, key=order)
    else:
        centre = (grid.width // 2, grid.height // 2)
        reached_centre = any(max(abs(x-centre[0]), abs(y-centre[1])) <= 1 for x, y in visited)
        # After the centre, a flier heads for the farthest reachable frontier so
        # one decision commits the whole move instead of one square (owner
        # 2026-10-20). Ground search keeps the nearest frontier: the saved AI
        # replays pin those choices, so its decision order must not change.
        from .flight import profile as flight_profile
        flying = flight_profile(engine, viewer).speed_ft > 0
        goal = (min(frontier, key=lambda c: (-distance[c], c[1], c[0]))
                if swept or (reached_centre and flying) else
                min(frontier, key=order) if reached_centre else
                min(frontier, key=lambda c: (max(abs(c[0]-centre[0]), abs(c[1]-centre[1])), *order(c))))
    # Reverse terrain distances give a route around walls rather than a straight
    # line pull toward an unreachable square. Reuse the forward reachable set.
    remaining = {goal: 0}
    queue = deque([goal])
    while queue:
        cell = queue.popleft()
        for dx, dy in neighbors:
            nxt = (cell[0] + dx, cell[1] + dy)
            if nxt in remaining or nxt not in distance or not step_legal(nxt, cell):
                continue
            remaining[nxt] = remaining[cell] + 1
            queue.append(nxt)
    advancing = [c for c in rows if (c.destination.x, c.destination.y) in remaining
                 and remaining[(c.destination.x, c.destination.y)] < remaining.get(start, 0)]
    if not advancing:
        # Public terrain routes cannot predict a currently occupied passage or
        # every temporary movement restriction. Explore another authoritative
        # safe endpoint instead of returning to passive loops. Own visit counts
        # prevent a repeated local obstruction from attracting the same square.
        return fallback()
    best = min(advancing, key=lambda c: (remaining[(c.destination.x, c.destination.y)],
        -int(careful and (c.destination.x, c.destination.y) in grid.cover), c.movement_cost_ft, c.candidate_id))
    return best


def _paces_in_contact(engine, viewer, hostiles, destination):
    """True when a spent turn in base contact would only pace, not close.

    A hostile already in base contact is not found by walking. Once nothing
    but movement is left, a search step must actually close on a contacted
    creature; a step that leaves it just as far away (a remembered square it
    may have left, or a corner the sight ray clips) only paces the same spot
    instead of ending the turn (owner 2026-10-20: do not shuffle once in
    reach). While the creature still has an action or bonus action, its
    planner chooses normally. Contact is measured with the same footprint- and
    height-aware ``_distance_actor_to_actor`` the movement planner reports
    (gate2_engine), not the remembered anchor cell's point distance: a Large
    body, or a flier at another height, is in contact while its anchor is 10 ft
    away. ``destination`` is the step's own endpoint, so the comparison is
    before versus after, per contacted hostile.
    """
    if viewer.action_available or viewer.bonus_action_available:
        return False
    before = {a.entity_id: engine._distance_actor_to_actor(viewer, a) for a in hostiles}
    in_contact = [a for a in hostiles if before[a.entity_id] <= 5]
    if not in_contact:
        return False
    return not any(engine._distance_actor_to_actor(viewer, a, actor_position=destination) < before[a.entity_id]
                   for a in in_contact)
