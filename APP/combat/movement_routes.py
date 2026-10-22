"""Pure route selection/admission shared by native movement and the table API.

Movement execution remains Gate2's per-step executor. No state is cached here
between queries, and previews never interpolate missing waypoint squares.
"""
from .gate2_runtime_models import CandidateKind, Position


def merge_modes(preferred, incoming, alternatives):
    """Keep the cheapest endpoint quote and each distinct native movement mode.

    Roof climbs and high jumps can share a destination with flight but trigger
    different rules. Alternatives are route-bound candidates, so their paths
    and modes participate in identity; the preferred quote keeps its usual ID.
    All containers are local to one read-only candidate query.
    """
    for destination, route in incoming.items():
        previous = preferred.get(destination)
        if previous is None:
            preferred[destination] = route
            continue
        old_mode = previous[2] if len(previous) > 2 else 'walk'
        new_mode = route[2] if len(route) > 2 else 'walk'
        if route[1] < previous[1]:
            preferred[destination] = route
            if old_mode != new_mode:
                alternatives.append((destination, previous))
        elif old_mode != new_mode:
            alternatives.append((destination, route))


def ordered_candidates(candidates):
    """Keep native endpoint ordering, with its cheapest quote before alternatives.

    Path-bound alternative IDs are hashes, not a price ranking. Group them at
    the preferred route's existing ID so adding a mode cannot make the first
    offered route more expensive or reorder unrelated actions/destinations.
    """
    anchors = {(c.actor_id, c.destination): c.candidate_id for c in candidates
               if c.kind == CandidateKind.MOVE and not c.metadata.get('explicit_movement_path')}

    def key(candidate):
        if candidate.kind != CandidateKind.MOVE:
            return candidate.candidate_id, False, candidate.candidate_id
        return (anchors.get((candidate.actor_id, candidate.destination), candidate.candidate_id),
                bool(candidate.metadata.get('explicit_movement_path')), candidate.candidate_id)

    return tuple(sorted(candidates, key=key))


def native_selector(engine, actor):
    from . import ext
    providers = tuple(ext.iter_strict('native_route_selection', engine, actor))
    providers = tuple(p for p in providers if p is not None)
    if len(providers) > 1 or any(not callable(p) for p in providers):
        raise ValueError('Native route selection needs at most one pure selector')
    return providers[0] if providers else None


def validate_path(engine, actor, path, mode):
    from . import flight
    from .granted_movement import native_path_cost
    from .terrain_materials import profile as material_profile
    if mode not in {'walk', 'fly', 'jump', 'climb', 'jump_down', 'swim'} and material_profile(engine, actor, mode) is None:
        raise ValueError('Choose walking, flying, climbing or jumping for this route')
    if len(path) < 2:
        raise ValueError('Choose at least one adjacent space to move to')
    if not actor.active or engine._effective_speed(actor) <= 0:
        raise ValueError('This creature cannot move right now')
    from .roof_movement import max_remaining
    allowance = max_remaining(engine, actor) if mode == 'climb' else flight.remaining(engine, actor, mode)
    if mode == 'jump':
        allowance = flight.path_allowance(engine, actor, path, mode)
    if len(path) > max(0, allowance) // engine.grid.square_size_ft + 1:
        raise ValueError('This route uses more movement than remains this turn')
    cost = native_path_cost(engine, actor, path, mode=mode)
    if cost > allowance:
        raise ValueError('This route uses more movement than remains this turn, including difficult terrain')
    return cost


def _observed_reactors(engine, actor):
    from .target_knowledge import actors_for
    return tuple(actors_for(engine, actor))


def expected_attacks(engine, actor, path, *, cache=None, reactors=None):
    reactors = _observed_reactors(engine, actor) if reactors is None else reactors
    free = int(actor.turn_flags.get('oa_free_ft') or 0)
    attacks = set()
    for a, b in zip(path, path[1:]):
        key = ('oa_edge', a.x, a.y, a.z, b.x, b.y, b.z, bool(free))
        if cache is None:
            eligible = engine.opportunity_eligible(actor, a, b, free_ft=free, reactors=reactors)
        else:
            if key not in cache:
                cache[key] = engine.opportunity_eligible(actor, a, b, free_ft=free, reactors=reactors, cache=cache)
            eligible = cache[key]
        attacks.update(eligible)
        free = max(0, free - engine.grid.square_size_ft)
    return sorted(attacks)


def threat_metadata(engine, actor, path, *, cache=None, reactors=None):
    reactors = _observed_reactors(engine, actor) if reactors is None else reactors
    ids = expected_attacks(engine, actor, path, reactors=reactors, cache={} if cache is None else cache)
    names = {r.entity_id: r.display_name for r in reactors}
    return {'expected_opportunity_attack_count': len(ids),
            'expected_opportunity_attacks': [{'actor_id': aid, 'display_name': names[aid]} for aid in ids]}


