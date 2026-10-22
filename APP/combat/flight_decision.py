"""Read-only flight facts for the built-in controller, shared with recovery.

These are decision annotations, never new movement or attack permissions.  The
native menu remains authoritative.  Ordinary grounded decisions return their
original candidates unchanged, including their metadata and serialized bytes.

Only the acting creature's own capabilities/deadlines and currently perceived
creatures enter this projection.  A remembered enemy is not a current threat.
No expiry callbacks, turn execution, observations, or dice are run here.
"""
from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import dataclass

from .gate2_runtime_models import CandidateKind
from .read_queries import pure
from .relations import ALLY, ENEMY, ordinary_turn, relation


METADATA_KEY = 'flight_tactics'
POSITION_LIMIT = 64
DESCENT_ROUTE_LIMIT = 16
DESCENT_STEP_LIMIT = 128
FORECAST_TURN_LIMIT = 16
EXPIRY_SUBSET_LIMIT = 8
_LEGACY_EXPIRIES = {
    'START_OF_TURN': {'START_OF_SELF_NEXT_TURN', 'START_OF_TARGET_NEXT_TURN'},
    'END_OF_TURN': {'END_OF_CURRENT_TURN', 'END_OF_TARGET_NEXT_TURN_OR_CONSUMED'},
}


@dataclass(frozen=True)
class _Deadline:
    movement_ft: tuple[int, ...]
    states: tuple


def _clear_query_memos(view):
    # Service menu closures retain their originating live engine.  AI restraint
    # memos predate altitude and do not include z in their position keys.
    for name in ('legal_candidates', '_ai_close_in_memo', '_ai_strike_memo',
                 '_cf_availability', '_cf_state_key'):
        view.__dict__.pop(name, None)


def _query_copy(engine):
    """Isolate query-local state, geometry caches and any native read caches.

    Native query methods execute on this ordinary engine copy; no methods or
    imports are replaced.  In particular a service's cached legal_candidates
    closure is never used by these prospective per-action queries.
    """
    view = copy(engine)
    view.state = engine.state.model_copy(deep=True)
    view.grid = deepcopy(engine.grid)
    view.events = list(engine.events)
    view.rolls = list(engine.rolls)
    view.roller = copy(engine.roller)
    view._gate4_reaction_provider = None
    view._effect_origin = None
    view._shot_geometry = None
    _clear_query_memos(view)
    return view


def _at(view, actor_id, candidate):
    from .flight import spend
    projected = copy(view)
    actor = view.state.actors[actor_id].model_copy(deep=True, update={'position': candidate.destination})
    spend(actor, candidate.movement_cost_ft)
    projected.state = view.state.model_copy(update={
        'actors': {**view.state.actors, actor_id: actor}})
    _clear_query_memos(projected)
    return projected, actor


def _damaging(action):
    from .target_knowledge import is_attack
    return bool(is_attack(action) or action.damage is not None
                or int(action.parameters.get('expected_damage') or 0) > 0)


def _attacks(view, actor, *, own):
    """Possessed targeted strikes; prices are checked only for the actor itself.

    Enemy threat geometry deliberately does not inspect its private resource
    reserves, present action economy, or effect deadlines to predict a turn.
    Area placement and future riders remain the ordinary controller's concern.
    """
    from .attack_reach import melee
    from . import loadout
    from .typed_executor import condition_rules
    from .ext.hand_occupancy import weapon_allowed
    if own and (not actor.active or actor.life_state in {'DYING', 'STABLE'}
                or any(row.get('no_actions') for row in condition_rules(actor))):
        return ()
    hidden = loadout.hidden(view, actor)
    disabled = {row.data.get('disables_action') for row in actor.conditions.values()}
    held = {row.data.get('disables_action') for holder in view.state.actors.values()
            for row in holder.conditions.values() if row.data.get('held_by') == actor.entity_id}
    out = []
    for source in sorted(set(actor.action_ids) - set(hidden)):
        action = view.action_catalog.get(source)
        if (action is None or action.target_kind not in
                {'HOSTILE_ENTITY', 'HOSTILE_ENTITY_OR_SELF', 'ANY_CREATURE'}
                or not _damaging(action)):
            continue
        if action.parameters.get('inert') or action.parameters.get('player_only'):
            continue
        # These specialized menu families have further top-level native gates.
        # Do not predict their availability through a per-action geometry query.
        if any(action.parameters.get(key) for key in
               ('requires_wall', 'item_action', 'stealth', 'shape_costs')):
            continue
        if not own and not melee(action):
            continue
        # Public physical possession/grip rules apply even when predicting a
        # foe's next turn. A stowed, dropped or taken long weapon is not reach.
        required_weapon = action.parameters.get('requires_held_weapon')
        if (source.split('#', 1)[0] in disabled
                or required_weapon and required_weapon not in held
                or weapon_allowed(view, actor, action) is False):
            continue
        if own:
            economy = str(getattr(action.economy, 'value', action.economy))
            if (economy == 'ACTION' and not actor.action_available
                    or economy == 'BONUS_ACTION' and not actor.bonus_action_available
                    or economy not in {'ACTION', 'BONUS_ACTION'}):
                continue
            if not view._can_pay(actor, action.costs, source_id=source):
                continue
        out.append(action)
    return tuple(out)


