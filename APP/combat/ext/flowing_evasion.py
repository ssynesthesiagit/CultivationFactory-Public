"""Flowing Evasion: a Reaction and 2 Qi halve positive, defended attack damage.

Reuse the owned compiled reaction row and plan, including older saved bundles.
The former generic pre-hit half_damage path is suppressed; this is its one owner.
"""

from ..paid_relocation import activation, capture, causal_scope, retain, take
from . import hook
from .needle import ask, checkpoint_id, CHOICE

FEATURE = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.flowing_evasion'
RECORD = 'flowing_evasion_attack'


def reduced_packet(target, record, amount):
    """Halve the defended attack total, rounding down once across its packets."""
    before = int(record['defended'])
    record['defended'] = before + amount
    target.turn_flags[RECORD] = record
    return {'amount': (before + amount) // 2 - before // 2}


@hook('reaction_subject_allowed')
def replace_early_reaction(engine, actor, other, row):
    return False if row.get('feature_id') == FEATURE and not row.get('post_defense_attack') else None


@hook('final_damage')
def evade(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    provenance = engine.damage_context()
    if amount <= 0 or provenance is None or intent is None:
        return None
    key = f'{intent.intent_id}:{source_actor_id}:{provenance.roll_id}'
    record = target.turn_flags.get(RECORD) or {}
    if record.get('key') == key:
        return reduced_packet(target, record, amount) if record['accepted'] else None
    from .. import typed_reactions as reactions
    row = next((r for r in reactions._rows(engine, target.entity_id, 'generic') if r.get('feature_id') == FEATURE), None)
    attacker = engine.state.actors.get(source_actor_id)
    if (row is None or attacker is None or not reactions._can_trigger(engine, target, row)
            or not reactions._generic_affordable(engine, target, row)
            or not reactions._generic_in_range(engine, target, attacker, row)
            or not reactions._subject_ok(engine, target, attacker, {**row, 'post_defense_attack': True})):
        return None
    if reactions._asking(engine, target, row):
        action = engine.action_catalog.get(source_id)
        name = action.display_name if action is not None else 'attack'
        choice = ask(engine, intent, checkpoint_id(engine, 'FLOWING_EVASION', target.entity_id, provenance.attack_index),
            target, CHOICE + 'flowing_evasion', ['halve'], labels={'halve': 'Spend your Reaction and 2 Qi: halve all damage from this attack, then move'},
            prompt=f"Flowing Evasion: {attacker.display_name}'s {name} hits {target.display_name}, with "
                   f"{amount} {damage_type.lower()} damage pending in this component. Spend your Reaction and 2 Qi "
                   "to halve all remaining damage from this attack, then move 5 feet (10 feet if fully submerged or in your Moon’s Pull field)?",
            prompt_context={'source_definition_id':source_id},
            name='Flowing Evasion', feature_id=FEATURE, allow_decline=True, default='decline', target_id=target.entity_id)
        if not choice:
            target.turn_flags[RECORD] = {'key': key, 'accepted': 0, 'defended': 0}
            return None
    with activation(engine, target, FEATURE):
        reactions._spend_generic(engine, target, row)
        target.reaction_available = False
        engine._append_event('REACTION_RESOLVED', FEATURE, actor_id=target.entity_id, target_ids=(target.entity_id,),
            payload={'checkpoint': 'POST_DEFENSE_ATTACK_DAMAGE', 'attack_source_id': source_id,
                     'attack_roll_id': provenance.roll_id, 'critical': provenance.critical,
                     'damage_before': amount, 'damage_after': amount // 2})
        retain(engine, (RECORD, target.entity_id, key), capture(engine))
        return reduced_packet(target, {'key': key, 'accepted': 1, 'defended': 0}, amount)


@hook('attack_damage_final')
def move_after_attack(engine, attacker, target, provenance, intent):
    """The owned post-damage step; choices and movement remain in the transaction."""
    from types import SimpleNamespace
    from .needle import ask, checkpoint_id, cell_options, position_of, step_to, numbers_of
    from .physical_holds import source, end_hold
    from .formations import arrays, gate_label
    from . import run
    from ..typed_executor import condition_rules

    record = target.turn_flags.get(RECORD) or {}
    key = f'{intent.intent_id}:{attacker.entity_id}:{provenance.roll_id}' if intent else ''
    if record.get('key') != key or not record.get('accepted') or record.get('moved'):
        return
    with causal_scope(engine, take(engine, (RECORD, target.entity_id, key))):
        record['moved'] = 1
        if not target.active or target.life_state is not None:
            return
        holds = {iid: c for iid, c in target.conditions.items()
                 if c.source_actor_id == attacker.entity_id
                 and c.condition_id.rsplit('.', 1)[-1] in {'grappled', 'restrained'} and source(engine, c)[0]}
        if holds:
            ability = ask(engine, intent, checkpoint_id(engine, 'Flowing Evasion Slip the Grasp', key), target,
                CHOICE + 'flowing_evasion_escape', ['STR', 'DEX'], labels={'STR':'Strength saving throw', 'DEX':'Dexterity saving throw'},
                name='Flowing Evasion: Slip the Grasp', feature_id=FEATURE,
                prompt=f"Flowing Evasion after {attacker.display_name}'s attack hits {target.display_name}: "
                       "choose Strength or Dexterity to escape the attacker's physical hold before moving.",
                prompt_context={'cost':'No additional action or resource cost'})
            for iid, hold in holds.items():
                action = engine.action_catalog.get(hold.source_definition_id)
                numbers = (((action.parameters or {}).get('typed') or {}).get('numbers') or {}) if action else {}
                dc = hold.data.get('save_dc') or numbers.get('save_dc')
                if dc is None:
                    key_mod = numbers_of(engine, attacker).get('key_mod')
                    if key_mod is None:
                        engine._append_event('GM_RIDER', FEATURE, actor_id=target.entity_id,
                            payload={'rider':"Flowing Evasion: Slip the Grasp needs the GM to set the save DC "
                                              "to 8 + the attacker's Proficiency Bonus + its key ability modifier; "
                                              "that modifier is not recorded."})
                        continue
                    dc = 8 + attacker.proficiency_bonus + int(key_mod)
                dc = int(dc)
                modes = {mode for mode in run('escape_save_mode', engine, target, [hold])
                         if mode in {'ADVANTAGE', 'DISADVANTAGE'}}
                roll = engine._roll_save(target, ability[0], dc, FEATURE,
                                         extra_mode=next(iter(modes)) if len(modes) == 1 else None)
                from . import run_strict
                run_strict("escape_roll_resolved", engine, target, [hold], roll.total >= dc, "save", FEATURE)
                if roll.total >= dc:
                    end_hold(SimpleNamespace(engine=engine, actor=target, source=FEATURE), iid)
        if engine._effective_speed(target) <= 0:
            engine._append_event('GM_RIDER', FEATURE, actor_id=target.entity_id,
                payload={'rider':f"Flowing Evasion: {target.display_name} cannot move while its Speed is 0."})
            return
        moon = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.moon_s_pull'
        in_moon = any(z.active and z.owner_id == target.entity_id and engine._footprint_intersects(target, z.affected_cells)
                      and (engine.action_catalog[z.source_definition_id].parameters.get('typed') or {}).get('source') == moon
                      for z in engine.state.zones.values() if engine.action_catalog.get(z.source_definition_id))
        feet = 10 if in_moon else 5
        if not in_moon:
            distance = ask(engine, intent, checkpoint_id(engine, 'Flowing Evasion movement distance', key), target,
                CHOICE + 'flowing_evasion_distance', ['5', '10'], name='Flowing Evasion movement distance', feature_id=FEATURE,
                labels={'5':'Move up to 5 feet', '10':'Fully submerged: move up to 10 feet'},
                prompt=f"Flowing Evasion after {attacker.display_name}'s attack damages {target.display_name}: "
                       "move 5 feet, or 10 feet only if fully submerged. This table does not track water depth; "
                       "choose 10 feet only when the GM confirms full submersion.",
                prompt_context={'cost':'No additional action or resource cost'}, preferred=['5'])
            feet = int(distance[0])
        reachable = engine.grid.reachable(target.position, movement_ft=feet,
            occupied_cells=engine._occupied_cells_except(target.entity_id),
            difficult_cells=engine._hostile_difficult_cells(target), footprint=engine._footprint(target))
        reachable = {cell: path_cost for cell, path_cost in reachable.items()
                     if not any(gate_label(engine, zone, target, start, end)
                                for zone in arrays(engine) for start, end in zip(path_cost[0], path_cost[0][1:]))}
        costs = {cell:cost for cell, (_,cost) in reachable.items()}
        if not costs:
            engine._append_event('GM_RIDER', FEATURE, actor_id=target.entity_id,
                payload={'rider':f"Flowing Evasion: {target.display_name} has no legal unoccupied destination within {feet} feet."})
            return
        options, labels = cell_options(engine, target, costs, cap=len(costs))
        preferred = [o for o in options if o != f'cell:{target.position.x},{target.position.y}']
        selected = ask(engine, intent, checkpoint_id(engine, 'Flowing Evasion movement', key), target,
            CHOICE + 'flowing_evasion_move', options, labels=labels, name='Flowing Evasion movement', feature_id=FEATURE,
            prompt=f"Flowing Evasion after {attacker.display_name}'s attack damages {target.display_name}: "
                   f"choose a legal unoccupied space within {feet} feet, without Opportunity Attacks.",
            prompt_context={'cost':'No additional action or resource cost'}, preferred=preferred)
        destination = position_of(selected[0])
        if destination != target.position:
            for cell in reachable[destination][0][1:]:
                # Zone entry/crossing can incapacitate, hold, move or block the actor.
                # Validate the next step against the current state, never the old path alone.
                if (not target.active or target.life_state is not None or engine._effective_speed(target) <= 0
                        or any(row.get('no_actions') for row in condition_rules(target))
                        or not engine.grid.step_legal(target.position, cell, footprint=engine._footprint(target),
                                                     occupied_cells=engine._occupied_cells_except(target.entity_id))
                        or any(gate_label(engine, zone, target, target.position, cell) for zone in arrays(engine))):
                    break
                step_to(engine, target, cell, FEATURE, forced=False)