def explicit_candidate(engine, actor_id, path, mode='walk'):
    """Reconstruct a route-bound MOVE from current state, without trusting a token."""
    if engine.state.terminal_result is not None or engine.state.pending_resolution is not None or engine.state.setup_tasks:
        raise ValueError('Finish the current decision before choosing a movement route')
    if actor_id != engine.state.current_actor_id or actor_id not in engine.state.actors:
        raise ValueError('Choose a route for the creature whose turn it is')
    from .zones import sync_walls, hazard_test
    sync_walls(engine)
    actor = engine.state.actors[actor_id]
    if actor.life_state in {'DYING', 'STABLE'}:
        raise ValueError('This creature cannot move right now')
    path = tuple(path)
    from .motion import terrain_for
    with terrain_for(engine, actor):
        cost = validate_path(engine, actor, path, mode)
    hazard = hazard_test(engine, actor)
    metadata = {'explicit_movement_path': True, 'movement_mode': mode,
                'compressed_path': [p.model_dump(mode='json') for p in engine.grid.compress_path(path)],
                'reaction_exposure': expected_attacks(engine, actor, path, cache={}),
                'hazard_exposure': engine._path_intersects_cells(actor, path[1:], engine.grid.qi_hazard),
                **threat_metadata(engine, actor, path)}
    if hazard is not None:
        metadata['zone_hazard_exposure'] = any(hazard(p) for p in path[1:])
        metadata['hazard_exposure'] |= metadata['zone_hazard_exposure']
    if mode != 'walk':
        metadata['altitude_ft'] = path[-1].z * 5
    candidate = engine._candidate(CandidateKind.MOVE, actor, 'system:combat.movement',
        'Move along your chosen route', destination=path[-1], path=path,
        movement_cost_ft=cost, metadata=metadata)
    from . import ext
    if ext.any_false('candidate_allowed', engine, actor, candidate, None):
        raise ValueError('This creature cannot take that movement right now')
    return candidate


def parse_waypoints(waypoints):
    """UI paths use integer squares, never rounding/coercing coordinates."""
    try:
        return tuple(Position.model_validate(p, strict=True) for p in waypoints)
    except ValueError as exc:
        raise ValueError('Choose valid whole-number grid squares for every step of your route.') from exc


def context_for_payload(engine, context, payload):
    """General service seam: add only the validated route bound to this request."""
    if payload.get('movement_path') is None:
        if payload.get('movement_mode') is not None:
            raise ValueError('A movement mode requires a chosen route')
        return context
    path = parse_waypoints(payload['movement_path'])
    candidate = explicit_candidate(engine, payload.get('actor_id'), path, payload.get('movement_mode') or 'walk')
    return context.model_copy(update={'legal_candidates': (*context.legal_candidates, candidate)})


def safe_selector(engine, actor):
    """Minimize OA crossings, then hazardous steps, within the native cost DAG.

    Dynamic programming retains projected free-movement feet as a state key.
    Work is bounded by DAG edges and the actor's exemption, never by the number
    of complete paths. Ties keep the original native path wherever possible.
    All eligibility/hazard memoization is local to this one actor query.
    """
    from .zones import hazard_test
    from .gate2_grid import SquareGrid
    reactors = _observed_reactors(engine, actor)
    zone_hazard = hazard_test(engine, actor)
    cache, edge_cache, hazard_cache = {}, {}, {}
    initial_free = int(actor.turn_flags.get('oa_free_ft') or 0)
    def pos(cell):
        return Position(x=cell[0], y=cell[1], z=cell[2] if len(cell) > 2 else 0)
    def score(a, b, free):
        key = (a, b, bool(free))
        if key not in edge_cache:
            if b not in hazard_cache:
                p = pos(b)
                hazard_cache[b] = int(engine._path_intersects_cells(actor, (p,), engine.grid.qi_hazard)
                                     or (zone_hazard is not None and zone_hazard(p)))
            edge_cache[key] = (len(engine.opportunity_eligible(actor, pos(a), pos(b),
                free_ft=free, reactors=reactors, cache=cache)), hazard_cache[b])
        return edge_cache[key]
    def select(start, previous, costs, legacy_parents=None):
        from .spatial_routes import horizontal_steps, projected_path
        horizontal = horizontal_steps(start, previous, costs) if legacy_parents is not None else None
        states = {start: {initial_free: ((0, 0), (start,))}}
        out = {}
        for cell in sorted(previous, key=lambda c: (costs[c], c)):
            states[cell] = {}
            for parent in sorted(previous[cell]):
                for free, (rank, path) in states[parent].items():
                    edge = score(parent, cell, free)
                    nxt_free = max(0, free - engine.grid.square_size_ft)
                    item = ((rank[0] + edge[0], rank[1] + edge[1]), (*path, cell))
                    if nxt_free not in states[cell] or item < states[cell][nxt_free]:
                        states[cell][nxt_free] = item
            chosen = min(states[cell].values())
            if len(start) == 2 or legacy_parents is not None:
                if legacy_parents is not None:
                    legacy = tuple(reversed(projected_path(start, cell, previous, horizontal)))
                else:
                    legacy = tuple(SquareGrid._straight_path(start, cell, previous))
                free, rank = initial_free, (0, 0)
                for a, b in zip(legacy, legacy[1:]):
                    edge = score(a, b, free)
                    rank = (rank[0] + edge[0], rank[1] + edge[1])
                    free = max(0, free - engine.grid.square_size_ft)
                if rank <= chosen[0]:
                    continue
            out[cell] = chosen[1]
        return out
    return select
