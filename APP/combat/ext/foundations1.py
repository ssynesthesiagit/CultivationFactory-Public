"""Foundation conversions with objective combat triggers.

Dragon-Wind counts native willing path distance controlled by its owner. Completed
attacks generate Momentum after all hit riders; pressure owns cap/round/expiry.
The speed passive is compiled as a normal motion row. Named conversions are
ordinary no-action choices, paid by the catalog before their effect executes.
No affinity-sphere approximation is used to invent Fixed Foundation Scope.
"""
from . import effect, hook, note

BLOCK = 'foundations1_conversion'
DISTANCE = 'foundations1_dragon_moved_ft'


@hook('compile_block')
def compile_conversion(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'kind': spec['kind'], 'pb': int(numbers['pb']),
             'key_mod': int(numbers['key_mod'])}]


@hook('compile_actions')
def conversions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    made = []
    for row in info['passives']:
        if row.get('block') != BLOCK or row.get('kind') not in ('momentum_step', 'banked_coals') or not row.get('resource_id'):
            continue
        name = info['mechanics'][row['feature_id']]['name']
        if row['kind'] == 'momentum_step':
            name += ' (walking: GM reminder)'
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{row['kind']}",
            display_name=name, owner_id=info['actor_id'], economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='SELF', costs=((row['resource_id'], 1),),
            parameters={'typed': {'source': row['feature_id'], 'numbers': info['numbers'],
                'effects': [{'type': 'foundations1_conversion', 'kind': row['kind']}],
                'riders': [], 'duration': {'kind': 'instant'}},
                'expected_temp_hp': row['pb'] + row['key_mod'] if row['kind'] == 'banked_coals' else 0}))
    return made


@effect('foundations1_conversion', harmful=False)
def conversion(ctx, eff):
    from .. import typed_executor
    if eff['kind'] == 'momentum_step':
        from .. import flight
        from .needle import ask, CHOICE, checkpoint_id
        options = ['walk']
        if flight.profile(ctx.engine, ctx.actor).speed_ft > 0:
            options.append('fly')
        selected = options[0]
        if len(options) > 1:
            chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'momentum_speed', ctx.actor.entity_id),
                ctx.actor, CHOICE + 'momentum_speed', options, minimum=1, maximum=1, preferred=['walk'],
                name='Momentum Step', target_id=ctx.actor.entity_id, labels={'walk': 'Walking speed (GM reminder; resolve movement manually)', 'fly': 'Flying speed (+10 feet, automated)'},
                prompt='Momentum Step: spend 1 Dragon-Wind Momentum for +10 feet to one existing speed until this turn ends. Flying is automated; walking needs the GM to resolve your speed and remaining movement.')
            selected = chosen[0]
        if selected == 'fly':
            ctx.engine._apply_condition(ctx.actor, 'condition:typed.foundations1_fly_step', ctx.source,
                ctx.actor.entity_id, expires_on='END_OF_CURRENT_TURN',
                data={'fly_speed_bonus_ft': 10, 'label': 'Momentum Step: flying speed +10 feet'})
            return
        # The shared pool does not distinguish spent base feet from Dash or
        # separate grants. Do not add a second ledger to every creature merely
        # for this conversion (lead direction 2026-10-12).
        ctx.rider('Momentum Step — GM reminder: 1 Dragon-Wind Momentum has been spent. '
                  'Increase your walking speed by 10 feet until this turn ends; '
                  'the GM must resolve your remaining movement. This table has not changed '
                  'your walking speed or granted movement.')
    else:
        amount = int(ctx.numbers['pb']) + int(ctx.numbers['key_mod'])
        rows = ctx.engine.typed_passive_rows.get(ctx.actor.entity_id, [])
        if any(r.get('block') == BLOCK and r.get('kind') == 'heart_cauldron_body' for r in rows):
            flag = 'foundations1_round_cauldron'
            if ctx.actor.turn_flags.get(flag) != ctx.engine.state.round_number:
                ctx.actor.turn_flags[flag] = ctx.engine.state.round_number
                amount += int(ctx.numbers['pb'])
        typed_executor.run_effects(ctx, [{'type': 'temp_hp', 'flat': max(0, amount), 'applies_to': 'self'}])


@hook('event')
def controlled_distance(engine, event_type, kwargs):
    if event_type != 'MOVEMENT_COMMITTED':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    payload = kwargs.get('payload') or {}
    if actor is None or payload.get('forced') or payload.get('dragged_by') or payload.get('teleport'):
        return
    if not any(r.get('block') == 'generate' and 'dragon_wind_hit' in r.get('on', [])
               for r in engine.typed_passive_rows.get(actor.entity_id, [])):
        return
    # Only actual walked path edges count. Teleport arrivals have no walked path.
    distance = max(0, len(payload.get('path') or []) - 1) * engine.grid.square_size_ft
    actor.turn_flags[DISTANCE] = int(actor.turn_flags.get(DISTANCE, 0)) + distance


@hook('attack_completed')
def momentum_after_hit(engine, notice, intent):
    actor = engine.state.actors.get(notice.attacker_id)
    if actor is None or not notice.hit or int(actor.turn_flags.get(DISTANCE, 0)) < 20:
        return
    from .. import pressure
    if pressure.generate(engine, actor, 'dragon_wind_hit'):
        note(engine, notice.source_id, actor, f'{actor.display_name} gains Dragon-Wind Momentum after the hit resolves.')
