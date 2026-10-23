"""Read-only legality explanations shared by native checks and Table's rider.

Independent queries run the real candidate pipeline on an isolated copy,
including the Gate4 filters. CombatService observes its existing checked pass
and retains transient explanations alongside the candidate cache. Both use the
same context-local observer; diagnostics never change candidate identity.
"""
from contextvars import ContextVar
from contextlib import contextmanager
from copy import deepcopy
from .read_queries import candidate_pass

_QUERY = ContextVar('action_availability', default=None)


@contextmanager
def observe(engine):
    """Collect refusals during CombatService's existing candidate pass.

    This uses the same observer as an independent query, without replacing any
    engine method or running another candidate pass.
    """
    observations = {source: {} for source in engine.action_catalog}
    token = _QUERY.set(observations)
    try:
        with candidate_pass(engine):
            yield observations
    finally:
        _QUERY.reset(token)


def signature(engine):
    """Bind transient explanations to state, catalogue and control modes.

    CombatService retains these alongside its saved-state candidate cache. Direct
    queries must also reject them after an in-memory state or catalogue edit.
    """
    from .canonical import canonical_sha256
    return canonical_sha256({
        'state': engine.state.model_dump(mode='json'),
        'catalogue': {source: action.model_dump(mode='json')
                      for source, action in engine.action_catalog.items()},
        'control_modes': getattr(engine, 'typed_control_modes', {}),
    })


def remember(engine, candidates, observations):
    """Build a read-only diagnostic frame from the checked menu, never fight state."""
    actor_id = engine.state.current_actor_id
    available = {(c.actor_id, c.source_definition_id) for c in candidates}
    target_available = {(c.actor_id, c.source_definition_id, target_id)
                        for c in candidates for target_id in c.target_ids}
    # A pass that offered discovery headers has not decided availability: its
    # headers are offers to inspect an action, exempt from target and plug-in
    # vetoes. Such a frame is a menu projection, so availability queries must
    # not reuse it (see _candidates).
    discovery = any((candidate.metadata or {}).get('lazy_action') for candidate in candidates)
    frame = (signature(engine), actor_id,
             {source: _answer(engine, actor_id, source, available, observation)
              for source, observation in observations.items()},
             target_available, observations, discovery)
    engine._cf_availability = frame
    return frame


def explaining():
    """True only while an explanation query runs; refusal text is computed then alone."""
    return _QUERY.get() is not None


def deny(source, code, reason, *, stage=0, details=None):
    """Return the usual empty candidate list, recording only an active query.

    Target alternatives precede final candidate filters. If a candidate reaches
    a later stage, report the first refusal there rather than an earlier rejected
    alternative target. This never changes check order or candidate membership.
    """
    observations = _QUERY.get()
    query = observations.get(source) if observations is not None else None
    if query is not None and stage > query.get('stage', -1):
        query.update(stage=stage, result={'available': False, 'code': code, 'reason': reason})
        if details is not None:
            query['result']['details'] = details
    return []


def plugin_denial(point, engine, actor, action, *args, stage=1):
    """Ask only the denied permission's adjacent pure explanatory providers."""
    from . import ext
    query = _QUERY.get()
    if query is None or action is None or action.source_definition_id not in query:
        return
    replies = ext.run_strict(point, engine, actor, *args, action)
    for reply in replies:
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError(f'{point} requires a nonempty player-facing string or None')
    deny(action.source_definition_id, point.upper(), replies[0] if replies else
         'This action has no eligible choice under its current restrictions.', stage=stage)


def cannot_pay(engine, actor, source, totals, *, alternatives_checked=False, stage=0):
    observations = _QUERY.get()
    if observations is None or source not in observations:
        return
    from .resource_labels import exhausted_uses_reason, resource_name
    missing = [(rid, int(amount), actor.resources.get(rid, 0)) for rid, amount in totals.items()
               if actor.resources.get(rid, 0) < int(amount)]
    parts = [f'{amount} {resource_name(rid)} (you have {held})' for rid, amount, held in missing]
    uses = any(rid.startswith('resource:uses.') for rid, _, _ in missing)
    reason = 'Requires ' + ', '.join(parts) + ('; no affordable alternative payment is available.'
                                             if alternatives_checked else ' for this action.')
    if uses:
        reason += ' ' + exhausted_uses_reason() + '.'
    deny(source, 'USE_LIMIT' if uses else 'COST', reason,
         stage=stage, details={'costs': [[rid, amount] for rid, amount in totals.items()]})


def query(engine, actor_id, source_id):
    """Return availability of this exact source in the current decision context."""
    return query_many(engine, actor_id, (source_id,))[source_id]