def _expiry_due(view, holder, row, checkpoint):
    """Ask the native deadline reader about this row's own skipped-slot clock.

    engine_due also supports combined-record callers by taking their greatest
    skipped offset.  Isolating this one row avoids shortening a second grant
    that happens to have the same token but a different lifetime offset.
    """
    from .ext.effect_durations import engine_due
    if row.expires_on in _LEGACY_EXPIRIES[checkpoint]:
        return (view.state.current_actor_id in {row.source_actor_id, holder.entity_id}
                or (not hasattr(row, 'condition_id') and row.expires_on == 'END_OF_CURRENT_TURN'))
    isolated = copy(view)
    condition = hasattr(row, 'condition_id')
    actor = holder.model_copy(update={
        'conditions': {row.instance_id: row} if condition else {},
        'modifiers': {} if condition else {row.modifier_id: row}})
    isolated.state = view.state.model_copy(update={
        'actors': {**view.state.actors, actor.entity_id: actor}})
    return engine_due(isolated, row.expires_on, checkpoint,
                      source_id=row.source_actor_id, holder_id=holder.entity_id,
                      ending_id=view.state.current_actor_id if checkpoint == 'END_OF_TURN' else None)


def _expiry_family(row, checkpoint):
    """Native sweep order: legacy rows, source/holder rows, then named hooks."""
    from .ext.effect_durations import NATIVE_SOURCE_START, NATIVE_HOLDER_END, NATIVE_SOURCE_TURN
    if row.expires_on in _LEGACY_EXPIRIES[checkpoint]:
        return 0
    if (row.expires_on in {NATIVE_SOURCE_START, NATIVE_HOLDER_END}
            or str(row.expires_on or '').startswith(NATIVE_SOURCE_TURN + ':')):
        return 1
    return 2


def _expiry_can_fall(view, actor, field, keys):
    """Whether any native same-phase removal order could lose support.

    Canonical saves sort mapping keys, so warm insertion order is not stable
    across a cold load. Every removed subset is a prefix of some legal order.
    Inspect all subsets of at most eight due rows; larger simultaneous batches
    conservatively warn instead of depending on incidental mapping order.
    """
    if len(keys) > EXPIRY_SUBSET_LIMIT:
        return True
    from .candidate_knowledge import perceived_ids, query
    from .falling import required
    records = getattr(actor, field)
    permitted = perceived_ids(view)
    for mask in range(1, 1 << len(keys)):
        removed = {key for index, key in enumerate(keys) if mask & (1 << index)}
        projected = copy(view)
        holder = actor.model_copy(update={field: {key: row for key, row in records.items() if key not in removed}})
        projected.state = view.state.model_copy(update={'actors': {**view.state.actors, actor.entity_id: holder}})
        _clear_query_memos(projected)
        with query(projected, perceived_actor_ids=permitted):
            if required(projected, holder):
                return True
    return False


