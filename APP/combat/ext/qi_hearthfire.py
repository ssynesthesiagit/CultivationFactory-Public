"""Hearthfire's owned assets, aura and paid damage response.

Only reviewed qi_hearthfire declarations opt in. Saved catalogs supply all
numbers; this module never reads current authority during a fight.
"""
from . import effect, hook
from ..relations import relation, ALLY, ENEMY

BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
HEARTH = BASE + 'kindled_hearth'
RECOVERY = BASE + 'homefire_recovery'
CARRY = BASE + 'carry_the_hearth'
BLOCK = 'qi_hearthfire'
SHIELD_ROUND_USE = 'hearth_shield_round_use'


@hook('compile_block')
def compile_row(block, spec, row, numbers):
    if block == BLOCK:
        minimum = {'kindled_hearth': 3, 'homefire_recovery': 6, 'hearthward_pavilion': 10, 'carry_the_hearth': 14, 'flame_that_welcomes_all': 18}.get(row.get('feature_id', '').rsplit('.', 1)[-1], 99)
        if int(numbers.get('cl', 0)) < minimum:
            return []
        return [{**row, 'block': BLOCK, 'kind': spec['kind'], 'numbers': dict(numbers),
                 'choice_owner': True, 'keeps_compiling': spec.get('keeps_compiling', False)}]


