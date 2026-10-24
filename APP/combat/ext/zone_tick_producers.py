"""Source-qualified clocks for reviewed fields with conditional recipients.

The ordinary zones dispatcher owns entry/start/once-per-turn and replay. These
producers only supply the missing Patron/formula payload or a custom printed
moment. Nothing executes damage while constructing a zone. Profile flags are
opt-in reviewed data; unflagged fields and characters are unchanged.
"""
from . import hook, effect


def profiled_zones(engine, flag):
    """Skip derived-area work unless a stored source field opts into this clock."""
    if not any(z.active and (z.trigger_profile.get('profile') or {}).get(flag)
               for z in engine.state.zones.values()):
        return []
    from .. import zones
    return [z for z in zones.typed_zones(engine) if (z.trigger_profile.get('profile') or {}).get(flag)]


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
            'lightning': [{'type': 'disadvantage', 'on': 'next attack roll'}],
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
        labels = {
            'Calming Sandalwood': 'Calming Sandalwood — hostile turn-start Wisdom save; failed save penalizes the next hostile attack',
            'Revealing Camphor': 'Revealing Camphor — GM resolves outlines of concealed spirits and supernatural traces inside the cloud',
            'Bitter Smoke': 'Bitter Smoke — hostile breathing creatures save on entry or turn-start; Poison damage and reduced Speed',
            'Lotus Focus': 'Lotus Focus — GM applies +1 to chosen allies’ Concentration saves and Cultivation Checks inside the cloud',
            'Dreaming Jasmine': 'Dreaming Jasmine — hostile turn-start Wisdom save; attack/check penalty and no Reactions on failure',
            'Mourning Myrrh': 'Mourning Myrrh — hostile spirits and Undead save at turn-start; Radiant or Psychic damage and no possession on failure',
        }
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'incense_formula'), ctx.actor,
                     'choice:needle.zone_incense_formula', formulas, labels=labels, name='Burn Incense',
                     prompt='Burn Incense: choose the learned Formula of the prepared dose you expend. '
                            'Its cloud lasts 1 minute with Concentration; hostile saves occur only on its printed entry or turn-start trigger.')
        if not picked:
            return
        formula = picked[0]
        zone.trigger_profile['profile'] = {**profile, 'formula': formula}
        zone.trigger_profile['name'] = 'Burn Incense: ' + formula
        if formula == 'Calming Sandalwood':
            from ..relations import relation, ALLY
            allies = [a for a in ctx.engine.state.actors.values()
                      if a.active and relation(ctx.engine, ctx.actor, a) == ALLY]
            recipients = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'incense_allies'), ctx.actor,
                'choice:needle.zone_incense_allies', [a.entity_id for a in allies], minimum=0,
                maximum=len(allies), allow_decline=True, default='all', name='Calming Sandalwood',
                labels={a.entity_id: f'{a.display_name} at square {a.position.x}, {a.position.y}' for a in allies},
                prompt='Calming Sandalwood: choose allies who gain Advantage on saves against being Charmed or Frightened while inside this cloud. '
                       'No additional cost; the cloud lasts 1 minute with Concentration.')
            zone.trigger_profile['profile']['beneficiaries'] = list(recipients or [])
            zone.trigger_profile['inside'] = [{
                'id': zone.source_definition_id + ':calming', 'name': formula, 'who': 'ally',
                'rule': {'save_against': {'mode': 'ADVANTAGE', 'against': ['charmed', 'frightened']}},
                'reading': 'Allies inside have Advantage on saves against being Charmed or Frightened.'}]
        effects, on = [], ['start']
        if formula == 'Bitter Smoke':
            count = 4 if int(ctx.numbers.get('cl') or 1) >= 17 else 3 if int(ctx.numbers.get('cl') or 1) >= 11 else 2
            save = _save('CON', count, 'poison',
                         [{'type': 'speed', 'flat': -10, 'duration': 'until_start_of_next_turn'}],
                         [{'type': 'speed', 'flat': -5, 'duration': 'until_start_of_next_turn'}])
            save['on_fail'][0]['dice']['sides'] = 6
            effects, on = [save], ['enter', 'start']
        elif formula == 'Mourning Myrrh':
            save = _save('CHA', 2, 'radiant', [{'type': 'rider',
                'evidence': 'Mourning Myrrh: the affected creature cannot possess another creature until the start of its next turn.'}])
            save['on_fail'][0]['dice']['sides'] = 6
            save['on_fail'][0]['damage_types'] = ['radiant', 'psychic']
            effects = [save]
        elif formula in ('Calming Sandalwood', 'Dreaming Jasmine'):
            sides = 6 if formula == 'Dreaming Jasmine' else 4
            # These existing unautomated roll penalties stay explicit GM
            # riders, now at their actual save rather than at cloud creation.
            penalty = {'type': 'rider', 'evidence': f'{formula}: the affected creature subtracts 1d{sides} '
                       + ('from its next attack roll or Cultivation Check before the start of its next turn.'
                          if formula == 'Dreaming Jasmine' else 'from its next hostile attack roll before the start of its next turn.')}
            effects = [{'type': 'save', 'ability': 'WIS', 'dc': 'technique_save_dc',
                        'on_fail': [penalty, *([{'type': 'reaction_denied', 'duration': 'until_start_of_next_turn'}]
                                             if formula == 'Dreaming Jasmine' else [])],
                        'on_success': ([{'type': 'rider', 'evidence': 'Dreaming Jasmine: the affected creature subtracts 1d4 from its next attack roll before the start of its next turn.'}]
                                       if formula == 'Dreaming Jasmine' else [])}]
        zone.trigger_profile['triggers'] = ([{'id': zone.source_definition_id + ':incense',
            'name': formula, 'on': on, 'who': 'hostile', 'effects': effects}] if effects else [])


