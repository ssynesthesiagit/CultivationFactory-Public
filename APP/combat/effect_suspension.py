"""Transactional instantaneous suspension of represented zones/conditions.

Primordial Syllable uses this general scope after selecting eligible sources.
The caller owns authority/area eligibility. Existing expiry and concentration
continue; restoration never revives an effect removed during the scope. Every
change is evented; pauses and failures unwind with the enclosing transaction.
"""
from contextlib import contextmanager


@contextmanager
def suspend(engine, source, zones=(), conditions=()):
    from . import zones as zone_rules
    from .ext.retained_updates import record_zone_update, record_instance_update
    saved = []
    first_event = len(engine.events)
    try:
        for zone in zones:
            if not zone.active:
                continue
            zone.active = False
            saved.append(('zone', zone, None))
            record_zone_update(engine,zone)
        for actor, condition in conditions:
            before = dict(condition.data)
            condition.data = {**before, 'suppressed': 1}
            saved.append(('condition', condition, (actor, before)))
            record_instance_update(engine,actor,'condition',condition.instance_id,condition)
        zone_rules.sync_inside(engine, source)
        yield
    finally:
        for kind, item, details in reversed(saved):
            if kind == 'zone':
                # A real removal/expiry in this scope takes precedence.
                removed = any(e.event_type == 'ZONE_REMOVED' and
                              e.payload.get('zone_id') == item.zone_id for e in engine.events[first_event:])
                started = (item.trigger_profile.get('placed') or {}).get('concentration_started')
                removed = removed or any(e.event_type == 'CONCENTRATION_ENDED' and e.actor_id == item.owner_id
                    and e.source_definition_id == item.source_definition_id and
                    (started is None or e.payload.get('started_sequence') == started)
                    for e in engine.events[first_event:])
                if engine.state.zones.get(item.zone_id) is item and not removed:
                    item.active = True
                    record_zone_update(engine,item)
            else:
                actor, before = details
                if actor.conditions.get(item.instance_id) is item:
                    item.data = before
                    record_instance_update(engine,actor,'condition',item.instance_id,item)
        zone_rules.sync_inside(engine, source)