def _nominal_clock(holder, omitted_id):
    """Advance only this holder's counted deadlines on an omitted native slot."""
    from .ext.effect_durations import expiry_key, parse, skipped_expiry_slots
    for row in (*holder.conditions.values(), *holder.modifiers.values()):
        parsed = parse(row.expires_on)
        anchored = (parsed is not None and parsed[1] == omitted_id) or (
            (str(row.expires_on or '').startswith('END_OF_SOURCE_TURN_AT:')
             or row.expires_on in {'START_OF_MARKER_NEXT_TURN', 'END_OF_MARKER_NEXT_TURN'})
            and row.source_actor_id == omitted_id)
        if anchored:
            holder.turn_flags[expiry_key(row)] = skipped_expiry_slots(holder, row) + 1


def _flight_deadline(engine, actor_id, air_position, perceived_actor_ids):
    """Future movement allowances before a known loss of airborne support.

    Project only stored clocks and the actor's own expiring rows through this
    turn's end and at most sixteen further own turns.  A surviving overlapping
    grant, permanent flight, Hover, or suspension prevents the support-loss warning.
    Future damage, concentration saves, recasts and unknown custom expiry
    mechanisms are not forecast.  None means no known support loss in the
    bounded horizon; an empty movement tuple means no future opportunity.
    Isolated snapshots retain the known movement modifiers at each future
    opportunity, so a discount ending before descent cannot buy extra time.
    """
    from .candidate_knowledge import query
    view = _query_copy(engine)
    with query(view, perceived_actor_ids=perceived_actor_ids):
        return _deadline(view, actor_id, air_position)


def _deadline(view, actor_id, air_position):
    from .falling import required
    from .flight import profile
    from .turn_decisions import omits_turn
    actor = view.state.actors[actor_id]
    if not actor.conditions and not actor.modifiers:
        return None
    actor.position = air_position
    if required(view, actor):
        return None  # already unsupported is not a predicted expiry

    def boundary(checkpoint):
        for family in range(3):
            # The native TURN_* event settles before the named expiry hooks.
            if family == 2 and required(view, actor):
                return True
            for field in ('conditions', 'modifiers'):
                records = getattr(actor, field)
                expired = sorted(key for key, row in records.items()
                                 if _expiry_family(row, checkpoint) == family
                                 and _expiry_due(view, actor, row, checkpoint))
                if _expiry_can_fall(view, actor, field, expired):
                    return True
                for key in expired:
                    del records[key]
        return False

    if boundary('END_OF_TURN'):
        return _Deadline((), ())
    order = view.state.initiative_order
    if not order:
        return None
    budgets, states = [], []
    for _ in range(len(order) * FORECAST_TURN_LIMIT):
        slot = view.state.current_slot_index + 1
        if slot == len(order):
            slot = 0
            view.state.round_number += 1
        view.state.current_slot_index = slot
        current_id = order[slot]
        view.state.current_actor_id = current_id
        current = view.state.actors.get(current_id)
        if current is None:
            continue
        omitted = omits_turn(view, current_id)
        if omitted:
            _nominal_clock(actor, current_id)
        else:
            current.turns_started += 1
            # Mirror only the stored start-of-turn flags, without running
            # callbacks, decisions, saves, or gaining new capabilities.
            current.turn_flags = {key: value for key, value in current.turn_flags.items()
                                  if '_round_' in key or key.startswith('once_per_round:')}
        if boundary('START_OF_TURN'):
            return _Deadline(tuple(budgets), tuple(states))
        if current_id == actor_id and not omitted:
            # No future Dash or recast is assumed.  Native Fly Speed after that
            # boundary's expirations is the allowance for its next own turn.
            allowance = profile(view, actor).speed_ft
            budgets.append(allowance)
            if allowance > 0:
                states.append(view.state.model_copy(deep=True))
        if boundary('END_OF_TURN'):
            return _Deadline(tuple(budgets), tuple(states))
    return None


