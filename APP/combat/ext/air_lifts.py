"""Updraft's finite lift and Sky-Sovereign's hostile flying save.

Uses native delayed-area contexts, holder expiry, physical impulse and flight
capabilities. Suspension is tied to the originating cylinder and ends on exit
or area removal, letting native falling decide how the creature lands.
"""
from copy import deepcopy
from . import effect, hook
from .needle import ask, checkpoint_id

UPDRAFT = 'TAL_AIR_UPDRAFT_GATE'
SKY = 'TAL_AIR_SKY_SOVEREIGN_INCARNATION'
SUSPENDED = 'condition:typed.updraft_suspended'


@hook('compile_action')
def lift_action(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') == SKY:
        typed = deepcopy(typed)
        # This is a start-turn save, never a second save on activation.
        typed['effects'] = [row for row in typed.get('effects', [])
                            if not (row.get('type') == 'save' and row.get('ability') == 'str')]
        return action.model_copy(update={'parameters': {**action.parameters, 'typed': typed}})
    if typed.get('source') != UPDRAFT:
        return None
    typed = deepcopy(typed)
    spec = typed.get('zone_spec') or {}
    spec.update(shape='sphere', size_ft=10, footprint_height_ft=30, difficult='all',
                triggers=[{'id': 'updraft_lift', 'on': ['enter', 'start'], 'who': 'any',
                           'effects': [{'type': 'updraft_lift'}]}])
    typed['zone_spec'] = spec
    typed['manual_inline_choice'] = True
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': typed}})


@hook('zone_trigger_context')
def lift_origin(ctx, zone, creature, moment):
    from ..zone_sources import of
    if (of(zone) or {}).get('mechanic_id') == UPDRAFT:
        ctx.damage_cache['updraft_zone'] = zone.zone_id


@hook('zone_created')
def draft_concentration(ctx, zone):
    if ctx.typed.get('source') == UPDRAFT:
        from .zone_concentration import bind
        bind(ctx, zone)


@effect('updraft_lift')
def lift(ctx, row):
    target = ctx.target
    if target is None:
        return
    from ..relations import relation, ALLY
    consent = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'updraft_consent', ctx.source, target.entity_id),
        target, 'choice:needle.updraft_consent', ['willing', 'resist'], name='Updraft Gate',
        preferred=['willing' if relation(ctx.engine, ctx.actor, target) == ALLY else 'resist'],
        labels={'willing': 'Willing: choose to rise up to 20 feet without spending movement',
                'resist': 'Unwilling: make a Strength save; failure lifts you 10 feet and suspends you'},
        prompt=f'Updraft Gate: {target.display_name} enters or starts its turn in the rising wind. Willingly rise, or resist with a Strength save?')
    if consent and consent[0] == 'willing':
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'updraft_height', ctx.source, target.entity_id),
            target, 'choice:needle.updraft_height', ['0', '5', '10', '15', '20'], name='Updraft Gate',
            labels={str(n): f'Rise {n} feet without spending movement' for n in (0, 5, 10, 15, 20)},
            prompt=f'Updraft Gate: how far will {target.display_name} rise, up to 20 feet?')
        if chosen and int(chosen[0]):
            rise(ctx, target, int(chosen[0]))
    else:
        from ..typed_executor import run_effects
        run_effects(ctx, [{'type': 'save', 'ability': 'str', 'applies_to': 'target',
            'on_fail': [{'type': 'updraft_failed'}], 'on_success': [{'type': 'updraft_resisted'}]}])


