"""Hearthfire's owned assets, aura and paid damage response.

Only reviewed qi_hearthfire declarations opt in. Saved catalogs supply all
numbers; this module never reads current authority during a fight.
Shared hearths/aura_contains readers serve qi_homefire_recovery and
qi_welcoming_flame; only live, owned assets supply sanctuary membership.
"""
from . import effect, hook

BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
HEARTH = BASE + 'kindled_hearth'
RECOVERY = BASE + 'homefire_recovery'
CARRY = BASE + 'carry_the_hearth'
BLOCK = 'qi_hearthfire'
SHIELD_ROUND_USE = 'hearth_shield_round_use'


@hook('compile_block')
def compile_row(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK, 'kind': spec['kind'], 'numbers': dict(numbers),
                 'choice_owner': True, 'keeps_compiling': spec.get('keeps_compiling', False)}]


@hook('compile_action')
def asset_action(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if any(e.get('type') == 'qi_hearth_asset' for e in typed.get('effects') or []):
        return action.model_copy(update={'target_kind': 'CELL', 'range_ft': 30,
            'parameters': {**action.parameters, 'typed': {**typed, 'area': None}}})
    if any(e.get('type') == 'qi_carry_hearth' for e in typed.get('effects') or []):
        return action.model_copy(update={'target_kind': 'SELF', 'range_ft': None,
            'parameters': {**action.parameters, 'typed': {**typed, 'area': None}}})


def hearths(engine, owner):
    """Live owned Hearths; a destroyed asset supplies no aura or response."""
    out = []
    for zone in engine.state.zones.values():
        profile = zone.trigger_profile.get('profile') or {}
        obj = engine.state.objects.get(profile.get('hearth_object', ''))
        if zone.active and zone.owner_id == owner.entity_id and obj is not None and not obj.destroyed and obj.current_hp > 0:
            out.append(zone)
    return out


def aura_contains(engine, zone, creature):
    from ..spatial_areas import zone_contains
    return zone_contains(engine, creature, zone)


def occupied(engine):
    return {cell for a in engine.state.actors.values() if a.active for cell in engine.grid.footprint_cells(a.position, engine._footprint(a))}


@effect('qi_hearth_asset', harmful=False)
def create_hearth(ctx, spec):
    from .. import zones
    from ..gate2_runtime_models import RuntimeObjectState
    position = ctx.intent.destination
    if position is None:
        raise ValueError('Choose an unoccupied space for the Hearth.')
    if not ctx.engine.grid.placement_legal(position, footprint=None,
            occupied_cells=occupied(ctx.engine)):
        raise ValueError('The Hearth needs an unoccupied space.')
    for zone in hearths(ctx.engine, ctx.actor):
        old = ctx.engine.state.objects[zone.trigger_profile['profile']['hearth_object']]
        ctx.engine._update_object(old.model_copy(update={'destroyed': True, 'current_hp': 0}), ctx.source, ctx.actor.entity_id)
        zones.remove(ctx.engine, zone, 'REPLACED')
    oid = 'object:hearth.' + ctx.actor.entity_id + '.' + str(ctx.engine.state.event_sequence + 1)
    hp = 3 * int(ctx.numbers['cl'])
    obj = RuntimeObjectState(object_id=oid, object_kind='cultivation_asset', position=position,
        owner_id=ctx.actor.entity_id, unattended=True, flammable=False, ac=13, current_hp=hp, maximum_hp=hp,
        damage_immunities=('FIRE', 'POISON', 'PSYCHIC'), destroyed=False,
        component={'name': 'Kindled Hearth', 'size': 'Small', 'blocks': False,
                   'source_cl': int(ctx.numbers['cl']), 'created_by': ctx.source})
    ctx.engine._update_object(obj, ctx.source, ctx.actor.entity_id)
    from .needle import ask, CHOICE, checkpoint_id
    from . import ai_controlled
    from ..target_knowledge import can_see
    allies = [a for a in ctx.engine.state.actors.values()
              if a.active and a.team_id == ctx.actor.team_id]
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
        'inside': [], 'triggers': [], 'visual': {'material': 'fire'}})


