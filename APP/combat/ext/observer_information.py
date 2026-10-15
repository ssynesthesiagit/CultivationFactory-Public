"""Observer-only information shared by Grave Sense, Earth Court and Hidden Eye.

Facts are flat integer/string dictionaries in ordinary evented conditions.
The public projection hook never grants sight, target identity or a location;
abilities that explicitly grant location use the separate pinpoint hook.
Scene authors opt conditions/objects into detection with a ``detection``
dictionary: category, dc, sense (sight by default), and readable description.
No metadata means no invented phenomenon or diagnostic fact.
"""
from . import hook

FACT = 'condition:typed.observer_information'


def record(engine, observer, source, text, *, expiry='UNTIL_REMOVED', **facts):
    if any(type(v) not in (str, int) for v in facts.values()):
        raise ValueError('Observer facts must be integers or strings')
    engine._apply_condition(observer, FACT, source, observer.entity_id,
        expires_on=expiry, data={'text': text, 'label': text, **facts})


def bearing(observer, position):
    dx, dy = position.x - observer.position.x, position.y - observer.position.y
    return (('north' if dy < 0 else 'south' if dy > 0 else '') +
            ('east' if dx > 0 else 'west' if dx < 0 else '')) or 'here'


@hook('observer_information')
def retained_facts(engine, viewer):
    return [{k: v for k, v in c.data.items() if k != 'label'}
            for c in viewer.conditions.values() if c.condition_id == FACT]


def detectable(engine, viewer, point, metadata, reach):
    """Explicit phenomenon eligibility; physical barriers always stop detection."""
    from ..senses import cell_probe, perceives, perceives_without_sight
    if not metadata or engine.grid.distance_ft(viewer.position, point) > reach:
        return False
    probe = cell_probe(point)
    if not engine.grid.line_of_physical_transmission(viewer.position, point):
        return False
    return (perceives_without_sight(engine, viewer, probe) if metadata.get('sense') == 'nonvisual'
            else perceives(engine, viewer, probe))


def phenomena(engine, viewer, reach):
    """All represented object/sensor/effect candidates, with no top-N cutoff."""
    for actor in engine.state.actors.values():
        for condition in actor.conditions.values():
            data = condition.data.get('detection') or {}
            if detectable(engine, viewer, actor.position, data, reach):
                yield condition.instance_id, actor.position, data
    for obj in engine.state.objects.values():
        data = (obj.component or {}).get('detection') or {}
        if not obj.destroyed and detectable(engine, viewer, obj.position, data, reach):
            yield obj.object_id, obj.position, data
    for zone in engine.state.zones.values():
        data = zone.trigger_profile.get('detection') or {}
        if zone.active and detectable(engine, viewer, zone.center, data, reach):
            yield zone.zone_id, zone.center, data


def phenomenon_search_mode(engine, viewer, point, metadata):
    """Sweep's represented sensory purpose, sharing native check penalties.

    Hidden Eye uses this for objects, sensors and effects. A visual phenomenon
    cannot switch to hearing to evade its sight penalty; scene metadata must
    explicitly qualify a nonvisual detection method. Nonvisual metadata does
    not assert hearing: it can represent tremorsense or another available sense.
    """
    from .. import stealth, senses
    from ..typed_executor import check_modes
    probe = senses.cell_probe(point)
    modes = stealth.search_modes(engine, viewer)
    hazards = () if metadata.get('sense') == 'nonvisual' else ('visual_concealment',)
    modes.update(check_modes(viewer, 'WIS', 'Perception', engine=engine,
                             against_creature=probe, hazards=hazards))
    return next(iter(modes)) if len(modes) == 1 else 'NORMAL'