def _descent_steps(view, actor, prefix, *, epochs=()):
    """Quote one explicit path to support with the native path validator.

    Only a vertical extension is proposed; geometry, fear, creature passage,
    terrain, dragging, and payment are all the engine's own answers.  This is
    a known route, not a claim to have found the globally shortest landing.
    """
    from .falling import supported
    path = list(prefix)
    if not path or path[0] != actor.position:
        return None
    while not supported(view, actor, path[-1]):
        if len(path) > DESCENT_STEP_LIMIT or path[-1].z <= 0:
            return None
        path.append(path[-1].model_copy(update={'z': path[-1].z - 1}))
    if len(path) == 1:
        return ()
    if len(path) - 1 > DESCENT_STEP_LIMIT:
        return None
    costs = _path_steps(view, actor, path)
    if costs is None:
        return None
    from .candidate_knowledge import perceived_ids, query
    permitted = perceived_ids(view)
    for state in epochs:
        projected = copy(view)
        mover = state.actors[actor.entity_id].model_copy(deep=True, update={'position': actor.position})
        projected.state = state.model_copy(update={'actors': {**state.actors, actor.entity_id: mover}})
        _clear_query_memos(projected)
        with query(projected, perceived_actor_ids=permitted):
            future = _path_steps(projected, mover, path)
        if future is None:
            return None
        # Each step must remain affordable when known movement discounts end.
        # The maximum per step is deliberately conservative; it never assumes
        # a current cheap route remains cheap in a later movement allowance.
        costs = tuple(max(now, later) for now, later in zip(costs, future))
    return costs


@pure
def _path_steps(view, actor, path):
    from .granted_movement import native_path_cost
    from .flight import step_cost
    from .falling import required
    # Native whole-path admission keeps the actor at the path origin. Actual
    # flight rechecks local support/capabilities after each committed step. A
    # future landing quote must also survive every waypoint in every epoch.
    safety = _route_safety(view, actor, ((None, path[-1], path, True),))[None]
    if required(view, actor) or any(safety.values()):
        return None
    # A route may pass through a creature without being allowed to stop there.
    # Future turn budgets must never buy such an impossible intermediate stop.
    # Requiring every sampled step to be a legal endpoint is conservative and
    # keeps the bounded packing below independent of future creature movement.
    occupied = view._occupied_volumes_except(actor.entity_id, observed=True)
    footprint = view._footprint(actor)
    if any(not view.grid.volume_legal(position, footprint=footprint, occupied_cells=occupied)
           for position in path[1:]):
        return None
    try:
        cost = native_path_cost(view, actor, tuple(path), mode='fly')
    except ValueError:
        return None  # no asserted route through a blocked or forbidden segment
    costs = tuple(step_cost(view, actor, a, b, mode='fly') for a, b in zip(path, path[1:]))
    if sum(costs) != cost:
        return None
    return costs


def _landing_plan(view, actor, moves, *, epochs=()):
    """Best of at most sixteen native descent quotes, with distinct columns."""
    from .falling import supported
    if supported(view, actor):
        return ()
    plans = []
    direct = _descent_steps(view, actor, (actor.position,), epochs=epochs)
    if direct is not None:
        plans.append(direct)
    def key(candidate):
        floor = candidate.destination.model_copy(update={'z': 0})
        return (candidate.movement_cost_ft + view.grid.distance_ft(candidate.destination, floor),
                bool(candidate.metadata.get('hazard_exposure')), candidate.destination.z,
                candidate.movement_cost_ft, candidate.destination.x, candidate.destination.y,
                candidate.candidate_id)
    columns = {(actor.position.x, actor.position.y)}
    for candidate in sorted(moves, key=key):
        column = (candidate.destination.x, candidate.destination.y)
        if column in columns or not candidate.canonical_path:
            continue
        if len(columns) == DESCENT_ROUTE_LIMIT:
            break
        columns.add(column)
        plan = _descent_steps(view, actor, candidate.canonical_path, epochs=epochs)
        if plan is not None:
            plans.append(plan)
    return min(plans, key=lambda costs: (sum(costs), len(costs), costs), default=None)


def _fits_before_loss(steps, budgets):
    """Unused feet do not carry into the next turn; each native step must fit."""
    if steps is None:
        return False
    index = 0
    for allowance in budgets:
        while index < len(steps) and steps[index] <= allowance:
            allowance -= steps[index]
            index += 1
    return index == len(steps)


def _movement_safety(view, actor, moves):
    """Cheap native support checks for every offered endpoint and fly waypoint."""
    return _route_safety(view, actor, (
        (candidate.candidate_id, candidate.destination, candidate.canonical_path,
         candidate.metadata.get('movement_mode') == 'fly') for candidate in moves))