def query_target(engine, actor_id, source_id, target_id):
    """Explain one exact source/target pair using the isolated candidate pipeline."""
    return query_targets(engine, actor_id, ((source_id, target_id),))[(source_id, target_id)]


def _candidates(engine):
    """One real candidate pass for availability, never a discovery header.

    A lazy menu header is an offer to inspect an action, not a legal execution
    candidate (combat/lazy_menu.py): headers are generated before target,
    destination and plug-in vetoes run, and are exempt from them on purpose.
    Asking "can this action be used now?" inside a lazy projection therefore
    counted headers as availability, so every surface that reads the menu
    (engine legality, the sheet's greyed rows, the table's button reasons, the
    planner) could be told a header was usable while its expansion was refused.
    Availability has one source: this pass, with discovery turned off.
    """
    from .lazy_menu import query as lazy_projection
    with lazy_projection(False):
        return engine.legal_candidates()


def query_targets(engine, actor_id, source_target_pairs):
    """Explain exact source/target pairs in one isolated candidate pass."""
    pairs = tuple(dict.fromkeys((source, target) for source, target in source_target_pairs))
    if not pairs:
        return {}
    # Table state has already checked the complete candidate set to build the
    # active menu. Reuse that exact pass for object-target explanations instead
    # of deep-copying the engine and enumerating every ability a second time.
    # The state/catalogue signature rejects this path after any recorded or
    # in-memory change; standalone callers retain the isolated fallback below.
    frame = getattr(engine, '_cf_availability', None)
    sources = {source for source, _ in pairs}
    if (frame is not None and frame[1] == actor_id
            and all(source in frame[4] for source in sources)
            and not frame[5]
            and frame[0] == signature(engine)):
        return _answer_targets(engine, actor_id, pairs, frame[3], frame[4])

    copied = deepcopy(engine)
    # A legality query cannot request a reaction or reuse live provider closures.
    copied._gate4_reaction_provider = None
    observations = {source_id: {} for source_id, _ in pairs}
    token = _QUERY.set(observations)
    try:
        candidates = _candidates(copied)
    finally:
        _QUERY.reset(token)
    available = {(candidate.actor_id, candidate.source_definition_id, target_id)
                 for candidate in candidates for target_id in candidate.target_ids}
    return _answer_targets(copied, actor_id, pairs, available, observations)


def _answer_targets(engine, actor_id, pairs, available, observations):
    """Apply the shared object-target policy to cached or isolated observations."""
    actor = engine.state.actors.get(actor_id)
    from . import ext
    sources = {source for source, _ in pairs}
    targets_by_source = {}
    for source_id in sources:
        action = engine.action_catalog.get(source_id)
        targets_by_source[source_id] = ({target_id for targets in ext.run('object_targets', engine, actor, action)
                                         for target_id in targets}
                                        if actor is not None and action is not None else set())
    source_wide = {}
    # These restrictions are checked before target enumeration and apply to
    # every target. Other observed refusals may belong to only one object.
    for source_id in sources:
        observation = observations.get(source_id, {})
        result = observation.get('result')
        source_wide[source_id] = (observation if result and result.get('code')
                                  in {'ACTION', 'BONUS_ACTION', 'COST', 'USE_LIMIT'} else {})
    answers = {}
    for source_id, target_id in pairs:
        if target_id not in targets_by_source[source_id]:
            answers[(source_id, target_id)] = {'available': False, 'reason': None, 'code': 'NOT_TARGETED'}
            continue
        target_available = ({(actor_id, source_id)} if (actor_id, source_id, target_id) in available else set())
        answers[(source_id, target_id)] = _answer(
            engine, actor_id, source_id, target_available, source_wide[source_id])
    return answers


def query_many(engine, actor_id, source_ids):
    """Answer independent source queries with one isolated candidate pass.

    Shared by the single-source API and Table's button explanations. Each source
    has its own rejection stage and result. No intent or player decision is
    executed. Refusals are reused only when an observed candidate pass has the exact same state,
    catalogue and control modes. Other callers still get an isolated fresh pass.
    """
    observations = {source: {} for source in source_ids}
    if not observations:
        return {}
    frame = getattr(engine, '_cf_availability', None)
    if (frame is not None and frame[1] == actor_id
            and all(source in frame[2] for source in observations)
            and not frame[5]
            and frame[0] == signature(engine)):
        return {source: deepcopy(frame[2][source]) for source in observations}
    copied = deepcopy(engine)
    # A legality query cannot request a reaction or reuse live provider closures.
    copied._gate4_reaction_provider = None
    token = _QUERY.set(observations)
    try:
        candidates = _candidates(copied)
    finally:
        _QUERY.reset(token)
    available = {(c.actor_id, c.source_definition_id) for c in candidates}
    return {source: _answer(copied, actor_id, source, available, observation)
            for source, observation in observations.items()}


