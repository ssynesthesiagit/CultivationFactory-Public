"""Returning Shield Disc through native weapon attacks and journaled equipment.

The controller chooses STR or DEX; range penalties and Attack-action remainder
are native. An in-flight shield grants no bonus or reaction permission; Orbiting
Shield Disc retains its printed exception. No transient Python state is saved.
"""
from contextlib import contextmanager

from . import hook, effect
from .needle import ask, checkpoint_id

DISC = 'TAL_SHIELD_RETURNING_SHIELD_DISC'
SWEEP = 'TAL_SHIELD_CELESTIAL_DISC_SWEEP'
PLACEMENT = 'condition:typed.returning_shield_disc'


@hook('compile_action')
def prepare(action, info):
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != DISC:
        return None
    numbers = {**typed['numbers'], 'shield_disc_mods':
               {key: int(info['mods'].get(key, 0)) for key in ('STR', 'DEX')}}
    cl = int(numbers.get('cl') or 1)
    count = 3 if cl >= 17 else 2 if cl >= 11 else 1
    preferred = max(('STR', 'DEX'), key=lambda key: numbers['shield_disc_mods'][key])
    bonus = numbers['shield_disc_mods'][preferred]
    numbers['attack_bonus'] = bonus + int(info['pb'])
    weapon = {'damage': {'count': count, 'sides': 8, 'modifier': bonus},
              'damage_type': 'BLUDGEONING', 'ability_modifier': bonus, 'properties': 'Thrown', 'melee': False}
    return action.model_copy(update={'target_kind': 'HOSTILE_ENTITY', 'range_ft': 90,
        'parameters': {**action.parameters, 'replaces_attack': 1,
            'expected_damage': count * 4 + max(numbers['shield_disc_mods'].values()),
            'typed': {**typed, 'numbers': numbers, 'weapon': weapon, 'range_ft': 30, 'long_range_ft': 90}}})


def thrown_item_key(engine, actor):
    """One physical Shield, or Guarded Stance's explicitly selected weapon."""
    from .. import armour, carry
    from .shield_wielding import shield_in_hand, orbiting, guarded_weapon
    key = armour.shield_item_key(engine, actor)
    if key and (shield_in_hand(engine, actor) or orbiting(engine, actor)):
        return key
    key = guarded_weapon(engine, actor)
    return key if key and not carry.lost_to_another_hand(actor, key) else None


@hook('candidate_allowed')
def available(engine, actor, candidate, action):
    if action is None or (action.parameters.get('typed') or {}).get('source') not in {DISC, SWEEP}:
        return None
    from .shield_wielding import wielding_a_shield
    return wielding_a_shield(engine, actor) and thrown_item_key(engine, actor) is not None


@hook('effect_resolution_scope')
def throw_scope(ctx, row):
    return in_flight(ctx) if row.get('shield_disc') == 1 or row.get('shield_in_flight') else None


@contextmanager
def in_flight(ctx):
    from .. import armour, carry
    from .shield_wielding import wielding_a_shield

    engine, actor = ctx.engine, ctx.actor
    key = thrown_item_key(engine, actor)
    if key is None or not wielding_a_shield(engine, actor):
        from . import CheckpointError
        raise CheckpointError('This throw requires a wielded Shield.')
    typed = ctx.typed
    if typed.get('source') == DISC:
        mods = ctx.numbers['shield_disc_mods']
        preferred = max(('STR', 'DEX'), key=lambda name: (mods[name], name == 'STR'))
        picked = ask(engine, ctx.intent, checkpoint_id(engine, 'SHIELD_DISC', actor.entity_id), actor,
            'choice:needle.shield_disc_ability', ['STR', 'DEX'], preferred=[preferred],
            labels={name: f'{"Strength" if name == "STR" else "Dexterity"} ({mods[name]:+d})' for name in mods},
            name='Returning Shield Disc', feature_id=DISC, target_id=ctx.target.entity_id if ctx.target else None,
            prompt='Returning Shield Disc: choose Strength or Dexterity for this attack and its damage (one attack of your Attack action).')
        ability = picked[0]
        bonus = mods[ability]
        cl = int(ctx.numbers.get('cl') or 1)
        count = 3 if cl >= 17 else 2 if cl >= 11 else 1
        typed = {**ctx.typed, 'numbers': {**ctx.numbers, 'attack_bonus': bonus + actor.proficiency_bonus},
            'weapon': {'damage': {'count': count, 'sides': 8, 'modifier': bonus},
                       'damage_type': 'BLUDGEONING', 'ability_modifier': bonus, 'properties': 'Thrown',
                       'melee': False}, 'range_ft': 30, 'long_range_ft': 90}
    location = carry.owned_item_location(actor, key)
    carry.clear_owned_item_location(engine, actor, key, ctx.source)
    item = carry.item_of(carry.carrying_of(engine, actor.entity_id), key=key) or {}
    engine._apply_condition(actor, PLACEMENT, ctx.source, actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'item_key': key, 'held_by': actor.entity_id, 'object_location': 'carried',
              **({'disables_action': item['weapon_action']} if item.get('weapon_action') else {}),
              'label': ctx.action.display_name + ': Shield in flight'})
    previous = ctx.typed
    ctx.typed = typed
    try:
        yield
    finally:
        ctx.typed = previous
    carry.clear_owned_item_location(engine, actor, key, ctx.source)
    if location:
        engine._apply_condition(actor, PLACEMENT, ctx.source, actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'item_key': key, 'held_by': actor.entity_id, 'object_location': location,
                  'label': ctx.action.display_name + ': Shield returned to your hand'})


@effect('shield_sweep_rider')
def sweep_rider(ctx, row):
    from ..typed_executor import run_effects
    target = ctx.target
    if target is None or target.team_id == ctx.actor.team_id:
        return
    picked = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, 'SHIELD_SWEEP', ctx.actor.entity_id, target.entity_id), ctx.actor,
        'choice:needle.shield_sweep_rider', ['Prone', 'Push'], preferred=['Prone'],
        name='Celestial-Disc Sweep', feature_id=SWEEP, target_id=target.entity_id,
        labels={'Prone': 'Knock this creature Prone', 'Push': 'Push this creature 15 feet away from the path'},
        prompt=f'Celestial-Disc Sweep: {target.display_name} failed its save. Choose Prone or a 15-foot push away from the path.')
    effect_row = ({'type': 'condition', 'condition': 'prone', 'duration': 'instant', 'applies_to': 'target'}
                  if picked[0] == 'Prone' else {'type': 'directed_forced_movement',
                      'direction_axis': 'area_path', 'distance_ft': 15, 'applies_to': 'target'})
    run_effects(ctx, [effect_row])