@pure
def _position_safety(view, actor, flight_start):
    """Share pure inputs only for one unchanged projected creature/position.

    required() already queries flight when support is absent. Its condition
    gates and the explicit departure capability query use the same derived
    zones. Every such answer is keyed by the creature and its square, so the
    caller may change only mover.position between squares of one read frame.
    """
    from .falling import required
    from .flight import profile
    return required(view, actor), profile(view, actor) if flight_start else None


def _route_safety(view, actor, routes):
    """Native local flight safety for offered paths or bounded landing quotes.

    Each row contains a key, endpoint, explicit path and whether it uses flight.
    The 64-position attack budget must not turn unchecked positions into safe
    urgent descents. A route can also enter a flight-suppressing area before
    reaching an otherwise supported endpoint. Query each distinct position
    once, retaining full effect-owner records and the original perception cap.
    No movement callbacks, new conditions, observations or dice are simulated.
    """
    from .candidate_knowledge import perceived_ids, query
    from .space import point
    routes = tuple(routes)
    positions, flight_starts = {}, set()
    for _, destination, path, flying in routes:
        positions[point(destination)] = destination
        if flying:
            for position in path:
                positions[point(position)] = position
            flight_starts.update(point(position) for position in path[:-1])
    checks = {}
    permitted = perceived_ids(view)
    from .read_queries import read_frame
    # One projected engine and one projected creature serve every square: only
    # the position changes. A single read-only frame then shares the facts that
    # do not depend on the square (condition rows, flight grants, Speed hooks
    # that read no position) while every position-keyed answer stays its own.
    projected = copy(view)
    # _position_safety only reads the projected creature (support, Speed, flight
    # capability), so a shallow copy is enough and never shares mutable state.
    mover = actor.model_copy()
    with read_frame(projected), query(projected, perceived_actor_ids=permitted):
        for key, position in sorted(positions.items()):
            mover.position = position
            projected.state = view.state.model_copy(update={'actors': {**view.state.actors, actor.entity_id: mover}})
            checks[key] = _position_safety(projected, mover, key in flight_starts)
    out = {}
    for key, destination, path, flying in routes:
        path_fall = flying and any(checks[point(position)][0] for position in path[1:])
        blocked = flying and any(not checks[point(previous)][1].speed_ft
                                 or (endpoint.z > previous.z
                                     and not checks[point(previous)][1].can_ascend)
                                 for previous, endpoint in zip(path, path[1:]))
        out[key] = {'fall_required': checks[point(destination)][0],
                    'path_requires_fall': path_fall, 'path_blocked': blocked}
    return out


def _geometric(view, actor, position, foes, own_attacks, enemy_attacks,
               own_limits=None, enemy_limits=None):
    """Cheap native volume/reach facts used to bound the expensive sight work.

    Reach/range limits depend on the creature and weapon, not on the square
    being priced, so the caller computes them once for all destinations.
    """
    from .attack_reach import maximum
    from .falling import supported
    distances = {foe.entity_id: view._distance_actor_to_actor(actor, foe, actor_position=position)
                 for foe in foes}
    if own_limits is None:
        own_limits = tuple(maximum(view, actor, action) for action in own_attacks)
    if enemy_limits is None:
        enemy_limits = {foe.entity_id: tuple(maximum(view, foe, action)
                                             for action in enemy_attacks[foe.entity_id])
                        for foe in foes}
    in_reach = any(limit is None or distance <= limit
                   for distance in distances.values() for limit in own_limits)
    threats = sum(any(limit is None or distances[foe.entity_id] <= limit
                      for limit in enemy_limits[foe.entity_id])
                  for foe in foes)
    return {'altitude_ft': position.z * view.grid.square_size_ft,
            'supported': supported(view, actor, position),
            'evaluated': False,
            'nearest_hostile_ft': min(distances.values(), default=None),
            'distances_ft': distances,
            'attack_target_ids': [], 'ranged_target_ids': [], 'melee_threat_ids': [],
            'safe_attack': False,
            '_in_reach': in_reach, '_threats': threats}


