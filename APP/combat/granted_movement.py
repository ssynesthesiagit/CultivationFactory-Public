"""Immediate movement granted by abilities, using native movement and reactions.

Merciful Hand uses a separate distance budget and exempts one named reactor.
Alchemy's Formula Intensification uses the same budget and exempts all reactors.
Other abilities may reuse the same path/terrain/drag/Speed checks without
changing the actor's ordinary movement allowance or suppressing every enemy.
Menus use observed occupancy and the same voluntary destination restrictions as
ordinary movement. Actual occupancy is checked only by native step execution,
which records unseen contact. Neither query mutates state or grants information.
"""
from dataclasses import dataclass
from collections.abc import Sequence
from .gate2_runtime_models import LegalCandidate, Position


@dataclass(frozen=True)
class Route(Sequence):
    """Offered path and mode; shared by granted_moves and native validation.

    Query-only value, never stored in fight state. Iteration remains compatible
    with callers that inspect path positions; pass the route intact to commit.
    """
    positions: tuple[Position, ...]
    mode: str

    def __getitem__(self, index):
        return self.positions[index]

    def __len__(self):
        return len(self.positions)


def movement_mode(engine, actor, path, mode=None):
    from . import flight
    selected = mode or (path.mode if isinstance(path, Route) else None)
    if selected is None:
        selected = 'fly' if any(p.z for p in path) and flight.profile(engine, actor).speed_ft else 'walk'
    if selected not in {'walk', 'fly', 'climb', 'jump'}:
        raise ValueError('Granted movement requires walking, flying, climbing or jumping')
    return selected


def _spatial(engine, actor):
    from . import flight
    return bool(actor.position.z or flight.profile(engine, actor).speed_ft)


def routes(engine, actor, feet, mode=None):
    """Where a grant of ``feet`` can legally carry this creature: cell -> (path, cost, mode).

    The one reachability query behind :func:`candidates`, and the general seam a movement rule reads when it
    must know a grant's own reach rather than a route's geometric length (Set Up's endpoint exception). The
    grant budget is priced exactly as native movement prices a route -- terrain, dragging, footprint, flight
    and voluntary-movement restrictions -- and the creature's ordinary movement allowance, position and events
    are left untouched. Read-only; nothing here is stored in fight state.

    ``mode`` (optional) restricts the search to one movement mode (``'walk'`` or ``'fly'``) instead of the
    default merged every-mode answer, so a rule can price a movement against the mode that actually governs it:
    a walking grant must not count an endpoint reachable only by flying. Granting is limited to walking and
    flying (see :func:`movement_mode`), so those are the only two modes that arise here.
    Elevated walking uses the spatial search, preserving the supporting surface and native volume/cost checks.
    """
    if not actor.active or engine._effective_speed(actor) <= 0:
        return {}
    drag = engine._drag_multiplier(actor)
    from .voluntary_movement import path_allowed
    from . import flight
    if mode == 'fly' or actor.position.z or (mode is None and _spatial(engine, actor)):
        return {cell: (tuple(path), cost, flown)
                for cell, (path, cost, flown) in flight.reachable(engine, actor, grant_ft=feet, mode=mode).items()
                if cell != actor.position and path_allowed(engine, actor, path)}
    from .voluntary_movement import edge_predicate
    from .movement_costs import surcharge
    from .posture import walking_extra
    from .creature_passage import geometry
    occupied, end_blocked, extra_difficult, _ = geometry(engine, actor, observed=True)
    restriction = edge_predicate(engine, actor)
    reachable = engine.grid.reachable(actor.position, movement_ft=feet // drag,
        extra_step_cost_ft=surcharge(engine, actor),
        occupied_cells=occupied, end_blocked_cells=end_blocked,
        difficult_cells=engine._hostile_difficult_cells(actor) | extra_difficult,
        footprint=engine._footprint(actor),
        extra_step_multiplier=walking_extra(engine, actor),
        **({'edge_allowed': restriction} if restriction is not None else {}))
    return {cell: (tuple(path), int(cost) * drag, 'walk')
            for cell, (path, cost) in sorted(reachable.items(), key=lambda item: (item[0].y, item[0].x))
            if cell != actor.position and cost * drag <= feet and path_allowed(engine, actor, path)}


def candidates(engine, actor, feet, intent, source):
    """Legal separate-budget routes as offered candidates, each stamped with the grant that built it.

    ``metadata['movement_allowance_ft']`` is the grant's own budget, so a whole-route rule consulted for a
    candidate (``candidate_allowed``) can price itself against the movement actually being made instead of the
    mover's unrelated ordinary allowance."""
    if not actor.active or engine._effective_speed(actor) <= 0:
        return {}
    spatial = _spatial(engine, actor)
    out = {}
    for cell, (path, cost, mode) in routes(engine, actor, feet).items():
        suffix = f'{cell.x},{cell.y},{cell.z}' if spatial else f'{cell.x},{cell.y}'
        out[f'step:{suffix}'] = LegalCandidate(candidate_id=f'grant:{suffix}',
            decision_id=intent.decision_id, state_version=intent.state_version, kind='MOVE',
            actor_id=actor.entity_id, source_definition_id=source,
            display_name=f'Move to {cell.z * 5} ft. altitude' if spatial else 'Step',
            destination=cell, canonical_path=path, movement_cost_ft=cost,
            metadata={'movement_mode': mode, 'movement_allowance_ft': feet} if spatial
                     else {'movement_allowance_ft': feet})
    return out


