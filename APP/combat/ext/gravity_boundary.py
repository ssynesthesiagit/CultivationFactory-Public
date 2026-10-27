"""Event Horizon Prison's Strength save prevents a voluntary boundary crossing.

The existing canonical zone supplies ownership, geometry, Concentration and DC.
Its turn-start Constitution damage remains in typed data. Teleports require their
own opposed Cultivation Check; they are not silently treated as walking.
"""
from . import hook

PRISON = 'tianxia.talent.gravity.event_horizon_prison'


@hook('movement_attempt')
def horizon(engine, mover, previous, nxt, intent):
    for zone in sorted(engine.state.zones.values(), key=lambda z:z.zone_id):
        action = engine.action_catalog.get(zone.source_definition_id)
        if not zone.active or not action or action.parameters.get('typed',{}).get('source') != PRISON:
            continue
        from ..spatial_areas import zone_contains
        if not zone_contains(engine, mover, zone, at=previous) or zone_contains(engine, mover, zone, at=nxt):
            continue
        dc = int(zone.trigger_profile['numbers']['save_dc'])
        roll = engine._roll_save(mover,'STR',dc,zone.source_definition_id)
        if roll is not None and roll.total < dc:
            return {'stop':True,'source_id':zone.source_definition_id,
                    'label':f'Event Horizon Prison stops {mover.display_name} at its boundary after a failed Strength save.'}
    return None