@hook('compile_action')
def asset_action(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if any(e.get('type') == 'qi_hearth_asset' for e in typed.get('effects') or []):
        return action.model_copy(update={'target_kind': 'OBJECT' if action.parameters.get('hearth_empower_existing') else 'CELL', 'range_ft': 30,
            'parameters': {**action.parameters, 'typed': {**typed, 'area': None}}})
    if any(e.get('type') in ('qi_carry_hearth', 'qi_welcome') for e in typed.get('effects') or []):
        return action.model_copy(update={'target_kind': 'SELF', 'range_ft': None,
            'parameters': {**action.parameters, 'typed': {**typed, 'area': None}}})


def hearths(engine, owner):
    """Live owned Hearths; a destroyed asset supplies no aura or response."""
    out = []
    for zone in engine.state.zones.values():
        profile = zone.trigger_profile.get('profile') or {}
        obj = engine.state.objects.get(profile.get('hearth_object', ''))
        if zone.active and zone.owner_id == owner.entity_id and not profile.get('pavilion') and not profile.get('welcome') and not profile.get('suppressed') and obj is not None and not obj.suppressed and not obj.destroyed and obj.current_hp > 0:
            out.append(zone)
    return out


def aura_contains(engine, zone, creature):
    from ..spatial_areas import zone_contains
    return zone_contains(engine, creature, zone)


def occupied(engine):
    return {cell for a in engine.state.actors.values() if a.active for cell in engine.grid.footprint_cells(a.position, engine._footprint(a))}


def create_hearth_object(engine,owner,source,numbers,position,*,existing=None):
    """One family producer for combat and Journey, using the owner's Asset API."""
    from .. import asset_anchor_runtime as assets
    from ..gate2_runtime_models import RuntimeObjectState
    cl=int(numbers['cl']);hp=3*cl
    component={'name':'Kindled Hearth','size':'Small','blocks':False,'source_cl':cl,
        'created_by':source,'bright_ft':15,'dim_ft':30,
        'condition_immunities':['CHARMED','FRIGHTENED','POISONED','PRONE'],
        'save_bonus':int(numbers['pb'])+int(numbers['key_mod'])}
    if existing is None:
        return assets.create(engine,owner,source,{'name':'Kindled Hearth','kind':'cultivation_asset','ac':13,'hp':hp,
            'source_cl':cl,'height_ft':5,'group':'hearthfire','immune':('FIRE','POISON','PSYCHIC')},position,component=component)
    obj=existing.model_copy(update={'ac':13,'current_hp':hp,'maximum_hp':hp,
        'damage_immunities':('FIRE','POISON','PSYCHIC'),
        'component':{**(existing.component or {}),**component,'hearth_original':existing.model_dump(mode='json')}})
    engine._update_object(obj,source,owner.entity_id)
    return obj


def retire_hearth_object(engine,obj,source,owner_id):
    """End empowerment without destroying the real item underneath it."""
    original=(obj.component or {}).get('hearth_original')
    if original:
        from ..gate2_runtime_models import RuntimeObjectState
        restored=RuntimeObjectState.model_validate(original)
        restored=restored.model_copy(update={'position':obj.position,'unattended':obj.unattended,
            'destroyed':bool(obj.destroyed),'current_hp':min(restored.current_hp or 0,obj.current_hp or 0)})
        engine._update_object(restored,source,owner_id)
    else:
        from ..asset_anchor_runtime import retire
        retire(engine,obj,source)


@effect('qi_hearth_asset', harmful=False)
def create_hearth(ctx, spec):
    from .. import zones
    from ..gate2_runtime_models import RuntimeObjectState
    from .qi_hearthfire_items import empowerable
    existing = ctx.engine.state.objects.get(next(iter(ctx.intent.target_ids), '')) if spec.get('existing') else None
    if spec.get('existing') and (existing is None or not empowerable(existing)):
        raise ValueError('Choose an existing contained flame, such as a lit native lantern or brazier.')
    position = existing.position if existing is not None else ctx.intent.destination
    if position is None:
        raise ValueError('Choose an unoccupied space for the Hearth.')
    if existing is None and not ctx.engine.grid.placement_legal(position, footprint=None,
            occupied_cells=occupied(ctx.engine)):
        raise ValueError('The Hearth needs an unoccupied space.')
    for zone in hearths(ctx.engine, ctx.actor):
        zones.remove(ctx.engine, zone, 'REPLACED')
    if existing is not None:
        existing = ctx.engine.state.objects[existing.object_id]
    obj = create_hearth_object(ctx.engine,ctx.actor,ctx.source,ctx.numbers,position,existing=existing)
    oid = obj.object_id
    from .needle import ask, CHOICE, checkpoint_id
    from . import ai_controlled
    from ..target_knowledge import can_see
    allies = [a for a in ctx.engine.state.actors.values()
              if a.active and relation(ctx.engine,ctx.actor,a)==ALLY]
    ids = [a.entity_id for a in allies]
    if ai_controlled(ctx.engine, ctx.actor):
        chosen = [a.entity_id for a in allies if can_see(ctx.engine, ctx.actor, a)]
    else:
        chosen = ask(ctx.engine, ctx.intent,
            checkpoint_id(ctx.engine, 'kindled_hearth_recipients', ctx.actor.entity_id), ctx.actor,
            CHOICE + 'kindled_hearth_recipients', ids,
            labels={a.entity_id: a.display_name for a in allies},
            prompt='Kindled Hearth: designate which allies receive its protection while within 15 feet for 8 hours.',
            minimum=0, maximum=len(ids), allow_decline=True, default='all', name='Kindled Hearth recipients',
            feature_id=HEARTH, preferred=ids)
    zones.create(ctx, {'name': 'Kindled Hearth', 'shape': 'sphere', 'size_ft': 15,
        'duration': {'kind': 'hours', 'amount': 8}, 'profile': {'hearth_object': oid,
            'chosen_recipients': list(chosen)},
        'inside': [], 'triggers': [], 'visual': {'material': 'fire', 'light': {'radius_ft': 15, 'level': 'bright', 'dim_radius_ft': 30}}})


@hook('candidate_allowed')
def admission(engine, actor, candidate, action):
    typed = (action.parameters or {}).get('typed') or {} if action is not None else {}
    effects = typed.get('effects') or []
    if any(e.get('type') == 'qi_hearth_asset' for e in effects):
        if action.parameters.get('hearth_empower_existing'):
            from .qi_hearthfire_items import empowerable
            obj = engine.state.objects.get(next(iter(candidate.target_ids), ''))
            return obj is not None and empowerable(obj)
        p = candidate.destination
        from ..asset_anchor_runtime import legal_placement
        return bool(p is not None and legal_placement(engine,(p,),5))
    if any(e.get('type') == 'qi_carry_hearth' for e in effects):
        return bool(hearths(engine, actor))


@effect('qi_carry_hearth', harmful=False)
def carry_hearth(ctx, spec):
    from .. import zones
    from .needle import ask, CHOICE, checkpoint_id
    from ..target_knowledge import can_see
    active = hearths(ctx.engine, ctx.actor)
    if not active:
        raise ValueError('Carry the Hearth requires an active Hearth.')
    zone = active[0]
    # The actual empowered item is required. An ally must be adjacent to it;
    # accepting the invitation records custody, not a duplicated flame.
    from .qi_hearthfire_items import held_item
    obj = ctx.engine.state.objects[zone.trigger_profile['profile']['hearth_object']]
    allies = [a for a in ctx.engine.state.actors.values() if a.active
              and (a is ctx.actor or held_item(ctx.engine,obj,a))]
    from .qi_path import armament_condition, armament_point
    armament = armament_condition(ctx.actor)
    ids = [a.entity_id for a in allies] + (['domain_armament'] if armament is not None else [])
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'carry_hearth', ctx.actor.entity_id), ctx.actor,
        CHOICE + 'carry_hearth', ids, allow_decline=False, name='Carry the Hearth', feature_id=CARRY,
        labels={**{a.entity_id: a.display_name for a in allies}, 'domain_armament': 'Your manifested Domain Armament'}, preferred=[ctx.actor.entity_id],
        automatic_options=[a.entity_id for a in allies if a is ctx.actor or can_see(ctx.engine,ctx.actor,a)] + (['domain_armament'] if armament is not None else []),
        prompt='Carry the Hearth: choose yourself, your Domain Armament, or a willing creature already carrying the real empowered item. It follows that center for 1 minute; Bonus Action and 4 Qi.')
    is_armament = chosen[0] == 'domain_armament'
    center = ctx.actor if is_armament else ctx.engine.state.actors[chosen[0]]
    if center is not ctx.actor:
        consent = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'carry_hearth_consent', center.entity_id), center,
            CHOICE + 'carry_hearth_consent', ['carry'], allow_decline=True, name='Carry the Hearth',
            labels={'carry': 'Carry the empowered flame'}, prompt='Carry the Hearth: carry the empowered flame for 1 minute?')
        if not consent:
            return
    # Carry is a temporary carrier policy on the existing eight-hour Hearth.
    # Retain one real object; when the minute ends it stays at its last position.
    profile = dict(zone.trigger_profile['profile'])
    profile.update(hearth_carrier=center.entity_id, carry_until=ctx.actor.turns_started + 10,
                   carry_armament=int(is_armament))
    # A fresh activation gets a fresh clock, including after a skipped slot
    # and revival at the same real turn count as the previous activation.
    zone.per_turn_triggered = {k: v for k, v in zone.per_turn_triggered.items()
                              if not k.startswith('custom_expiry_round_skipped:hearth_carry:')}
    from ..gate2_runtime_models import Position
    point = armament_point(ctx.actor) if is_armament else None
    position = Position(x=point[0], y=point[1]) if point else center.position
    zone.center = position
    zone.radius_cells = 4
    zone.trigger_profile = {**zone.trigger_profile, 'size_ft': 20, 'profile': profile}
    zone.affected_cells = zones._cells(ctx.engine, zone.center, zone.trigger_profile)
    from .retained_updates import record_zone_update
    record_zone_update(ctx.engine, zone)
    obj = ctx.engine.state.objects[profile['hearth_object']]
    ctx.engine._update_object(obj.model_copy(update={'position': position}), ctx.source, ctx.actor.entity_id)


