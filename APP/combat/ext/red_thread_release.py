"""Red Thread Auspice's bearer-owned Hit Die Release, without caster payment."""
from . import effect, hook
from .fate_riders import AUSPICE, RED_THREAD
from .hit_dice import available, spend
from .needle import ask, checkpoint_id

ACTION = 'system:combat.red_thread_release'


def held(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == AUSPICE and c.data.get('auspice') == 'red_thread'), None)


@hook('match_start')
def release_action(engine):
    from ..gate2_runtime_models import ActionDefinition
    if not any((a.parameters.get('typed') or {}).get('source') == RED_THREAD for a in engine.action_catalog.values()):
        return
    engine.action_catalog[ACTION] = ActionDefinition(source_definition_id=ACTION, display_name='Red Thread Auspice: Release',
        owner_id='*', economy='NONE', resolution_kind='TYPED', target_kind='SELF',
        parameters={'free_primary': True, 'typed': {'effects': [{'type': 'red_thread_release'}], 'numbers': {}, 'riders': []},
            'description': 'Spend one of your Hit Dice and end your Red Thread Auspice. One chosen ally within 30 feet gains Temporary HP equal to the die result plus the caster’s Fate modifier.'})


@hook('additional_actions')
def offer(engine, actor):
    return [ACTION] if held(actor) and available(actor) and ACTION in engine.action_catalog else []


@hook('candidate_allowed')
def eligible(engine, actor, candidate, action):
    if action is not None and action.source_definition_id == ACTION:
        return bool(held(actor) and available(actor))


@effect('red_thread_release')
def release(ctx, row):
    from ..relations import relation, ALLY
    from ..targeting import line_of_effect
    grant = held(ctx.actor)
    if grant is None:
        return
    # Release says one ally, including the bearer, without requiring sight.
    allies = [a for a in ctx.engine.state.actors.values() if a.active
              and relation(ctx.engine, ctx.actor, a) == ALLY and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 30
              and line_of_effect(ctx.engine, ctx.actor, target=a)]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'red_thread_ally', ctx.actor.entity_id), ctx.actor,
        'choice:needle.red_thread_ally', [a.entity_id for a in allies], name='Red Thread Auspice: Release',
        labels={a.entity_id: a.display_name for a in allies},
        prompt=f'Red Thread Auspice: {ctx.actor.display_name} will spend one Hit Die. Choose an ally within 30 feet to gain Temporary HP; this ends the Auspice.')
    if not chosen:
        return
    dice = available(ctx.actor)
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'red_thread_die', ctx.actor.entity_id), ctx.actor,
        'choice:needle.red_thread_die', list(dice), name='Red Thread Auspice: Release',
        labels={key: f'Spend one d{sides} Hit Die ({ctx.actor.resources[key]} remaining)' for key, sides in dice.items()},
        prompt='Red Thread Auspice: choose the Hit Die to spend for this Release.')
    if not picked:
        return
    source_action = ctx.engine.action_catalog.get(grant.source_definition_id)
    bonus = int(((source_action.parameters.get('typed') or {}).get('numbers') or {}).get('key_mod') or 0) if source_action else 0
    total = max(0, spend(ctx.engine, ctx.actor, picked[0], grant.source_definition_id) + bonus)
    ctx.engine._grant_temp_hp(ctx.engine.state.actors[chosen[0]], total, grant.source_definition_id, ctx.actor.entity_id)
    from .d20_floor import end_auspice
    end_auspice(ctx.engine, ctx.actor, grant, 'RELEASED')
