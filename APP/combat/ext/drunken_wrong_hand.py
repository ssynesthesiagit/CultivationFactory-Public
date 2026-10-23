"""Wrong-Hand Strike: sealed ability options, chosen for one Broken-Rhythm attack.

Compile-time ownership and weapon properties opt in. Runtime edits a private
copy of the prepared strike specification only; the saved action catalog and weapon stay immutable.
"""
import copy
from . import hook, note

WRONG_HAND = 'TAL_DRUNKEN_STYLE_WRONG_HAND_STRIKE'
BROKEN = 'TAL_DRUNKEN_STYLE_BROKEN_RHYTHM_STRIKE'
BLOCK = 'drunken_wrong_hand'


@hook('compile_block')
def wrong_hand_owner(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK}]


@hook('compile_action')
def wrong_hand_options(action, info):
    if WRONG_HAND not in info['owned_ids']:
        return
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') != BROKEN or not typed.get('weapon'):
        return
    weapon = typed['weapon']
    properties = {p.strip().lower() for p in str(weapon.get('properties') or '').split(',')}
    if 'heavy' in properties:
        return
    original = str(weapon.get('ability') or 'STR').upper()
    from .attack_abilities import option_scopes
    kind = 'unarmed' if any(e.get('attack_kind') == 'unarmed' for e in typed.get('effects') or []) else 'weapon'
    ordinary, _ = option_scopes(['STR'], {**info, 'kind': kind,
        'source': weapon.get('implement_id') or weapon.get('natural_source') or typed.get('maneuver_of') or typed['source']})
    ordinary = list(dict.fromkeys([*ordinary, original]))
    allowed = list(dict.fromkeys(['STR', 'DEX', *ordinary]))
    options = {a: int(info['mods'].get(a, 0)) for a in allowed}
    original_mod = int(weapon.get('ability_modifier', options.get(original, 0)))
    changed = copy.deepcopy(typed)
    changed[BLOCK] = {'options': options, 'ordinary': ordinary, 'original': original, 'original_mod': original_mod,
                     'fixed_unarmed': 'fixed_damage' in weapon and any(e.get('attack_kind') == 'unarmed' for e in typed.get('effects') or [])}
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': changed}})


@hook('attack_spec_choice')
def wrong_hand_choice(ctx, target, attack, spec, attack_index):
    from .needle import CHOICE, ask, checkpoint_id
    from .choice_prompt import action_context
    from .trigger_occurrence import current_strike
    held = ctx.typed.get(BLOCK)
    if not held or not ctx.typed.get('weapon'):
        return
    from .attack_abilities import strike_options, strike_attack_only_options, select_strike_ability
    options = dict(held['options'])
    names = {'STR': 'Strength', 'DEX': 'Dexterity', 'CON': 'Constitution', 'INT': 'Intelligence',
             'WIS': 'Wisdom', 'CHA': 'Charisma'}
    # Older sealed opt-in bundles have no ordinary list. Weapon properties and
    # their original ability retain the ordinary options without rewriting saves.
    properties = {p.strip().lower() for p in str(ctx.typed['weapon'].get('properties') or '').split(',')}
    ordinary = held.get('ordinary', ['STR', *(['DEX'] if 'finesse' in properties else []), held['original']])
    extra = strike_options(ctx, {a: options[a] for a in ordinary if a in options})
    ordinary = list(extra)
    options.update(extra)
    attack_only = strike_attack_only_options(ctx)
    if set(attack_only) & set(options):
        raise ValueError('attack-only option conflicts with ordinary ability')
    ordinary.extend(attack_only)
    options.update({key: value['modifier'] for key, value in attack_only.items()})
    names.update({key: value['label'] for key, value in attack_only.items()})
    original_modifier = int(ctx.typed['weapon'].get('ability_modifier', held['original_mod']))
    labels = {}
    for ability, value in options.items():
        scope = (f"for this attack only ({value:+d} ability modifier); damage keeps "
                 f"{names.get(held['original'], held['original'])} ({original_modifier:+d})"
                 if ability in attack_only else f"for this attack and its damage ({value:+d} ability modifier)")
        labels[ability] = f"Use {names.get(ability,ability)} {scope}; " + (
            'ordinary ability choice' if ability in ordinary else 'uses your Drunken Style talent for this attack')
    best = max(options, key=lambda a: options[a])
    count = int(attack.get('count') or 1)
    which = f' (attack {attack_index} of {count})' if count > 1 else ''
    context = action_context(ctx.engine, ctx.actor, ctx.source, target, action=ctx.action)
    context['cost'] = 'No additional Action or resource cost. Only an ability unavailable normally uses your one Drunken Style talent for this attack.'
    chosen = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, BLOCK, ctx.actor.entity_id, target.entity_id, attack_index),
        ctx.actor, CHOICE+BLOCK, list(options), name='Wrong-Hand Strike', target_id=target.entity_id,
        preferred=[best], allow_decline=False,
        labels=labels,
        prompt=f'Wrong-Hand Strike: choose the ability for {ctx.action.display_name}{which} against {target.display_name}.',
        prompt_context=context)[0]
    frame = current_strike(ctx.engine)
    if frame is not None:
        frame['scratch']['drunken_style_attack_talent'] = chosen not in ordinary
    select_strike_ability(ctx, spec, chosen, options[chosen], fixed_unarmed=held.get('fixed_unarmed', False),
                          original_modifier=held['original_mod'],
                          damage_modifier=original_modifier if chosen in attack_only else None)
    scope = (f"; damage keeps {names.get(held['original'],held['original'])}" if chosen in attack_only else ' and its damage')
    note(ctx.engine, ctx.source, ctx.actor, f'Wrong-Hand Strike uses {names.get(chosen,chosen)} for {ctx.action.display_name}{which}{scope}.', (target,))
