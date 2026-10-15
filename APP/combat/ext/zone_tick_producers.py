"""Source-qualified clocks for reviewed fields with conditional recipients.

The ordinary zones dispatcher owns entry/start/once-per-turn and replay. These
producers only supply the missing Patron/formula payload or a custom printed
moment. Nothing executes damage while constructing a zone. Profile flags are
opt-in reviewed data; unflagged fields and characters are unchanged.
"""
from . import hook, effect


def _save(ability, dice, kind, fail=(), success=()):
    return {'type': 'save', 'ability': ability, 'dc': 'technique_save_dc',
            'on_fail': [{'type': 'damage', 'dice': {'count': dice, 'sides': 8},
                         'damage_types': [kind]}, *fail],
            'on_success': [{'type': 'half_damage'}, *success]}


@hook('zone_created')
def choose_payload(ctx, zone):
    profile = zone.trigger_profile.get('profile') or {}
    if profile.get('patron_aura'):
        from .shugenja_prayer import choose_patron, TYPES
        patron = choose_patron(ctx)
        if patron is None:
            return
        riders = {
            'air': [{'type': 'forced_movement', 'distance_ft': 10, 'direction': 'away'}],
            'cold': [{'type': 'speed', 'flat': -15, 'duration': 'until_start_of_next_turn'}],
            'earth': [{'type': 'condition', 'condition': 'prone', 'duration': 'instant'}],
            'fire': [{'type': 'reaction_denied', 'duration': 'until_start_of_next_turn'}],
            'lightning': [{'type': 'disadvantage', 'on': 'next_attack', 'duration': 'until_start_of_next_turn'}],
            'metal': [{'type': 'ac_bonus', 'flat': -1, 'duration': 'until_start_of_next_turn'}],
            'water': [{'type': 'zone_patron_water_move'}],
            'wood': [{'type': 'condition', 'condition': 'restrained', 'duration': 'until_start_of_next_turn'}],
        }
        ability = {'air': 'STR', 'cold': 'CON', 'water': 'STR', 'wood': 'STR'}.get(patron, 'DEX')
        zone.trigger_profile['triggers'] = [{
            'id': zone.source_definition_id + ':patron', 'name': 'Avatar of the Element',
            'on': ['enter', 'start'], 'who': 'hostile',
            'effects': [_save(ability, 2, TYPES[patron], riders[patron])]}]
    if profile.get('incense_formula'):
        from .needle import ask, checkpoint_id
        formulas = ['Calming Sandalwood', 'Revealing Camphor', 'Bitter Smoke',
                    'Lotus Focus', 'Dreaming Jasmine', 'Mourning Myrrh']
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'incense_formula'), ctx.actor,
                     'choice:zone.incense_formula', formulas, name='Burn Incense',
                     prompt='Burn Incense: choose the learned Formula of the prepared dose you expend. '
                            'Its cloud lasts 1 minute with Concentration; hostile saves occur only on its printed entry or turn-start trigger.')
        if not picked:
            return
        formula = picked[0]
        zone.trigger_profile['profile'] = {**profile, 'formula': formula}
        zone.trigger_profile['name'] = 'Burn Incense: ' + formula
        effects, on = [], ['start']
        if formula == 'Bitter Smoke':
            count = 4 if int(ctx.numbers.get('cl') or 1) >= 17 else 3 if int(ctx.numbers.get('cl') or 1) >= 11 else 2
            save = _save('CON', count, 'poison',
                         [{'type': 'speed', 'flat': -10, 'duration': 'until_start_of_next_turn'}],
                         [{'type': 'speed', 'flat': -5, 'duration': 'until_start_of_next_turn'}])
            save['on_fail'][0]['dice']['sides'] = 6
            effects, on = [save], ['enter', 'start']
        elif formula == 'Mourning Myrrh':
            save = _save('CHA', 2, 'radiant', [{'type': 'condition', 'condition': 'incense_no_possession',
                                             'duration': 'until_start_of_next_turn',
                                             'condition_data': {'no_possession': 1, 'label': 'Mourning Myrrh: cannot possess a creature until your next turn'}}])
            save['on_fail'][0]['dice']['sides'] = 6
            effects = [save]
        elif formula in ('Calming Sandalwood', 'Dreaming Jasmine'):
            sides = 6 if formula == 'Dreaming Jasmine' else 4
            penalty = {'type': 'attack_modifier', 'dice': {'count': 1, 'sides': sides},
                       'negative': True, 'duration': 'until_start_of_next_turn', 'on': 'next_attack'}
            effects = [{'type': 'save', 'ability': 'WIS', 'dc': 'technique_save_dc',
                        'on_fail': [penalty, *([{'type': 'reaction_denied', 'duration': 'until_start_of_next_turn'}]
                                             if formula == 'Dreaming Jasmine' else [])],
                        'on_success': ([{**penalty, 'dice': {'count': 1, 'sides': 4}}]
                                       if formula == 'Dreaming Jasmine' else [])}]
        zone.trigger_profile['triggers'] = ([{'id': zone.source_definition_id + ':incense',
            'name': formula, 'on': on, 'who': 'hostile', 'effects': effects}] if effects else [])