def rise(ctx, target, feet):
    from ..movement_paths import resolve
    path = tuple(target.position.model_copy(update={'z': target.position.z + i}) for i in range(feet // 5 + 1))
    resolve(ctx.engine, target, path, ctx.source, kind='forced', feet=feet, intent=ctx.intent,
            source_actor_id=ctx.actor.entity_id, ctx=ctx)


@effect('updraft_failed')
def failed(ctx, row):
    from .effect_durations import holder_next_turn
    ctx.engine._apply_condition(ctx.target, SUSPENDED, ctx.source, ctx.actor.entity_id,
        expires_on=holder_next_turn(ctx.target), data={'flight_suspended': 1,
            'zone_id': ctx.damage_cache.get('updraft_zone', ''),
            'label': 'Updraft Gate: suspended until your next turn starts, or until you leave the rising wind'})
    rise(ctx, ctx.target, 10)


@effect('updraft_resisted')
def resisted(ctx, row):
    ctx.engine._apply_condition(ctx.target, 'condition:typed.updraft_resisted', ctx.source, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'updraft_difficult': ctx.damage_cache.get('updraft_zone', ''),
            'label': 'Updraft Gate: its rising wind is Difficult Terrain for you while the area lasts'})


@hook('difficult_zone_exempt')
def draft_difficult(engine, actor, zone):
    from ..zone_sources import of
    if (of(zone) or {}).get('mechanic_id') == UPDRAFT:
        return not any(c.condition_id == 'condition:typed.updraft_resisted'
            and c.data.get('updraft_difficult') == zone.zone_id for c in actor.conditions.values())
    return None


@hook('flight_grant_allowed')
def suspended_here(engine, actor, condition):
    if condition.condition_id != SUSPENDED:
        return None
    from ..spatial_areas import zone_contains
    zone = engine.state.zones.get(condition.data.get('zone_id'))
    return bool(zone and zone.active and zone_contains(engine, actor, zone))


@hook('zone_arrival')
def leaving_draft(engine, mover, start, end, forced):
    from .riders_shared import remove_benefit_condition
    for condition in list(mover.conditions.values()):
        if condition.condition_id == SUSPENDED and not suspended_here(engine, mover.model_copy(update={'position': end}), condition):
            remove_benefit_condition(engine, mover, condition, 'LEFT_UPDRAFT')


@hook('turn_start')
def sky_enemy_save(engine, target):
    from .states import active
    from ..relations import relation, ENEMY
    from ..flight import profile
    from ..falling import supported
    from ..typed_executor import Context, run_effects
    from .needle import numbers_of
    if not profile(engine, target).speed_ft or supported(engine, target) or target.climbing:
        return
    for owner in engine.state.actors.values():
        if not active(engine, owner, 'sky_sovereign_incarnation') or relation(engine, owner, target) != ENEMY or engine._distance_actor_to_actor(owner, target) > 60:
            continue
        action = next((a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id and (a.parameters.get('typed') or {}).get('source') == SKY), None)
        if action is None:
            continue
        ctx = Context(engine, owner, action, getattr(engine, '_active_intent', None),
                      {'source': SKY, 'numbers': numbers_of(engine, owner), 'duration': {'kind': 'instant'}}, [target], target)
        run_effects(ctx, [{'type': 'save', 'ability': 'str', 'applies_to': 'target',
            'on_fail': [{'type': 'sky_half_flight'}], 'on_success': []}])


@effect('sky_half_flight')
def half_flight(ctx, row):
    from .effect_durations import holder_next_turn
    ctx.engine._apply_condition(ctx.target, 'condition:typed.sky_half_flight', ctx.source, ctx.actor.entity_id,
        expires_on=holder_next_turn(ctx.target), data={'fly_speed_percent': 50,
            'label': 'Sky-Sovereign Incarnation: Fly Speed halved until your next turn starts'})


def has_air(engine, actor):
    """Only explicit vacuum/Created Air scene facts; ordinary maps have air."""
    from ..spatial_areas import zone_contains
    rows = [c.data for c in actor.conditions.values()]
    rows += [(z.trigger_profile.get('profile') or {}) for z in engine.state.zones.values()
             if z.active and zone_contains(engine, actor, z)]
    return not any(r.get('airless') for r in rows) or any(r.get('created_air') for r in rows)


@hook('state_allowed')
def sky_in_air(engine, actor, condition):
    if condition.condition_id == 'condition:typed.state.sky_sovereign_incarnation':
        return has_air(engine, actor)


@hook('flight_grant_allowed')
def sky_flight_air(engine, actor, condition):
    action = engine.action_catalog.get(condition.source_definition_id)
    if action is not None and (action.parameters.get('typed') or {}).get('source') == SKY:
        return has_air(engine, actor)


@hook('candidate_allowed')
def sky_needs_air(engine, actor, candidate, action):
    if action is not None and (action.parameters.get('typed') or {}).get('source') == SKY:
        return has_air(engine, actor)


def air_control_count(engine, actor):
    """Current accounting: up to six Incarnation grants do not consume control."""
    from .air_currents import currents
    from .states import active
    zones = currents(engine, actor)
    exempt = [z for z in zones if z.trigger_profile.get('sky_control_exempt')]
    return len(zones) - min(6, len(exempt)) if active(engine, actor, 'sky_sovereign_incarnation') else len(zones)


@hook('technique_used')
def sovereign_currents(ctx):
    from .air_currents import currents
    from .states import active
    if not active(ctx.engine, ctx.actor, 'sky_sovereign_incarnation'):
        return
    areas = currents(ctx.engine, ctx.actor)
    remaining = max(0, 6 - sum(bool(z.trigger_profile.get('sky_control_exempt')) for z in areas))
    for zone in areas:
        if remaining and not zone.trigger_profile.get('sky_control_exempt'):
            zone.trigger_profile['sky_control_exempt'] = 1
            ctx.engine._append_event('ZONE_CREATED', zone.source_definition_id, actor_id=zone.owner_id,
                payload={'zone': zone.model_dump(mode='json')})
            remaining -= 1


@hook('event')
def draft_ended(engine, event_type, kwargs):
    if event_type != 'ZONE_REMOVED':
        return
    zone_id = (kwargs.get('payload') or {}).get('zone_id')
    from .riders_shared import remove_benefit_condition
    for actor in engine.state.actors.values():
        for condition in list(actor.conditions.values()):
            if (condition.condition_id == SUSPENDED and condition.data.get('zone_id') == zone_id
                    or condition.condition_id == 'condition:typed.updraft_resisted'
                    and condition.data.get('updraft_difficult') == zone_id):
                remove_benefit_condition(engine, actor, condition, 'UPDRAFT_ENDED')
