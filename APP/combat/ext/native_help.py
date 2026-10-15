"""Opt-in ordinary Help delivery through native actions and modifiers.

help_actions_enabled is a pure opt-in per fight. No subscriber creates no
catalog row/menu/event in historical fights. Momentum requests this producer;
specialized Help effects use help_policy.delivered after their own delivery.
The printed 2024 Assist an Attack Roll option chooses an ally and an enemy
within five feet; it adds no attack or roll engine.
"""
from . import hook, effect, run_strict

SOURCE = 'system:combat.help_attack'


@hook('match_start')
def install(engine):
    if not any(run_strict('help_actions_enabled', engine)):
        return
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    engine.action_catalog[SOURCE] = ActionDefinition(source_definition_id=SOURCE,
        display_name='Help an ally attack', owner_id='*', economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', reach_ft=5,
        parameters={'expected_damage': 0, 'native_help': 1, 'typed': {
            'effects': [{'type': 'native_help_attack'}], 'numbers': {}, 'riders': [], 'duration': {'kind': 'instant'}},
            'description': 'Action: distract an enemy within 5 feet. Choose an ally; its next attack against that enemy has Advantage before your next turn.'})


def recipients(engine, helper):
    from ..relations import relation, ALLY
    from .help_policy import allowed
    return [a for a in engine.state.actors.values() if a.active and a is not helper
            and relation(engine, helper, a) == ALLY and allowed(engine, helper, a)]


@hook('additional_actions')
def actions(engine, actor):
    return [SOURCE] if SOURCE in engine.action_catalog and recipients(engine, actor) else []


@hook('candidate_allowed')
def eligible(engine, actor, candidate, action):
    if action and action.source_definition_id == SOURCE:
        return bool(recipients(engine, actor)) and all(
            engine._distance_actor_to_actor(actor, engine.state.actors[t]) <= 5 for t in candidate.target_ids)
    return None


@effect('native_help_attack')
def assist(ctx, effect):
    from .needle import ask, checkpoint_id, CHOICE
    from .effect_durations import token
    from .help_policy import delivered
    enemy = ctx.target
    allies = recipients(ctx.engine, ctx.actor)
    if enemy is None or not allies or ctx.engine._distance_actor_to_actor(ctx.actor, enemy) > 5:
        return
    by_id = {a.entity_id: a for a in allies}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, SOURCE, ctx.actor.entity_id, enemy.entity_id),
        ctx.actor, CHOICE + 'help_recipient', list(by_id), labels={a.entity_id: a.display_name for a in allies},
        name='Help an ally attack', prompt=f'Whose next attack against {enemy.display_name} do you aid? Advantage expires at the start of your next turn. Action; no resource cost.')
    if not selected:
        return
    ally = by_id[selected[0]]
    ctx.engine._add_modifier(ally, SOURCE + ':' + ctx.actor.entity_id, 'attack_mode_vs', 'SET',
        'ADVANTAGE:' + enemy.entity_id, 'NEXT_ATTACK',
        expires_on=token('start', ctx.actor.entity_id, int(ctx.actor.turns_started) + 1))
    delivered(ctx.engine, ctx.actor, ally, SOURCE, kind='attack', target_id=enemy.entity_id)
