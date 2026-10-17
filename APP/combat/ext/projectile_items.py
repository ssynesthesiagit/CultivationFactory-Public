"""Fired material-unit lifecycle shared by interception and ammunition producers.

Only ammunition's committed native spend creates an in-flight identity. A
receipt follows one fired unit, separate from its original stack, through catch
or ground placement. It never restores the shooter's consumed ammunition or
creates a second copy. No interception means no saved receipt or event.
"""
from . import hook
STATE = 'condition:typed.fired_projectile_item'


def current(engine, viewer=None):
    """This exact typed strike's material projectile, or None for unknown delivery."""
    if viewer is not None and engine.state.actors.get(viewer.entity_id) is not viewer:
        return None
    from .attack_scope import current as attack_scope
    frame = attack_scope(engine)
    if frame is None:
        from ..attack_delivery import native_strike
        frame = native_strike(engine)
    value = (frame or {}).get('fired_projectile')
    if isinstance(value, dict):
        return dict(value)
    if viewer is not None:
        from . import run_strict
        candidates = run_strict('projectile_instance', engine, viewer)
        if len(candidates) > 1:
            raise ValueError('One actual projectile cannot have multiple instance producers')
        return dict(candidates[0]) if candidates else None
    return None


def settle(engine, interceptor, projectile, source, *, hand=None, destination=None):
    """Move one fired unit to a free hand or legal ground space, once only."""
    if engine.state.actors.get(interceptor.entity_id) is not interceptor:
        raise ValueError('Projectile settlement requires its live native interceptor')
    owned = any(row.get('feature_id') == source for row in getattr(engine, 'typed_passive_rows', {}).get(interceptor.entity_id, []))
    owned = owned or any(action.owner_id == interceptor.entity_id
        and (action.source_definition_id == source or (action.parameters.get('typed') or {}).get('source') == source)
        for action in engine.action_catalog.values())
    if not owned:
        raise ValueError('Projectile settlement requires an acquired source owned by the interceptor')
    actual = current(engine, interceptor)
    if actual != projectile or not actual:
        raise ValueError('Projectile settlement requires the actual committed shot')
    if any(c.condition_id == STATE and c.data.get('projectile_id') == actual['projectile_id']
           for actor in engine.state.actors.values() for c in actor.conditions.values()):
        raise ValueError('This projectile already has a settled location')
    data = {**actual, 'label': 'Caught ' + actual['item_name'] if hand else 'Deflected ' + actual['item_name'],
            'holder': interceptor.entity_id if hand else ''}
    if hand is not None:
        from .hand_occupancy import free_hands
        if hand not in free_hands(engine, interceptor):
            raise ValueError('Catching a projectile requires a free hand')
        data['hand'] = hand
    else:
        from ..object_placement import destinations
        if destination not in destinations(engine, interceptor, 15):
            raise ValueError('Deflection requires an unoccupied space within 15 feet')
        data.update(x=destination.x, y=destination.y, z=destination.z)
    if actual.get('unit') == 'weapon':
        from .thrown_equipment import settle_flight
        settle_flight(engine, actual, interceptor, source, hand=hand, destination=destination)
    lifetime = int(actual.get('lifetime_rounds', -1))
    from .effect_durations import round_token
    engine._apply_condition(interceptor, STATE, source, interceptor.entity_id,
                            expires_on=round_token(engine, lifetime) if lifetime > 0 else 'UNTIL_REMOVED', data=data)


@hook('hand_occupants')
def caught_hand(engine, actor):
    return {c.data['hand']: c.data['projectile_id'] for c in actor.conditions.values()
            if c.condition_id == STATE and c.data.get('holder') == actor.entity_id and c.data.get('hand')}


@hook('status_description')
def projectile_status(engine, actor, row, data):
    if not isinstance(row, dict) or row.get('condition_id') != STATE:
        return None
    if data.get('hand'):
        ending = ('Its original ammunition was spent.' if data.get('unit') != 'source_material'
                  else 'This is the one projectile from the creating attack; no ammunition or second item was created.')
        text = f"{actor.display_name} holds this one {data['item_name']} in one hand. {ending}"
    else:
        text = f"This one fired {data['item_name']} was deflected into the chosen unoccupied space; it makes no further attack."
    lifetime = int(data.get('lifetime_rounds', -1))
    duration = ('until this attack ends' if lifetime == 0 else str(lifetime)+' rounds, or until the object is moved'
                if lifetime > 0 else 'until the object is moved')
    return {'rules': text, 'duration': duration}



@hook('attack_damage_final')
def expire_source_projectile(engine, attacker, target, provenance, intent):
    for actor in engine.state.actors.values():
        for condition in list(actor.conditions.values()):
            if (condition.condition_id == STATE and condition.data.get('lifetime_rounds') == 0
                    and condition.data.get('creating_roll') == provenance.roll_id):
                engine._remove_condition_instance(actor, condition.instance_id, condition.source_definition_id, expected=condition)
