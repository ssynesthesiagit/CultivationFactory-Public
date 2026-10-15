"""Brute's damage-free Disarm; Overrun/Shove Aside keep their existing provider.

Uses the shared attack-slot budget, scoped native d20/check engine and the exact
held-possession drop adapter. The defender owns the skill choice; the attacker
owns the item choice. No ability rule is placed in the core resolver.
"""
from copy import deepcopy
from . import hook, effect

SOURCE = 'BRUTE_BASE_BRUTE_MANEUVERS'


def owned(info):
    return SOURCE in info.get('owned_ids', ()) or 'tianxia.sphere.brute' in info.get('spheres', ())


def disarm(action):
    typed = deepcopy(action.parameters.get('typed') or {})
    typed.update(source=SOURCE, effects=[{'type': 'brute_disarm_contest'}], manual_inline_choice=True)
    return action.model_copy(update={'display_name': 'Disarm (' + action.display_name.removesuffix(' attack')
        .removesuffix(': Disarm') + ')', 'costs': (), 'parameters': {
            **action.parameters, 'typed': typed, 'replaces_attack': 1, 'expected_damage': 0}})


@hook('compile_actions')
def compile_maneuvers(info):
    if not owned(info):
        return None
    from .weapon_actions import weapon_attacks
    from ..gate2_runtime_models import EconomyKind
    from .special_attacks import REST
    actions, existing = [], {a.source_definition_id for a in info['actions']}
    for action, typed, attack, kind in weapon_attacks(info['actions'], info['actor_id']):
        if not typed.get('weapon'):
            continue
        ident = action.source_definition_id + '#disarm'
        variant = disarm(action).model_copy(update={'source_definition_id': ident})
        if ident not in existing:
            actions.append(variant)
        follow = deepcopy(variant.parameters)
        follow[REST] = True
        actions.append(variant.model_copy(update={'source_definition_id': ident + '.remaining',
            'economy': EconomyKind.NONE, 'parameters': follow,
            'display_name': variant.display_name + ' (remaining attack)'}))
    return actions


@hook('compile_action')
def replace_weapon_disarm(action, info):
    if SOURCE not in info.get('owned_ids', ()):
        return action
    if action.source_definition_id.endswith('#disarm'):
        return disarm(action)
    return action


@hook('candidate_allowed')
def held_target(engine, actor, candidate, action):
    typed = (action.parameters.get('typed') or {}) if action else {}
    if not any(e.get('type') == 'brute_disarm_contest' for e in typed.get('effects', ())):
        return None
    from .scoundrel_riders import held_possessions
    return bool(candidate.target_ids) and all(held_possessions(engine, engine.state.actors[tid])
                                             for tid in candidate.target_ids)


@effect('brute_disarm_contest', harmful=True)
def contest(ctx, effect):
    from .scoundrel_riders import held_possessions, drop_held_object
    from .hand_occupancy import occupancy
    from .needle import ask, CHOICE, checkpoint_id
    from ..ability_checks import skill_bonus
    from ..dynamic_size import CATEGORIES, current_category
    from ..ext.ability_source import combine_modes
    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    items = {str(item['object']): item for item in held_possessions(engine, target)}
    if not items:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'brute_disarm_item', target.entity_id), actor,
        CHOICE + 'brute_disarm_item', list(items), labels={k: str(v['name']) for k, v in items.items()},
        name='Disarm: choose the held item', target_id=target.entity_id,
        prompt=f'Disarm: choose one item held by {target.display_name}. This replaces one attack and deals no damage.')
    if not picked:
        return
    item = items[picked[0]]
    bonuses = {'STR': skill_bonus(engine, target, 'Athletics', (target.strength_score - 10) // 2),
               'DEX': skill_bonus(engine, target, 'Acrobatics', (target.dexterity_score - 10) // 2)}
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, 'brute_disarm_skill', target.entity_id), target,
        CHOICE + 'brute_disarm_skill', ['STR', 'DEX'],
        labels={'STR': f'Strength (Athletics) {bonuses["STR"]:+d}',
                'DEX': f'Dexterity (Acrobatics) {bonuses["DEX"]:+d}'},
        preferred=sorted(bonuses, key=lambda a: -bonuses[a]), name='Resist Disarm', target_id=target.entity_id,
        prompt=f'{actor.display_name} tries to disarm {target.display_name}. Choose the defending skill.')
    ability = chosen[0] if chosen else max(bonuses, key=bonuses.get)
    skill = 'Athletics' if ability == 'STR' else 'Acrobatics'
    mine = {engine._attack_mode(actor, target)} - {'NORMAL'}
    occupant = 'weapon:' + str(item.get('weapon_action')) if item.get('weapon_action') else 'shield:' + str(item['key'])
    hands = sum(occupant in occupants or 'object:' + str(item['key']) in occupants
                for part, occupants in occupancy(engine, target).items() if part.startswith('hand:'))
    if hands >= 2:
        mine.add('DISADVANTAGE')
    larger = CATEGORIES.index(current_category(engine, target)) - CATEGORIES.index(current_category(engine, actor))
    with engine.d20_scope({'kind': 'attack', 'actor_id': actor.entity_id, 'target_id': target.entity_id,
                          'source_id': ctx.source, 'source_actor_id': actor.entity_id}):
        attack = engine.roller.d20(modifier=int(ctx.numbers.get('attack_bonus', 0)), actor_id=actor.entity_id,
            reason='ATTACK:' + ctx.source + ':DISARM', mode=combine_modes(mine))
    engine._record_roll(attack)
    total = attack.total + engine._consume_attack_modifiers(actor)
    defense = engine.roll_check(modifier=bonuses[ability], actor_id=target.entity_id,
        reason='CHECK:' + ctx.source + ':DISARM', ability=ability, skill=skill,
        modes=('ADVANTAGE',) if larger > 0 else ('DISADVANTAGE',) if larger < 0 else (), against_creature=actor)
    engine._record_roll(defense)
    won = total > defense.total
    engine._append_event('CHECK_ROLLED', ctx.source, actor_id=actor.entity_id,
        target_ids=(target.entity_id,), payload={'actor': attack.model_dump(mode='json'),
            'target': defense.model_dump(mode='json'), 'target_skill': skill, 'skill': None,
            'success': won, 'modified_total': total, 'item': picked[0], 'maneuver': 'Disarm'})
    if won:
        drop_held_object(engine, target, item, source=ctx.source, by=actor)