def path_cost(engine, actor, path, *, mode=None):
    """Price an explicitly selected native movement mode without moving the actor."""
    _validate_origin(actor, path)
    return native_path_cost(engine, actor, path, mode=movement_mode(engine, actor, path, mode))


def _validate_origin(actor, path):
    if not path or any(not isinstance(p, Position) for p in path) or path[0] != actor.position:
        raise ValueError('Movement must start at the creature\'s current space')


def native_path_cost(engine, actor, path, *, mode, grant_ft=None):
    """Validate an offered route against observed geometry; return terrain/drag cost.

    Hidden occupancy is deliberately left for native contact handling, which
    stops safely without charging the blocked step. This query never moves actors.
    Native route admission/recovery and granted movement share these checks;
    the granted wrapper restricts modes, native jumps also enforce posture/height.
    """
    _validate_origin(actor, path)
    from .creature_passage import geometry
    _, _, extra_difficult, _ = geometry(engine, actor, observed=True)
    difficult = engine._hostile_difficult_cells(actor) | extra_difficult
    footprint = engine._footprint(actor)
    from .terrain_materials import profile as material_profile
    material = material_profile(engine, actor, mode)
    from .terrain_materials import placement_legal
    if not placement_legal(engine, actor, path[-1], mode, observed=True):
        raise ValueError('Movement must end in a free legal space')
    from . import flight
    if mode not in {'walk', 'fly', 'jump', 'climb', 'jump_down'} and material is None:
        raise ValueError('Movement requires walking, flying or jumping')
    from .posture import allows_jumping
    if mode == 'jump' and (not allows_jumping(actor) or not flight.valid_jump(engine, actor, path)):
        raise ValueError('This route exceeds the creature\'s jump height or prevents jumping')
    from .roof_movement import valid_climb, valid_drop, step_mode
    if mode == 'climb' and not valid_climb(engine, actor, path):
        raise ValueError('Climbing requires a supported space or existing grip, usable Speed, and an upright creature')
    if mode == 'jump_down' and not valid_drop(engine, actor, path):
        raise ValueError('Jump down by stepping off a supported edge into open space')
    if any(not flight.step_allowed(engine, actor, a, b, mode=mode, observed=True) for a, b in zip(path, path[1:])):
        raise ValueError('Granted movement requires a legal path of adjacent spaces')
    from .voluntary_movement import path_allowed
    if not path_allowed(engine, actor, path):
        raise ValueError('Frightened prevents this movement toward a visible source')
    cost = 0
    for a, b in zip(path, path[1:]):
        cost += flight.step_cost(engine, actor, a, b, mode, difficult)
        if mode == 'climb' and cost > (flight.remaining(engine, actor, step_mode(engine, actor, a, b)) if grant_ft is None else grant_ft):
            raise ValueError('This climbing route exceeds the remaining movement for one of its walking or climbing steps')
    return cost


def resolve_path(engine, actor, path, source, *, feet, intent=None, provokes=True, ignore_oa_from=(), mode=None, use_movement=False):
    """Run a rider's route through native steps/OAs; return actual granted feet spent.

    Call inside the accepted action transaction. The caller owns its grant pool,
    consent and costs. Patrol Responses provoke; Interpose explicitly exempts all
    reactors. Merciful Hand can exempt one reactor. Ordinary movement is untouched.
    Player pauses/errors unwind the outer transaction; an interrupted grant spends
    only the returned distance. The normal recorded path remains authoritative.
    """
    if type(feet) is not int or feet < 0 or type(provokes) is not bool:
        raise ValueError('Granted movement requires a nonnegative distance and an explicit provoking rule')
    if not isinstance(source, str) or not source:
        raise ValueError('Granted movement requires its source')
    ignore_oa_from = tuple(ignore_oa_from)
    if any(not isinstance(a, str) or a not in engine.state.actors for a in ignore_oa_from):
        raise ValueError('Granted movement names an unknown exempt creature')
    mode = movement_mode(engine, actor, path, mode)
    path = tuple(path)
    cost = native_path_cost(engine, actor, path, mode=mode, grant_ft=None if use_movement else feet)
    if cost > feet:
        raise ValueError('Granted movement exceeds its distance allowance')
    if len(path) == 1 or not actor.active or engine._effective_speed(actor) <= 0:
        return 0
    intent = intent or getattr(engine, '_active_intent', None)
    if intent is None:
        raise ValueError('Granted movement requires an active action')
    candidate = LegalCandidate(candidate_id='grant:path', decision_id=intent.decision_id,
        state_version=intent.state_version, kind='MOVE', actor_id=actor.entity_id,
        source_definition_id=source, display_name='Granted movement', destination=path[-1],
        canonical_path=path, movement_cost_ft=cost, metadata={'movement_mode': mode})
    exempt = tuple(ignore_oa_from) if provokes else tuple(engine.state.actors)
    start = len(engine.events)
    from .reaction_trigger import trigger_scope
    with trigger_scope(engine, 'LEAVE_REACH', actor_id=actor.entity_id,
                       target_id=actor.entity_id, source_id=source, roll_kind=''):
        engine._resolve_movement(actor, candidate, intent, granted_ft=None if use_movement else feet,
                                 ignore_oa_from=exempt, grant_source=source)
    receipt = next((e for e in reversed(engine.events[start:]) if e.event_type == 'MOVEMENT_COMMITTED'
                    and e.actor_id == actor.entity_id and e.source_definition_id == source), None)
    return int(receipt.payload['cost_ft' if use_movement else 'granted_cost_ft']) if receipt is not None else 0
