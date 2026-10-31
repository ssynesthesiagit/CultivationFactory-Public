"""Chain Lash's minor link: once on each actual turn, with a scoped next check."""
from typing import Any
from . import effect, hook

LASH = 'TAL_CHAINS_CHAIN_LASH_BASE'
GRANT = 'condition:typed.chains_lash_grapple'
USED = '_round_chains_lash_minor'


def grapple_action(action):
    """Only an explicitly represented grapple attempt, never an escape or Shove."""
    from ..typed_executor import _walk_rows
    return action is not None and any(row.get('type') == 'condition' and row.get('condition') == 'grappled'
        for row in _walk_rows((action.parameters.get('typed') or {}).get('effects')))


@effect('chains_minor_link')
def minor_link(ctx: Any, row: dict) -> None:
    from .ability_source import mechanic_of
    from ..typed_executor import run_effects
    if mechanic_of(ctx.action) != LASH or ctx.target is None:
        return
    stamp = next((e.sequence for e in reversed(ctx.engine.events) if e.event_type == 'TURN_STARTED'), 0)
    if ctx.actor.turn_flags.get(USED) == stamp:
        return
    ctx.actor.turn_flags[USED] = stamp
    if row.get('grapple_check'):
        ctx.engine._apply_condition(ctx.actor, GRANT, ctx.source, ctx.actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN', data={'target_id': ctx.target.entity_id,
                'label': f'Chain Lash: Advantage on your next check to grapple {ctx.target.display_name}'})
    else:
        run_effects(ctx, row.get('effects') or [])


@hook('contest_check_mode')
def grapple_check(ctx: Any, subject: Any, opponent: Any, spec: dict) -> str | None:
    if subject is not ctx.actor or not grapple_action(ctx.action):
        return None
    return 'ADVANTAGE' if any(c.condition_id == GRANT and c.data.get('target_id') == opponent.entity_id
        for c in subject.conditions.values()) else None


@hook('event', nested=True)
def consume_grapple_check(engine: Any, event_type: str, kwargs: dict) -> None:
    if event_type != 'CHECK_ROLLED' or not grapple_action(engine.action_catalog.get(kwargs.get('source_definition_id'))):
        return
    from .roll_context import check_receipts
    from .condition_ownership import remove_instance
    for actor_id, roll in check_receipts(kwargs):
        actor = engine.state.actors.get(actor_id)
        if actor is None:
            continue
        for held in list(actor.conditions.values()):
            if held.condition_id == GRANT and held.data.get('target_id') in (kwargs.get('target_ids') or ()):
                remove_instance(engine, actor, held.instance_id, held.source_definition_id)