@hook('zone_recipient_allowed')
def conditional_recipient(engine, zone, actor, spec):
    profile = zone.trigger_profile.get('profile') or {}
    if profile.get('grappling_owner'):
        owner = engine.state.actors.get(zone.owner_id)
        return owner is not None and any(c.condition_id.rsplit('.', 1)[-1] == 'grappled'
            and c.source_actor_id == actor.entity_id for c in owner.conditions.values())
    if profile.get('incense_formula'):
        from ..physiology import trait
        from .creature_kinds import labels
        formula = profile.get('formula')
        if formula == 'Bitter Smoke':
            return trait(actor, 'breath_dependent') is True
        if formula == 'Mourning Myrrh':
            return bool(set(labels(actor)) & {'spirit', 'undead', 'incorporeal', 'possession entity', 'possessing'})
    return None


@hook('event')
def spent_in_field(engine, event):
    if event.event_type != 'RESOURCE_SPENT' or int((event.payload or {}).get('amount') or 0) <= 0:
        return
    if (event.payload or {}).get('resource_id') not in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'}:
        return
    from .. import zones
    from ..spatial_areas import zone_contains
    actor = engine.state.actors.get(event.actor_id)
    if actor is None:
        return
    for zone in list(zones.typed_zones(engine)):
        if (zone.trigger_profile.get('profile') or {}).get('cp_spent_tick') and zone_contains(engine, actor, zone):
            zones.fire_trigger(engine, zone, actor, 'cp_spent')


@hook('movement_step')
def center_approach(engine, mover, previous, destination, intent):
    from .. import zones
    from .retained_updates import record_zone_update
    for zone in list(zones.typed_zones(engine)):
        if zone.owner_id != mover.entity_id or not (zone.trigger_profile.get('profile') or {}).get('center_impact'):
            continue
        # The source says the center must MOVE ten feet, then enter the
        # creature's five-foot reach. Initial placement never reaches this hook.
        key = 'center_impact_distance'
        clock = next((e.sequence for e in reversed(engine.events) if e.event_type == 'TURN_STARTED'), 0)
        amount = (int(zone.per_turn_triggered.get(key, 0)) if zone.per_turn_triggered.get(key + ':clock') == clock else 0)
        amount += engine.grid.distance_ft(previous, destination)
        zone.per_turn_triggered[key] = amount
        zone.per_turn_triggered[key + ':clock'] = clock
        record_zone_update(engine, zone)
        if amount < 10:
            continue
        for target in list(engine.state.actors.values()):
            if target.active and engine.grid.distance_ft(previous, target.position) > 5 >= engine.grid.distance_ft(destination, target.position):
                zones.fire_trigger(engine, zone, target, 'center_approach')


@effect('zone_patron_water_move', harmful=True)
def water_direction(ctx, row):
    from .needle import ask, checkpoint_id
    from ..typed_executor import run_effects
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'patron_aura_water', ctx.target.entity_id),
                 ctx.actor, 'choice:zone.patron_water', ['push', 'pull'],
                 name='Avatar of the Element', target_id=ctx.target.entity_id,
                 prompt=f'Avatar of the Element: push or pull {ctx.target.display_name} 10 feet after its failed aura save. No additional cost.')
    run_effects(ctx, [{'type': 'forced_movement', 'distance_ft': 10,
                       'direction': 'toward' if picked and picked[0] == 'pull' else 'away'}])
