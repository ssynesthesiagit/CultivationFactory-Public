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
    frame = (signature(engine), actor_id,
             {source: _answer(engine, actor_id, source, available, observation)
              for source, observation in observations.items()})
    engine._cf_availability = frame
    return frame


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
            and frame[0] == signature(engine)):
        return {source: deepcopy(frame[2][source]) for source in observations}
    copied = deepcopy(engine)
    # A legality query cannot request a reaction or reuse live provider closures.
    copied._gate4_reaction_provider = None
    token = _QUERY.set(observations)
    try:
        candidates = copied.legal_candidates()
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
        return observation['result']
    action = copied.action_catalog.get(source_id)
    if action is None or source_id not in actor.action_ids and not source_id.startswith('system:combat.'):
        return no('NOT_OWNED', 'This fighter does not have this action.')
    return no('NO_CANDIDATE', 'No eligible target or position is currently available for this action.')