def _selected_moves(rows, facts, *, ending):
    """At most 64 exact endpoints, retaining landing and altitude diversity.

    Cheap range tests use native complete-volume geometry; they grant no safe
    attack credit.  All ordering is integer/coordinate/ID based, never a die.
    """
    def key(candidate):
        row = facts[candidate.candidate_id]
        risk = bool(candidate.metadata.get('hazard_exposure'))
        reactions = len(candidate.metadata.get('reaction_exposure') or ())
        return (not (row['_in_reach'] and row['_threats'] == 0), not row['_in_reach'],
                row['_threats'], risk, reactions, candidate.destination.z,
                candidate.movement_cost_ft, row['nearest_hostile_ft'] or 0,
                candidate.destination.x, candidate.destination.y, candidate.candidate_id)

    selected = {}
    ranked = sorted(rows, key=key)
    # First reserve low-risk supported endpoints before tactical preferences.
    if ending:
        landings = sorted((c for c in rows if facts[c.candidate_id]['supported']),
                          key=lambda c: (bool(c.metadata.get('hazard_exposure')),
                                         len(c.metadata.get('reaction_exposure') or ()),
                                         c.movement_cost_ft, c.destination.z, c.destination.x,
                                         c.destination.y, c.candidate_id))
        for candidate in landings[:8]:
            selected[candidate.candidate_id] = candidate
    levels = {}
    for candidate in ranked:
        levels.setdefault(candidate.destination.z, candidate)
    for level in sorted(levels)[:16]:
        candidate = levels[level]
        selected[candidate.candidate_id] = candidate
    for candidate in ranked:
        if len(selected) == POSITION_LIMIT:
            break
        selected[candidate.candidate_id] = candidate
    return tuple(selected.values())


@pure
def _assess(view, actor, foes, own_attacks, enemy_attacks, basic):
    """Exact prospective native attacks plus perceived melee threat geometry."""
    from . import ext
    from .attack_reach import melee
    from .falling import required
    from .target_knowledge import can_see, knowledge
    from .targeting import in_range, reason
    from .shot_geometry import scope
    visible_ids = {foe.entity_id for foe in foes if can_see(view, actor, foe)}
    attack_ids, ranged_ids = set(), set()
    for action in own_attacks:
        # Native generation includes current economy, price, stance, weapon and
        # recipient rules; no made-up geometry or free future action is offered.
        for candidate in view._action_candidates(actor, action):
            targets = visible_ids.intersection(candidate.target_ids)
            if not targets or ext.any_false('candidate_allowed', view, actor, candidate, action):
                continue
            if ext.any_false('ai_candidate_allowed', view, actor, candidate, action):
                continue
            attack_ids.update(targets)
            if not melee(action):
                ranged_ids.update(targets)
    threats = []
    for foe in foes:
        for action in enemy_attacks[foe.entity_id]:
            with scope(view, foe, action):
                known = knowledge(view, foe, actor, action)
                if (known is not None and known.position == actor.position
                        and reason(view, foe, actor, action) is None
                        and in_range(view, foe, actor, action)):
                    threats.append(foe.entity_id)
                    break
    fall_required = required(view, actor)
    route_risk = bool(basic.get('path_requires_fall') or basic.get('path_blocked'))
    return {**basic, 'evaluated': True, 'fall_required': fall_required,
            'attack_target_ids': sorted(attack_ids), 'ranged_target_ids': sorted(ranged_ids),
            'melee_threat_ids': sorted(threats),
            'safe_attack': bool(attack_ids) and not threats and not fall_required and not route_risk}


def annotate(engine, candidates, actor_id, known_actors):
    """Attach optional flight_tactics dictionaries to detached AI candidates.

    Every assessment supplies native distances, altitude and terrain support.
    Up to POSITION_LIMIT move endpoints plus the current position are evaluated
    for actual attack geometry.  Unevaluated rows explicitly receive no safe
    attack credit.  No capability, timer, or current location of an unperceived
    enemy is read into the annotation.  Supported roofs alone are not flight.
    """
    if not ordinary_turn(candidates):
        return candidates
    from .flight import profile
    from .falling import supported
    from .target_knowledge import knowledge
    actor = engine.state.actors[actor_id]
    capability = profile(engine, actor)
    current = [other for other in known_actors if other.entity_id == actor_id
               or relation(engine, actor, other) == ALLY
               or ((known := knowledge(engine, actor, engine.state.actors[other.entity_id])) is not None
                   and known.mode == 'DIRECT')]
    foes = tuple(sorted((other for other in current if other.active and relation(engine, actor, other) == ENEMY),
                        key=lambda other: other.entity_id))
    if (not capability.speed_ft and supported(engine, actor)
            and not any(other.position.z and not supported(engine, other) for other in foes)):
        return candidates
    view = _query_copy(engine)
    # Retain full source records for ongoing effects, while an explicit native
    # knowledge scope freezes which bodies can enter prospective geometry.
    # A move may lose sight of a known foe, but cannot discover an unknown one
    # until its real execution records the new observation.
    from .candidate_knowledge import query
    ids = frozenset(other.entity_id for other in current)
    with query(view, perceived_actor_ids=ids):
        return _annotate_view(view, engine, candidates, actor_id, foes, capability, ids)


