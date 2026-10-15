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
    typed.update(source=SOURCE, effects=[{'type': 'brute_disarm_contest', 'attack_kind': 'weapon'}], manual_inline_choice=True)
    return action.model_copy(update={'display_name': 'Disarm (' + action.display_name.removesuffix(' attack')
        .removesuffix(': Disarm') + ')', 'costs': (), 'parameters': {
            **action.parameters, 'typed': typed, 'replaces_attack': 1, 'expected_damage': 0}})


@hook('compile_actions')
def compile_maneuvers(info):
    if not owned(info):
        return None
    from .weapon_actions import weapon_attacks
    actions, existing = [], {a.source_definition_id for a in info['actions']}
    for action, typed, attack, kind in weapon_attacks(info['actions'], info['actor_id']):
        from ..weapon_delivery import delivery_kind
        if not typed.get('weapon') or delivery_kind(typed, attack, action.parameters) != 'weapon':
            continue
        ident = action.source_definition_id + '#disarm'
        variant = disarm(action).model_copy(update={'source_definition_id': ident})
        if ident not in existing:
            actions.append(variant)
    return actions


@hook('compile_action')
def replace_weapon_disarm(action, info):
    if not owned(info):
        return action
    if action.source_definition_id.endswith('#disarm'):
        return disarm(action)
    typed = action.parameters.get('typed') or {}
    if any(e.get('type') == 'brute_overrun' or e.get('type') == 'brutal_shove' and e.get('mode') == 'aside'
           for e in typed.get('effects', ())):
        params = deepcopy(action.parameters)
        for row in params['typed'].get('effects', ()):
            if row.get('type') == 'brute_overrun' or row.get('type') == 'brutal_shove' and row.get('mode') == 'aside':
                row['category_size'] = True
                if row.get('mode') == 'aside':
                    row['native_aside'] = True
        return action.model_copy(update={'parameters': params})
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
    from ..attack_declaration import declare
    from ..attack_reach import maximum
    from dataclasses import replace
    target, _ = declare(engine, actor, target, ctx.source, ctx.intent, 1,
        range_ft=maximum(engine, actor, ctx.action) or 5, context={'effect': effect, 'typed': ctx.typed})
    ctx = replace(ctx, target=target, targets=[target], attack_effect=effect)
    from ..targeting import attack_line_of_effect
    checkpoints = engine._attack_checkpoint(actor, target, ctx.source, ctx.intent, 1,
        {'effect': effect, 'typed': ctx.typed, 'ranged': bool(ctx.typed.get('range_ft'))})
    if not engine._target_in_range(actor, target, ctx.action) or not attack_line_of_effect(engine, actor, target, ctx.source):
        return
    from . import any_false
    if any_false('attack_allowed', ctx, target, effect):
        return
    from .attack_scope import resolving
    from .thrown_equipment import return_inscription
    with resolving(ctx, target, effect):
        try:
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
            mine = set()
            base_mode = engine._attack_mode(actor, target, contributions=mine)
            if base_mode != 'NORMAL':
                mine.add(base_mode)
            from . import run_strict
            from ..attack_modes import typed_contribution
            for value in run_strict('attack_mode', ctx, target):
                contribution = typed_contribution(value)
                if contribution:
                    mine.add(contribution[0])
            occupant = 'weapon:' + str(item.get('weapon_action')) if item.get('weapon_action') else 'shield:' + str(item['key'])
            hands = sum(occupant in occupants or 'object:' + str(item['key']) in occupants
                        for part, occupants in occupancy(engine, target).items() if part.startswith('hand:'))
            if hands >= 2:
                mine.add('DISADVANTAGE')
            larger = CATEGORIES.index(current_category(engine, target)) - CATEGORIES.index(current_category(engine, actor))
            with engine.d20_scope({'kind': 'attack', 'actor_id': actor.entity_id, 'target_id': target.entity_id,
                                  'source_id': ctx.source, 'source_actor_id': actor.entity_id}):
                bonus = int(ctx.numbers.get('attack_bonus', 0)) + sum(run_strict('attack_bonus', ctx, actor))
                from ..attack_modes import disadvantage_alternatives, checkpoint_results
                from ..choice_checkpoints import roll_modes
                checkpoints, penalty = disadvantage_alternatives(checkpoints, combine_modes(mine))
                attack = engine.roller.d20(modifier=bonus + penalty, actor_id=actor.entity_id,
                    reason='ATTACK:' + ctx.source + ':DISARM', mode=roll_modes(combine_modes(mine), checkpoint_results(checkpoints)))
            engine._record_roll(attack)
            total = attack.total + engine._consume_attack_modifiers(actor)
            from ..roll_resolution import visible_attack
            _ac, revalidate = visible_attack(engine, actor, target,
                {'attack_modified_total': total, 'parameters': ctx.action.parameters, 'typed': ctx.typed}, attack, ctx.intent)
            engine._append_event('CONTESTED_ATTACK_ROLLED', ctx.source, actor_id=actor.entity_id,
                target_ids=(target.entity_id,), payload={**attack.model_dump(mode='json'), 'modified_total': total})
            from ..target_knowledge import can_see
            from ..attack_outcomes import forced_miss
            forced = forced_miss(engine, actor, target, ctx.source, 1, attack, checkpoints)
            if forced or revalidate and (not target.active or not engine._target_in_range(actor, target, ctx.action)
                               or not attack_line_of_effect(engine, actor, target, ctx.source) or not can_see(engine, actor, target)):
                engine._append_event('CONTESTED_ATTACK_FAILED', ctx.source, actor_id=actor.entity_id,
                    target_ids=(target.entity_id,), payload={'roll_id': attack.roll_id, 'reason': 'TARGET_NO_LONGER_LEGAL', 'item': picked[0]})
                return
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
        finally:
            return_inscription(ctx, target, False, effect)