def sync_carriers(engine):
    from .. import zones
    for zone in list(engine.state.zones.values()):
        profile = zone.trigger_profile.get('profile') or {}
        carrier = engine.state.actors.get(profile.get('hearth_carrier', ''))
        obj = engine.state.objects.get(profile.get('hearth_object', ''))
        if not zone.active or carrier is None or obj is None or obj.destroyed:
            continue
        from .qi_path import armament_condition, armament_point
        from ..gate2_runtime_models import Position
        if profile.get('carry_armament'):
            if armament_condition(carrier) is None:
                continue
            point = armament_point(carrier)
            new = Position(x=point[0], y=point[1])
        else:
            new = carrier.position
        if zone.center != new:
            zone.center = new
            zone.affected_cells = zones._cells(engine, new, zone.trigger_profile)
            from .retained_updates import record_zone_update
            record_zone_update(engine, zone)
            engine._update_object(obj.model_copy(update={'position': new}), zone.source_definition_id, zone.owner_id)


@hook('movement_landed')
def sync_carrier_after_step(engine, mover, previous, nxt, intent, forced):
    """Sync carried assets before responses and hazards at the entered step."""
    sync_carriers(engine)


def expire_carry(engine, actor, *, nominal=False):
    from .. import zones
    from .effect_durations import custom_turn_due
    from .retained_updates import record_zone_update
    for zone in hearths(engine, actor):
        profile = zone.trigger_profile.get('profile') or {}
        until = profile.get('carry_until')
        if until is None:
            continue
        previous = dict(zone.per_turn_triggered)
        if custom_turn_due(actor, until, zone.per_turn_triggered, 'hearth_carry', nominal=nominal):
            profile = {k: v for k, v in profile.items() if k not in ('hearth_carrier', 'carry_until', 'carry_armament')}
            zone.trigger_profile = {**zone.trigger_profile, 'size_ft': 15, 'profile': profile}
            zone.radius_cells = 3
            zone.affected_cells = zones._cells(engine, zone.center, zone.trigger_profile)
            record_zone_update(engine, zone)
        elif zone.per_turn_triggered != previous:
            record_zone_update(engine, zone)


