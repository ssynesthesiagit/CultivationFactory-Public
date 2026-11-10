"""Opt-in shared round allowance for independently compiled action/reaction rows.

response_use stores its named group and actual round in an evented condition.
row_allowed and candidate_allowed read only opted-in rows. No matching row means
no change to historical saved actions. Round numbers, rather than turn expiry,
keep the limit shared across the owner's and other creatures' turns.
"""
from typing import Any
from . import effect, hook
from ..hook_queries import actor_action

CONDITION = 'condition:typed.response_round'


def available(engine: Any, actor: Any, group: str) -> bool:
    return not any(c.condition_id == CONDITION and c.data.get('group') == group
                   and c.data.get('round') == engine.state.round_number for c in actor.conditions.values())


def groups(value: Any):
    if isinstance(value, dict):
        if value.get('type') == 'response_use' and value.get('group'):
            yield value['group']
        for child in value.values():
            yield from groups(child)
    elif isinstance(value, list):
        for child in value:
            yield from groups(child)


def consume(engine: Any, actor: Any, group: str, source: str, name: str = 'Response') -> None:
    """Commit one accepted allowance; callers own admission and other costs."""
    if not available(engine, actor, group):
        raise ValueError('This response has already been used this round')
    from .condition_ownership import remove_instance
    for iid, c in list(actor.conditions.items()):
        if c.condition_id == CONDITION and c.data.get('group') == group:
            remove_instance(engine, actor, iid, source)
    engine._apply_condition(actor, CONDITION, source, actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'group': group, 'round': engine.state.round_number,
              'label': f'{name}: already used this round'})


@effect('response_use')
def use(ctx: Any, row: dict) -> None:
    consume(ctx.engine, ctx.actor, row['group'], ctx.source, row.get('name', 'Response'))


@hook('row_allowed')
def reaction_allowed(engine: Any, actor: Any, row: dict) -> bool | None:
    return False if any(not available(engine, actor, group) for group in groups(row.get('effects') or [])) else None


@hook('candidate_allowed', query_key=actor_action)
def candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return False if any(not available(engine, actor, group) for group in groups(typed.get('effects') or [])) else None


@hook('state_event')
def clear_old_round(engine: Any, event: Any) -> None:
    """Retire stale display trackers when the next actual round begins."""
    if event.event_type != 'ROUND_STARTED':
        return
    from .condition_ownership import remove_instance
    for actor in engine.state.actors.values():
        for iid, c in list(actor.conditions.items()):
            if c.condition_id == CONDITION and c.data.get('round') != engine.state.round_number:
                remove_instance(engine, actor, iid, 'system:response_round.expiry')
