"""Heaven-Sealing Ice Script on the transactional declaration checkpoint.

The owner chooses whether to spend their Reaction and 3 CP. On a failed save,
the triggering creature chooses among changes that can affect its activation.
No candidate listing spends resources or changes state.
"""

from ..paid_relocation import activation
from . import hook

FEATURE = 'TAL_ICE_HEAVEN_SEALING_ICE_SCRIPT'
BLOCK = 'ice_interception'


@hook('compile_block')
def compile_ice(block, spec, row, numbers):
    return [{**row, 'block': BLOCK, 'cl': int(numbers['cl'])}] if block == BLOCK else None


def applicable(action):
    from ..typed_executor import _walk_rows
    typed = action.parameters.get('typed') or {}
    effects = list(_walk_rows(typed.get('effects') or []))
    options = {}
    if (action.range_ft or action.reach_ft or 0) > 5:
        options['range'] = ('Reduce this effect’s range by 30 feet (minimum touch)', {'range_delta_ft': -30})
    if (action.radius_ft or (typed.get('area') or {}).get('size_ft') or 0) > 5:
        options['area'] = ('Reduce one area dimension by 10 feet (minimum 5 feet)', {'area_delta_ft': -10})
    # The shared choice primitive runs a native Dash movement grant when chosen;
    # its declaration must expose the same cap as a plain movement row.
    if any(e.get('type') in {'forced_movement', 'movement', 'teleport', 'reaction_move', 'move_object',
                             'dash_or_disengage'} for e in effects):
        options['movement'] = ('Limit movement and teleportation to 10 feet per creature or object. The GM must check any additional movement or moved objects.', {'movement_cap_ft': 10})
    weapon_damage = (typed.get('weapon') or {}).get('damage')
    if (action.damage is not None and action.damage.count > 0) or any(e.get('type') == 'damage' and
            (e.get('dice') or e.get('dice_by_cl') or (e.get('weapon_damage') and weapon_damage)) for e in effects):
        options['damage'] = ('Reduce this effect’s first damage roll by the Ice user’s Cultivation Level', {})
    return options


@hook('technique_declared')
def freeze_outer_path(engine, user, action, candidate, intent):
    from ..typed_executor import bears_mark, condition_rules
    from ..target_knowledge import can_see
    from . import needle
    from ..technique_interception import named_ability
    if not named_ability(action):
        return None
    options = applicable(action)
    if not options:
        return None
    changes, labels = {}, []
    for reactor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        row = next((r for r in getattr(engine, 'typed_passive_rows', {}).get(reactor.entity_id, []) if r.get('block') == BLOCK and not r.get('held_back')), None)
        if row is None or not reactor.active or reactor.life_state is not None or not reactor.reaction_available:
            continue
        if any(rule.get('no_reactions') for rule in condition_rules(reactor)):
            continue
        if not bears_mark(user, reactor.entity_id, 'Fracture Mark') or engine._distance_actor_to_actor(reactor, user) > 60 or not can_see(engine, reactor, user):
            continue
        pools = [rid for rid in ('resource:core.qi', 'resource:core.stamina', 'resource:core.resonance')
                 if engine._can_pay(reactor, ((rid, 3),), source_id=FEATURE)]
        if not pools:
            continue
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, 'ice_script', reactor.entity_id, action.source_definition_id),
            reactor, needle.CHOICE + 'ice_script', pools,
            labels={rid: f"Spend 3 {rid.rsplit('.', 1)[-1].title()} and your Reaction" for rid in pools},
            allow_decline=True, name='Heaven-Sealing Ice Script', feature_id=FEATURE,
            prompt=f'{user.display_name} starts {action.display_name}. Use your Reaction and 3 CP to try to weaken it?', target_id=user.entity_id)
        if not chosen:
            continue
        with activation(engine, reactor, FEATURE):
            reactor.reaction_available = False
            engine._spend_costs(reactor, ((chosen[0], 3),), FEATURE)
            engine._append_event('REACTION_RESOLVED', FEATURE, actor_id=reactor.entity_id, target_ids=(user.entity_id,),
                payload={'checkpoint': 'TECHNIQUE_DECLARED', 'ability': 'Heaven-Sealing Ice Script', 'resource_id': chosen[0], 'spend': 3})
            roll = engine._roll_save(user, 'CON', needle.save_dc(engine, reactor), FEATURE)
            if roll is None or roll.total >= needle.save_dc(engine, reactor):
                continue
            choice = needle.ask(engine, intent, needle.checkpoint_id(engine, 'ice_script_effect', reactor.entity_id, action.source_definition_id),
                user, needle.CHOICE + 'ice_script_effect', list(options), labels={key: v[0] for key, v in options.items()},
                name='Heaven-Sealing Ice Script', feature_id=FEATURE,
                prompt=f'{user.display_name} failed the save. Choose how Heaven-Sealing Ice Script weakens {action.display_name}; this choice costs nothing extra.')
            key = (choice or list(options))[0]
            change = {'damage_roll_reduction': row['cl']} if key == 'damage' else options[key][1]
            for field, amount in change.items():
                changes[field] = min(changes.get(field, amount), amount) if field in {'forced_cap_ft', 'movement_cap_ft'} else changes.get(field, 0) + amount
            labels.append(f'{reactor.display_name}: {options[key][0]}.')
    return {'source_id': FEATURE, 'label': 'Heaven-Sealing Ice Script — ' + ' '.join(labels), **changes} if labels else None