@hook('candidate_allowed')
def admission(engine, actor, candidate, action):
    typed = (action.parameters or {}).get('typed') or {} if action is not None else {}
    effects = typed.get('effects') or []
    if any(e.get('type') == 'qi_hearth_asset' for e in effects):
        p = candidate.destination
        return bool(p is not None and engine.grid.placement_legal(p, footprint=None,
            occupied_cells=occupied(engine)))
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
    allies = [a for a in ctx.engine.state.actors.values() if a.active and a.team_id == ctx.actor.team_id
              and (a is ctx.actor or can_see(ctx.engine, ctx.actor, a)
                   and ctx.engine.grid.distance_ft(a.position, zone.center) <= 5)]
    ids = [a.entity_id for a in allies]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'carry_hearth', ctx.actor.entity_id), ctx.actor,
        CHOICE + 'carry_hearth', ids, allow_decline=False, name='Carry the Hearth', feature_id=CARRY,
        labels={a.entity_id: a.display_name for a in allies}, preferred=[ctx.actor.entity_id],
        prompt='Carry the Hearth: choose yourself or a willing nearby ally to carry the empowered flame for 1 minute.')
    center = ctx.engine.state.actors[chosen[0]]
    if center is not ctx.actor:
        consent = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'carry_hearth_consent', center.entity_id), center,
            CHOICE + 'carry_hearth_consent', ['carry'], allow_decline=True, name='Carry the Hearth',
            labels={'carry': 'Carry the empowered flame'}, prompt='Carry the Hearth: carry the empowered flame for 1 minute?')
        if not consent:
            return
    # Carry is a temporary carrier policy on the existing eight-hour Hearth.
    # Retain one real object; when the minute ends it stays at its last position.
    profile = dict(zone.trigger_profile['profile'])
    profile.update(hearth_carrier=center.entity_id, carry_until=ctx.actor.turns_started + 10)
    # A fresh activation gets a fresh clock, including after a skipped slot
    # and revival at the same real turn count as the previous activation.
    zone.per_turn_triggered = {k: v for k, v in zone.per_turn_triggered.items()
                              if not k.startswith('custom_expiry_round_skipped:hearth_carry:')}
    zone.center = center.position
    zone.radius_cells = 4
    zone.trigger_profile = {**zone.trigger_profile, 'size_ft': 20, 'profile': profile}
    zone.affected_cells = zones._cells(ctx.engine, zone.center, zone.trigger_profile)
    from .retained_updates import record_zone_update
    record_zone_update(ctx.engine, zone)
    obj = ctx.engine.state.objects[profile['hearth_object']]
    ctx.engine._update_object(obj.model_copy(update={'position': center.position}), ctx.source, ctx.actor.entity_id)


def sync_carriers(engine):
    from .. import zones
    for zone in list(engine.state.zones.values()):
        profile = zone.trigger_profile.get('profile') or {}
        carrier = engine.state.actors.get(profile.get('hearth_carrier', ''))
        obj = engine.state.objects.get(profile.get('hearth_object', ''))
        if not zone.active or carrier is None or obj is None or obj.destroyed:
            continue
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
            profile = {k: v for k, v in profile.items() if k not in ('hearth_carrier', 'carry_until')}
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
    if obj is None or obj.destroyed or obj.current_hp <= 0:
        return
    engine._update_object(obj.model_copy(update={'destroyed': True, 'current_hp': 0}),
                          zone.source_definition_id, zone.owner_id)


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
            if owner.team_id != subject.team_id:
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
    if amount <= 0 or intent is None:
        return None
    remaining = amount
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        row = row_of(engine, owner.entity_id, BLOCK, 'shield')
        if row is None or owner.team_id != target.team_id or not typed_reactions._can_react(engine, owner, row):
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
    return {'reduction': amount - remaining} if remaining != amount else None


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
            if creature.team_id == owner.team_id:
                key = 'hearth_bloom:' + zone.zone_id
                if creature.turn_flags.get(key) != engine.state.round_number:
                    creature.turn_flags[key] = engine.state.round_number
                    te.run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'pb'}])
            else:
                fire_once(engine, zone, creature, ctx)


def fire_once(engine, zone, creature, ctx):
    from ..typed_executor import run_effects
    key = 'hearth_fire:' + creature.entity_id
    stamp = engine.state.round_number * 1000 + engine.state.current_slot_index
    if zone.per_turn_triggered.get(key) == stamp:
        return
    zone.per_turn_triggered[key] = stamp
    run_effects(ctx, [{'type': 'save', 'ability': 'dex', 'applies_to': 'target',
        'on_fail': [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 2, 'sides': 8},
                     'damage_types': ['fire', 'radiant']}], 'on_success': [{'type': 'half_damage'}]}])


@hook('zone_arrival')
def hearth_entry(engine, creature, start, end, forced):
    from .. import zones
    from ..spatial_areas import zone_contains
    from .rider_choices import intent_for
    for owner in engine.state.actors.values():
        if creature.team_id == owner.team_id:
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