@hook('nominal_slot_boundary')
def nominal_carry_expiry(engine, actor, checkpoint):
    if checkpoint == 'START_OF_TURN':
        expire_carry(engine, actor, nominal=True)


def retire_zone_asset(engine, kwargs):
    """The object a zone empowered ends with that zone, whatever ended it.

    zones.remove() only deactivates the zone, so a removed zone's object would
    otherwise stay a live, positive-HP cultivation asset: an eight-hour Hearth
    that expires leaves a targetable flame with the Hearth's immunities, and a
    later Hearth leaves it untouched because replacement reads live zones only.
    Retiring here covers every removal reason (DURATION_ENDED, REPLACED,
    HEARTH_DESTROYED and any future one) at the single event the engine already
    appends, so no caller has to remember. An object already destroyed (the
    replacement and destruction paths retire it first) is left alone.
    Carry the Hearth is only a temporary carrier policy on a still-live zone, so
    its own end never removes the zone and never reaches here.
    """
    zone = engine.state.zones.get(str((kwargs.get('payload') or {}).get('zone_id') or ''))
    if zone is None:
        return
    profile = zone.trigger_profile.get('profile') or {}
    obj = engine.state.objects.get(profile.get('hearth_object', ''))
    if obj is None:
        return
    retire_hearth_object(engine,obj,zone.source_definition_id,zone.owner_id)


@hook('event', nested=True)
def lifecycle(engine, event_type, kwargs):
    if event_type == 'ZONE_REMOVED':
        retire_zone_asset(engine, kwargs)
        return
    if event_type not in ('OBJECT_UPDATED', 'MOVEMENT_COMMITTED', 'TELEPORT_COMMITTED'):
        return
    if event_type != 'OBJECT_UPDATED':
        sync_carriers(engine)
        return
    from .. import zones
    for zone in list(engine.state.zones.values()):
        obj = engine.state.objects.get((zone.trigger_profile.get('profile') or {}).get('hearth_object', ''))
        if zone.active and obj is not None and (obj.destroyed or obj.current_hp <= 0):
            zones.remove(engine, zone, 'HEARTH_DESTROYED')


