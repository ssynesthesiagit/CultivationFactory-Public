"""Burden the Blade: consent before damage, exact-hit B/P/S resistance and
same-weapon follow-up. Uses the existing hit_response, damage_defenses,
attack_mode and attack_roll_finished contracts. No core patch or global defense.
The recorded grant matches the confirmed attack roll, including its rider packets;
independent damage cannot borrow it. Stored metadata is integer/string only.
"""
from typing import Any
from . import hook

BLOCK = 'elements_earth_burden_the_blade'
FEATURE = 'TAL_EARTH_BURDEN_THE_BLADE'
PROTECT = 'condition:typed.earth_blade_protection'
HEAVY = 'condition:typed.earth_blade_heavy'


@hook('compile_block')
def _compile_block(block, spec, row, numbers):
    return [row] if block == BLOCK else None


def _weapon(engine, typed, source, parameters):
    """Share delivery ancestry while preserving historical unarmed identities."""
    from ..weapon_delivery import weapon_identity

    weapon = (typed or {}).get('weapon') or {}
    action = engine.action_catalog.get(source.split('+')[0])
    parameters = parameters or (action.parameters if action is not None else {})
    base = weapon_identity(engine, source.split('+')[0], typed or {}, parameters)
    unarmed = (parameters or {}).get('attack_kind') == 'unarmed' or any(
        e.get('type') == 'attack' and e.get('attack_kind') == 'unarmed'
        for e in (typed or {}).get('effects') or [] if isinstance(e, dict))
    if base and not unarmed:
        return base
    return str(weapon.get('item_id') or weapon.get('implement_id') or weapon.get('weapon_id')
               or weapon.get('name') or source.split('+')[0])


def _matches_weapon(stored, engine, typed, source, parameters):
    """Read both historical Blade encodings without rewriting saved conditions.

    Pre-change compiled attacks stored their action source, possibly a variant.
    The intervening implementation stored catalogue IDs; those records cannot
    recover a physical-copy distinction that was never saved.
    """
    weapon = (typed or {}).get('weapon') or {}
    key = _weapon(engine, typed, source, parameters)
    historical = engine.action_catalog.get(stored.split('+')[0]) if isinstance(stored, str) else None
    historical_key = (_weapon(engine, historical.parameters.get('typed'),
                              historical.source_definition_id, historical.parameters)
                      if historical is not None else None)
    legacy = str(weapon.get('item_id') or weapon.get('weapon_id')
                 or weapon.get('name') or source.split('+')[0])
    return (stored == key or stored == legacy or historical_key == key
            or (isinstance(stored, str) and stored.startswith('action:typed.')
                and stored.split('+')[0].split('#')[0] == key)
            or (bool(weapon.get('implement_id')) and stored == weapon['implement_id']))


@hook('hit_response')
def burden_the_blade(engine, attacker, target, spec, total, natural, effective_ac):
    from .attack_scope import current
    from .needle import ask, checkpoint_id, CHOICE
    from .effect_durations import token
    from ..typed_executor import bears_mark, mark_condition_id
    from .placed import note

    frame = current(engine)
    typed = spec.get('typed') or {}
    kind = (spec.get('parameters') or {}).get('attack_kind')
    if frame is None or not frame['roll_id'] or kind not in ('weapon', 'unarmed'):
        return
    for owner in engine.state.actors.values():
        owned = any(r.get('block') == BLOCK for r in engine.typed_passive_rows.get(owner.entity_id, []))
        if not owner.active or not owned or not bears_mark(attacker, owner.entity_id, 'Burden Mark'):
            continue
        if owner.turn_flags.get('_round_earth_response') == engine.state.round_number:
            continue
        picked = ask(engine, engine._active_intent,
            checkpoint_id(engine, 'burden_blade', owner.entity_id, frame['roll_id']), owner,
            CHOICE + 'burden_blade', ['SPEND'], labels={'SPEND': 'Spend Burden Mark'},
            allow_decline=True, target_id=attacker.entity_id,
            name='Burden the Blade', prompt=f'Burden the Blade: {attacker.display_name} hits {target.display_name}. '
            'Spend your Burden Mark (the Earth weight on the attacker), with no Action or Cultivation Point cost, '
            'to halve this hit’s bludgeoning, piercing and slashing damage? Its next attack with the same weapon '
            'or limb has disadvantage before the end of its next turn. This uses your once-per-round Earth Response.')
        if not picked:
            continue
        owner.turn_flags['_round_earth_response'] = engine.state.round_number
        owner.turn_flags['earth_spent_round'] = engine.state.round_number
        from .earth_responses import spend_mark
        spend_mark(engine, owner, attacker, FEATURE)
        engine._apply_condition(target, PROTECT, FEATURE, owner.entity_id, expires_on='END_OF_CURRENT_TURN',
            data={'roll_id': frame['roll_id'], 'attacker': attacker.entity_id,
                  'label': 'Burden the Blade: this hit’s bludgeoning, piercing and slashing damage is halved'})
        engine._apply_condition(attacker, HEAVY, FEATURE, owner.entity_id,
            expires_on=token('end', attacker.entity_id, attacker.turns_started + 1),
            data={'weapon': _weapon(engine, typed, frame['source'], frame['context'].action.parameters),
                  'except_roll': frame['roll_id'],
                  'label': 'Burden the Blade: next attack with this weapon or limb has disadvantage'})
        note(engine, FEATURE, owner, f'Burden the Blade: {owner.display_name} spends the mark on '
             f'{attacker.display_name} to protect {target.display_name} from this hit.', [target])
        break


@hook('damage_defenses')
def blade_resistance(engine, target, damage_type, typed, source_actor_id):
    packet = engine.damage_context()
    if packet is None or str(damage_type).upper() not in ('BLUDGEONING', 'PIERCING', 'SLASHING'):
        return
    if any(c.condition_id == PROTECT and c.data.get('roll_id') == packet.roll_id
           and c.data.get('attacker') == packet.attacker_id for c in target.conditions.values()):
        return [{'kind': 'resistance', 'damage_types': [str(damage_type).upper()]}]


@hook('attack_mode')
def heavy_weapon(ctx, target):
    if any(c.condition_id == HEAVY and _matches_weapon(c.data.get('weapon'), ctx.engine, ctx.typed, ctx.source, ctx.action.parameters)
           for c in ctx.actor.conditions.values()):
        return 'DISADVANTAGE'


@hook('attack_roll_finished')
def finish_blade_roll(ctx, target, effect, roll_id):
    """Take off what this attack resolved.

    The halved hit's protection belongs to the roll that dealt it, whichever creature holds it, so it is
    cleaned up for the attacker and the defender. The heavy penalty is spent by the attack it names:
    ``attack_mode`` only ever offers it to its holder, so it is spent for ``ctx.actor`` alone and a
    defender that happens to carry the same weapon keeps its pending disadvantage until it swings it."""
    from .condition_ownership import remove_instance

    for holder in (ctx.actor, target):
        for iid, held in list(holder.conditions.items()):
            protects = held.condition_id == PROTECT and held.data.get('roll_id') == roll_id
            spent = (holder is ctx.actor and held.condition_id == HEAVY
                     and held.data.get('except_roll') != roll_id
                     and _matches_weapon(held.data.get('weapon'), ctx.engine, ctx.typed, ctx.source, ctx.action.parameters))
            if protects or spent:
                remove_instance(ctx.engine, holder, iid, FEATURE)