def _answer(copied, actor_id, source_id, available, observation):
    if (actor_id, source_id) in available:
        return {'available': True, 'reason': None}
    def no(code, reason):
        return {'available': False, 'code': code, 'reason': reason}
    state = copied.state
    if state.terminal_result is not None:
        return no('FINISHED', 'The fight has ended.')
    actor = state.actors.get(actor_id)
    if actor is None:
        return no('ACTOR', 'This fighter is not in the fight.')
    if state.setup_tasks:
        return no('SETUP', 'Finish the fight setup choices before taking an action.')
    if state.pending_resolution is not None:
        return no('PENDING', 'Finish the current follow-up choice before taking another action.')
    if state.current_actor_id != actor_id:
        return no('TURN', "Wait for this fighter's turn.")
    if not actor.active or actor.life_state in ('DYING', 'STABLE'):
        return no('INACTIVE', 'This fighter cannot act while inactive or dying.')
    from .typed_executor import condition_rules
    if any(row.get('no_actions') for row in condition_rules(actor)):
        return no('NO_ACTIONS', 'A current condition prevents this fighter from taking actions.')
    if 'result' in observation:
        return deepcopy(observation['result'])
    action = copied.action_catalog.get(source_id)
    shared_action = (action is not None and action.owner_id == '*'
                     and source_id.startswith('system:')
                     and (action.parameters or {}).get('player_only') is True)
    if action is None or source_id not in actor.action_ids and not source_id.startswith('system:combat.') and not shared_action:
        return no('NOT_OWNED', 'This fighter does not have this action.')
    distance = range_reason(copied, actor, action)
    if distance is not None:
        return no('TARGET_RANGE', distance)
    return no('NO_CANDIDATE', 'No eligible target or position is currently available for this action.')


def range_reason(engine, actor, action):
    """Plain text when distance is the only blocker, else None.

    Shared by recipient refusals and the fallback. Only creatures the actor
    currently perceives count, so a remembered but unseen foe never shows up.
    The nearest one is measured the way the attack is: its route when it has
    one, otherwise 3D distance including altitude.
    """
    from .attack_reach import maximum, melee
    from .relations import relation, ALLY, ENEMY
    from .shot_geometry import attack_distance
    from .target_knowledge import knowledge
    kind = action.target_kind
    limit = maximum(engine, actor, action)
    if limit is None:
        return None
    if kind == 'CELL' and (action.parameters or {}).get('any_cell'):
        # Any-cell actions use the same grid, distance and sight checks as the
        # candidate builder. Diagnose only visible, clear squares so this stays
        # a distance-only explanation and never infers hidden occupants.
        from .gate2_runtime_models import Position
        from .senses import perceives_cell
        distances = []
        for y in range(engine.grid.height):
            for x in range(engine.grid.width):
                cell = Position(x=x, y=y)
                if (not perceives_cell(engine, actor, cell)
                        or not engine._line_of_sight_actor_to_cell(actor, cell)):
                    continue
                distance = engine._distance_actor_to_cell(actor, cell)
                if distance <= limit:
                    return None
                distances.append(distance)
        if not distances:
            return None
        nearest = min(distances)
        height = f', counting your {actor.position.z * engine.grid.square_size_ft} ft height' if actor.position.z else ''
        return f'Out of range: the nearest square you can see is {nearest} ft away (range {limit} ft){height}.'
    if kind not in {'HOSTILE_ENTITY', 'HOSTILE_ENTITY_OR_SELF', 'ALLY_OR_SELF', 'ANY_CREATURE'}:
        return None
    def wanted(other):
        if other is actor or not other.active:
            return False
        if kind in {'HOSTILE_ENTITY', 'HOSTILE_ENTITY_OR_SELF'}:
            return relation(engine, other, actor) == ENEMY
        if kind == 'ALLY_OR_SELF':
            return relation(engine, other, actor) == ALLY
        return True
    seen = [other for other in engine.state.actors.values()
            if wanted(other) and (known := knowledge(engine, actor, other, action)) is not None
            and known.mode == 'DIRECT']
    if not seen:
        return None
    nearest = min(attack_distance(engine, actor, other) for other in seen)
    if nearest <= limit:
        return None
    height = f', counting your {actor.position.z * engine.grid.square_size_ft} ft height' if actor.position.z else ''
    if melee(action):
        return f'No target within reach ({limit} ft); the nearest is {nearest} ft away{height}.'
    return f'Out of range: the nearest target you know of is {nearest} ft away (range {limit} ft){height}.'