@hook('save_effects')
def hearth_save(ctx, subject, ability, fail_effects, success_effects, categories):
    from ..typed_executor import _walk_rows
    names = {str(e.get('condition', '')).lower() for e in _walk_rows(fail_effects)}
    protected = 'frightened' in names or bool(set(categories) & {'environmental_cold', 'environmental_exposure_exhaustion'})
    if protected:
        for owner in ctx.engine.state.actors.values():
            if relation(ctx.engine,owner,subject)!=ALLY:
                continue
            if any(subject.entity_id in (z.trigger_profile.get('profile') or {}).get('chosen_recipients', [])
                   and aura_contains(ctx.engine, z, subject) for z in hearths(ctx.engine, owner)):
                return {'modes': ['ADVANTAGE']}


@hook('choice_reactors')
def choice_owners(engine):
    from .passive_rows import row_of
    return [a.entity_id for a in engine.state.actors.values()
            if row_of(engine, a.entity_id, BLOCK, 'shield') and hearths(engine, a)]


@hook('final_damage')
def shield_the_flame(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    from .. import typed_reactions
    from ..gate2_runtime_models import DiceSpec
    from ..paid_relocation import activation
    from .passive_rows import row_of
    from .choice_costs import payable
    from .needle import ask, CHOICE, checkpoint_id
    from .choice_prompt import action_context
    intent = intent or getattr(engine, '_active_intent', None)
    if amount <= 0:
        return None
    from .qi_hearthfire_sanctuary import hearthward_reduction
    automatic = hearthward_reduction(engine,target,amount,damage_type,source_id,source_actor_id,intent)
    if intent is None:
        return automatic
    remaining = amount - (automatic['reduction'] if automatic else 0)
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        row = row_of(engine, owner.entity_id, BLOCK, 'shield')
        if row is None or relation(engine,owner,target)!=ALLY or not typed_reactions._can_react(engine, owner, row):
            continue
        if owner.turn_flags.get(SHIELD_ROUND_USE) == engine.state.round_number:
            continue
        active = [z for z in hearths(engine, owner) if aura_contains(engine, z, target)]
        payment = payable(owner, 'resource:core.qi', 1)
        if not active or payment is None or remaining <= 0:
            continue
        from . import ai_controlled
        from ..target_knowledge import located
        if ai_controlled(engine, owner) and not located(engine, owner, target):
            continue
        n = row['numbers']; cl = int(n['cl'])
        count = 3 if cl >= 18 else 2 if cl >= 14 else 1
        if any((z.trigger_profile.get('profile') or {}).get('hearth_carrier') for z in active):
            count = 2  # Carry the Hearth's explicit replacement, even at CL18.
        # The paid Reaction is chosen against a named cause. Delayed and off-turn
        # damage arrives with no enclosing action of its own, so the prompt is
        # built from the damage's own source (its catalog action, not the outer
        # End turn action) and says so in words a newcomer can read.
        context = action_context(engine, engine.state.actors.get(source_actor_id or ''), source_id, target)
        cause = context['action_name'] or 'an ongoing effect'
        choice = ask(engine, intent, checkpoint_id(engine, 'hearth_shield', owner.entity_id, target.entity_id, source_id),
            owner, CHOICE + 'hearth_shield', ['shield'], allow_decline=True, name='Shield the Flame', feature_id=RECOVERY,
            target_id=target.entity_id, payment=payment, prompt_context=context,
            labels={'shield': f'Reaction and 1 Qi: reduce damage by {count}d8 + your key modifier'},
            prompt=f'Shield the Flame: {target.display_name} is taking {remaining} {damage_type} damage from {cause} in your Hearth aura. '
                   f'Spend your Reaction and 1 Qi to reduce it by {count}d8 + your key modifier?')
        if not choice:
            continue
        with activation(engine, owner, RECOVERY):
            payment.pay(engine, owner, RECOVERY)
            typed_reactions._open(engine, row, owner, (target.entity_id,), 'FINAL_DAMAGE')
            typed_reactions.spend_reaction(engine, owner, row)
            # Generic turn-start cleanup retains keys containing ``_round_``.
            owner.turn_flags[SHIELD_ROUND_USE] = engine.state.round_number
            roll = engine.roller.roll(DiceSpec(count=count, sides=8, modifier=int(n['key_mod'])),
                actor_id=owner.entity_id, reason='HEARTH_SHIELD_REDUCTION')
            engine._record_roll(roll)
            reduction = min(remaining, max(0, roll.total))
            remaining -= reduction
            engine._append_event('REACTION_RESOLVED', RECOVERY, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                payload={'ability': 'Shield the Flame', 'reduction': reduction, 'roll_id': roll.roll_id})
    if remaining == amount:
        return None
    result = {'reduction': amount - remaining}
    if automatic:
        result['settle'] = automatic['settle']
    return result


@hook('turn_start')
def hearth_start(engine, creature):
    from .. import typed_executor as te
    from .. import zones
    from .rider_choices import intent_for
    expire_carry(engine, creature)
    sync_carriers(engine)
    for owner in list(engine.state.actors.values()):
        for zone in hearths(engine, owner):
            profile = zone.trigger_profile.get('profile') or {}
            if not profile.get('hearth_carrier') or not aura_contains(engine, zone, creature):
                continue
            action = engine.action_catalog[zone.source_definition_id]
            ctx = zones.delayed_area_effect_context(engine, zone, creature,
                typed={'numbers': zone.trigger_profile['numbers']}, owner=owner, action=action,
                intent=intent_for(engine), moment='start')
            if relation(engine,owner,creature)==ALLY:
                key = 'hearth_bloom_round_:' + zone.zone_id
                if creature.turn_flags.get(key) != engine.state.round_number:
                    creature.turn_flags[key] = engine.state.round_number
                    te.run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'pb'}])
            elif relation(engine,owner,creature)==ENEMY:
                fire_once(engine, zone, creature, ctx)