@hook('zone_recipient_allowed')
def conditional_recipient(engine, zone, actor, spec):
    profile = zone.trigger_profile.get('profile') or {}
    if profile.get('requires_kinds'):
        from .creature_kinds import matches
        if not matches(actor, profile['requires_kinds']):
            return False
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
        if formula in ('Calming Sandalwood', 'Dreaming Jasmine'):
            from .creature_kinds import matches
            if formula == 'Calming Sandalwood' and spec.get('who') == 'ally' and actor.entity_id not in profile.get('beneficiaries', []):
                return False
            if formula == 'Dreaming Jasmine' and matches(actor, ['mindless']):
                return False
            return trait(actor, 'breath_dependent') is True or matches(actor, ['spirit'])
        if formula == 'Mourning Myrrh':
            return bool(set(labels(actor)) & {'spirit', 'undead', 'incorporeal', 'possession entity', 'possessing'})
    return None


@hook('state_event')
def spent_in_field(engine, event):
    if event.event_type == 'TURN_STARTED':
        from .. import zones
        actor = engine.state.actors.get(event.actor_id)
        if actor is not None:
            for zone in profiled_zones(engine, 'grappling_owner'):
                if (zone.trigger_profile.get('profile') or {}).get('grappling_owner'):
                    # A long-reach grappler need not stand in the mantle's
                    # ten-foot LIGHT. Its actual hold is the printed trigger.
                    zones.fire_trigger(engine, zone, actor, 'grappler_start')
        return
    if event.event_type == 'DAMAGE_COMMITTED' and str((event.payload or {}).get('damage_type') or '').upper() == 'FIRE':
        from .. import zones
        from ..spatial_areas import zone_contains
        if int(event.payload.get('hp_damage') or 0) + int(event.payload.get('temporary_hp_absorbed') or 0) > 0:
            for zone in profiled_zones(engine, 'fire_damage_tick'):
                if (zone.trigger_profile.get('profile') or {}).get('fire_damage_tick'):
                    for aid in event.target_ids:
                        target = engine.state.actors.get(aid)
                        if target is not None and zone_contains(engine, target, zone):
                            zones.fire_trigger(engine, zone, target, 'fire_damage')
        return
    if event.event_type != 'RESOURCE_SPENT' or int((event.payload or {}).get('amount') or 0) <= 0:
        return
    if (event.payload or {}).get('resource_id') not in {'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'}:
        return
    from .. import zones
    from ..spatial_areas import zone_contains
    actor = engine.state.actors.get(event.actor_id)
    if actor is None:
        return
    for zone in profiled_zones(engine, 'cp_spent_tick'):
        if (zone.trigger_profile.get('profile') or {}).get('cp_spent_tick') and zone_contains(engine, actor, zone):
            zones.fire_trigger(engine, zone, actor, 'cp_spent')


@hook('movement_step')
@hook('forced_movement_step')
def center_approach(engine, mover, previous, destination, intent):
    from .. import zones
    from .retained_updates import record_zone_update
    for zone in profiled_zones(engine, 'center_impact'):
        if zone.owner_id != mover.entity_id or not (zone.trigger_profile.get('profile') or {}).get('center_impact'):
            continue
        # The source says the center must MOVE ten feet, then enter the
        # creature's five-foot reach. Initial placement never reaches this
        # hook, and a pushed or pulled center moves the same printed way,
        # so this producer subscribes to both step hooks. They are mutually
        # exclusive; once-per-turn accounting is shared below.
        key = 'center_impact_distance'
        clock = next((e.sequence for e in reversed(engine.events) if e.event_type == 'TURN_STARTED'), 0)
        amount = (int(zone.per_turn_triggered.get(key, 0)) if zone.per_turn_triggered.get(key + ':clock') == clock else 0)
        amount += engine.grid.distance_ft(previous, destination)
        zone.per_turn_triggered[key] = amount
        zone.per_turn_triggered[key + ':clock'] = clock
        record_zone_update(engine, zone)
        profile = zone.trigger_profile.get('profile') or {}
        if amount < int(profile.get('impact_min_ft', 10)):
            continue
        reach = int(profile.get('impact_reach_ft', 5))
        for target in list(engine.state.actors.values()):
            # Distances use the engine's occupied-footprint metric: a Large
            # creature is every square it occupies, not its anchor alone.
            near = engine._distance_actor_to_cell(target, destination) <= reach
            entered = engine._distance_actor_to_cell(target, previous) > reach
            if target.active and near and (entered or profile.get('impact_pass_within')):
                zones.fire_trigger(engine, zone, target, 'center_approach')


@effect('zone_patron_water_move', harmful=True)
def water_direction(ctx, row):
    from .needle import ask, checkpoint_id
    from ..typed_executor import run_effects
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'patron_aura_water', ctx.target.entity_id),
                 ctx.actor, 'choice:needle.zone_patron_water', ['push', 'pull'],
                 name='Avatar of the Element', target_id=ctx.target.entity_id,
                 prompt=f'Avatar of the Element: push or pull {ctx.target.display_name} 10 feet after its failed aura save. No additional cost.')
    run_effects(ctx, [{'type': 'forced_movement', 'distance_ft': 10,
                       'direction': 'toward' if picked and picked[0] == 'pull' else 'away'}])