def _annotate_view(view, engine, candidates, actor_id, foes, capability, ids):
    from .candidate_knowledge import query
    from .flight import remaining
    from .falling import supported, required
    actor = view.state.actors[actor_id]
    foes = tuple(view.state.actors[other.entity_id] for other in foes)
    own_attacks = _attacks(view, actor, own=True)
    enemy_attacks = {foe.entity_id: _attacks(view, foe, own=False) for foe in foes}
    moves = [candidate for candidate in candidates
             if candidate.kind == CandidateKind.MOVE and candidate.destination is not None]
    from .attack_reach import maximum
    own_limits = tuple(maximum(view, actor, action) for action in own_attacks)
    enemy_limits = {foe.entity_id: tuple(maximum(view, foe, action)
                                         for action in enemy_attacks[foe.entity_id])
                    for foe in foes}
    safety = _movement_safety(view, actor, moves)
    facts = {candidate.candidate_id: {
                 **_geometric(view, actor, candidate.destination, foes, own_attacks, enemy_attacks,
                              own_limits=own_limits, enemy_limits=enemy_limits),
                 **safety[candidate.candidate_id]}
             for candidate in moves}
    air = actor.position if not supported(view, actor) else None
    if air is None:
        for candidate in sorted(moves, key=lambda c: (c.destination.z, c.candidate_id)):
            if facts[candidate.candidate_id]['supported']:
                continue
            projected, mover = _at(view, actor_id, candidate)
            with query(projected, perceived_actor_ids=ids):
                if not required(projected, mover):
                    air = candidate.destination
                    break
    deadline = _flight_deadline(engine, actor_id, air, ids) if air is not None else None
    budgets = deadline.movement_ft if deadline is not None else None
    epochs = deadline.states if deadline is not None else ()
    plan = _landing_plan(view, actor, moves, epochs=epochs) if budgets is not None else None
    ending = budgets is not None and (not budgets or not _fits_before_loss(plan, budgets))
    basic = _geometric(view, actor, actor.position, foes, own_attacks, enemy_attacks,
                       own_limits=own_limits, enemy_limits=enemy_limits)
    here = _assess(view, actor, foes, own_attacks, enemy_attacks, basic)
    for candidate in _selected_moves(moves, facts, ending=ending):
        projected, mover = _at(view, actor_id, candidate)
        with query(projected, perceived_actor_ids=ids):
            facts[candidate.candidate_id] = _assess(projected, mover, foes, own_attacks,
                                                   enemy_attacks, facts[candidate.candidate_id])
            if budgets is not None:
                descent = _descent_steps(projected, mover, (mover.position,), epochs=epochs)
                risk = not _fits_before_loss(descent, (remaining(projected, mover, 'fly'), *budgets))
                facts[candidate.candidate_id]['expiry_risk'] = risk
                if risk:
                    facts[candidate.candidate_id]['safe_attack'] = False
    def public(row):
        return {key: value for key, value in row.items() if not key.startswith('_')}
    common = {'can_fly': capability.speed_ft > 0, 'flight_ending': ending, 'current': public(here)}
    if budgets is not None:
        common.update(landing_cost_ft=sum(plan) if plan is not None else None,
                      future_movement_ft=list(budgets))
    return tuple(candidate.model_copy(update={'metadata': {
        **candidate.metadata, METADATA_KEY: {
            **common, **({'destination': public(facts[candidate.candidate_id])}
                         if candidate.candidate_id in facts else {})}}})
                 for candidate in candidates)