def fire_once(engine, zone, creature, ctx):
    from ..typed_executor import run_effects
    key = 'hearth_fire:' + creature.entity_id
    stamp = engine.state.round_number * 1000 + engine.state.current_slot_index
    if zone.per_turn_triggered.get(key) == stamp:
        return
    zone.per_turn_triggered[key] = stamp
    from .retained_updates import record_zone_update
    record_zone_update(engine, zone)
    run_effects(ctx, [{'type': 'save', 'ability': 'dex', 'applies_to': 'target',
        'on_fail': [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8},
                     'damage_types': ['fire', 'radiant']}], 'on_success': [{'type': 'half_damage'}]}])


@hook('zone_arrival')
def hearth_entry(engine, creature, start, end, forced):
    from .. import zones
    from ..spatial_areas import zone_contains
    from .rider_choices import intent_for
    for owner in engine.state.actors.values():
        if relation(engine,owner,creature)!=ENEMY:
            continue
        for zone in hearths(engine, owner):
            if not (zone.trigger_profile.get('profile') or {}).get('hearth_carrier'):
                continue
            if zone_contains(engine, creature, zone, at=end) and not zone_contains(engine, creature, zone, at=start):
                action = engine.action_catalog[zone.source_definition_id]
                ctx = zones.delayed_area_effect_context(engine, zone, creature,
                    typed={'numbers': zone.trigger_profile['numbers']}, owner=owner, action=action,
                    intent=intent_for(engine), moment='enter')
                fire_once(engine, zone, creature, ctx)


@hook('compile_bundle')
def seal_family_numbers(bundle, info):
    """Carry the acquired source's full native DC/CL/PB into camp consumers."""
    rows=bundle.get('typed_passives',())
    if not any(r.get('block')==BLOCK for r in rows):
        return bundle
    stats=info['owner_sheet'].get('ability_scores_and_statistics') or {}
    wisdom=next((int(r['modifier']) for r in stats.get('abilities',()) if r.get('ability')=='WIS'),0)
    perception=next((int(r['bonus']) for r in stats.get('skills',()) if str(r.get('skill','')).casefold()=='perception'),wisdom)
    return {**bundle,'hearthfire_checks':{'perception':perception},'typed_passives':[{**r,'numbers':{**r['numbers'],**info['numbers']}}
        if r.get('block')==BLOCK else r for r in rows]}
