"""Native delivery of an acquired action when another feature grants its economy.

Used by composite configurations and other source-owned free deliveries. Only
economy is waived: the isolated native candidate pipeline retains costs, use,
condition, target and plug-in gates. No catalogue, actor or method is patched.
Resolution uses the ordinary action/interception/completion path and owns a
fresh activation cache. The caller owns the grant's eligibility and limit.
"""
from copy import deepcopy
from .gate2_runtime_models import EconomyKind


def without_economy(action):
    """Grant a paid turn action without losing its native activation permission.

    NONE alone is not permission to activate. Promote only an originally paid
    Action/Bonus Action; existing free selectors and trigger-only profiles keep
    their own permission. The returned parameters are detached from the catalog.
    """
    parameters = dict(action.parameters)
    if action.economy in (EconomyKind.ACTION, EconomyKind.BONUS_ACTION):
        parameters['free_primary'] = True
    return action.model_copy(update={'economy': EconomyKind.NONE, 'parameters': parameters})


def candidates(engine, actor, action, *, origin=None):
    if action.owner_id != actor.entity_id or action.source_definition_id not in actor.action_ids:
        return []
    shadow = deepcopy(engine)
    granted = without_economy(action)
    shadow.action_catalog[action.source_definition_id] = granted
    from contextlib import nullcontext
    from .candidate_knowledge import query
    from .ext import ai_controlled
    with query(shadow) if ai_controlled(engine, actor) else nullcontext():
        result = shadow.action_candidates_for_sources((action.source_definition_id,))
    return [c for c in result if (c.metadata.get('effect_origin') or {}).get('id') ==
            (origin or {}).get('id')]


def resolve(engine, actor, action, candidate, intent, *, origin=None):
    from . import ext
    from .technique_interception import activation
    legal = candidates(engine, actor, action, origin=origin)
    selected = next((c for c in legal if c.target_ids == candidate.target_ids
                     and c.destination == candidate.destination
                     and c.option_ids == candidate.option_ids), None)
    if selected is None:
        raise ValueError('This granted feature no longer has that legal target or use.')
    granted = without_economy(action)
    try:
        with activation(engine, actor, granted, selected, intent) as (declared, chosen, canceled):
            if canceled:
                return False
            completed = engine._resolve_action(actor, declared, chosen, intent) is not False
            if completed:
                engine._run_final_riders('resolution_final', engine, actor, declared, chosen, intent)
            return completed
    finally:
        ext.run('activation_end', engine, actor, action, selected, intent)
