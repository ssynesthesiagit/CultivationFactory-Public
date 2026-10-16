"""Physical object consumers for newly constructed Trap devices.

Reuses native RuntimeObjectState and object damage. Old zone-only traps lack
physical_device and remain unchanged. Zone and object provenance share one
stable id; destroying a device removes its zone and its fragile Acid load.
"""
from . import hook, placed
from ..gate2_runtime_models import RuntimeObjectState


@hook('event')
def device_events(engine, event_type, args):
    payload = args.get('payload') or {}
    if event_type == 'ZONE_CREATED':
        raw = payload.get('zone') or {}
        zid = raw.get('zone_id')
        zone = engine.state.zones.get(zid)
        data = placed.data(zone) if zone else {}
        if not zone or data.get('tag') != 'trap' or not data.get('physical_device'):
            return
        oid = 'object:trap:' + zid
        if oid in engine.state.objects:
            return
        hp = 2 * int(data.get('cl') or 1)
        obj = RuntimeObjectState(object_id=oid, object_kind='TRAP', position=zone.center,
            owner_id=zone.owner_id, unattended=True, ac=int(zone.trigger_profile.get('numbers', {}).get('save_dc') or 10),
            current_hp=hp, maximum_hp=hp, component={'trap_zone':zid, 'created_by':zone.source_definition_id})
        engine._update_object(obj, zone.source_definition_id, zone.owner_id)
    elif event_type == 'ZONE_REMOVED':
        zid = payload.get('zone_id')
        obj = engine.state.objects.get('object:trap:' + str(zid))
        if obj and not obj.destroyed:
            engine._update_object(obj.model_copy(update={'destroyed':True}), obj.component['created_by'], obj.owner_id)
    elif event_type == 'OBJECT_UPDATED':
        raw = payload.get('object') or {}
        obj = engine.state.objects.get(raw.get('object_id'))
        if not obj or not obj.destroyed or not obj.component.get('trap_zone'):
            return
        zone = engine.state.zones.get(obj.component['trap_zone'])
        if not zone or not zone.active:
            return
        data = placed.data(zone)
        if data.get('payload', {}).get('spec', {}).get('fragile'):
            from copy import deepcopy
            stock = deepcopy(data['payload'])
            stock['remaining'] = 0
            placed.update(engine, zone, payload=stock)
        placed.drop(engine, zone, 'DESTROYED')


@hook('object_target_cells')
def cells(engine, obj):
    zone = engine.state.zones.get((obj.component or {}).get('trap_zone'))
    return tuple(zone.affected_cells) if zone else None
