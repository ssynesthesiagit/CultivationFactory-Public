"""Exact activation links shared by Obscure Passage and Updraft Gate.

The native concentration start receipt precedes zone creation. These two
providers opt their zones into a persisted integer activation sequence before
publication, so ending current or held concentration also works after reload.
No receipt leaves every other zone's native lifecycle unchanged.
"""
from . import hook

START = 'concentration_started_sequence'


def bind(ctx, zone):
    concentration = ctx.actor.concentration
    if (zone.concentration_link and concentration is not None
            and concentration.source_definition_id == ctx.source):
        zone.trigger_profile[START] = concentration.started_sequence
        concentration.zone_id = zone.zone_id


@hook('event')
def end_linked(engine, event_type, kwargs):
    if event_type != 'CONCENTRATION_ENDED':
        return
    from .. import zones
    payload = kwargs.get('payload') or {}
    for zone in list(engine.state.zones.values()):
        if (zone.active and START in zone.trigger_profile
                and zone.owner_id == kwargs.get('actor_id')
                and zone.source_definition_id == kwargs.get('source_definition_id')
                and zone.trigger_profile[START] == payload.get('started_sequence')):
            zones.remove(engine, zone, payload.get('reason') or 'CONCENTRATION_ENDED')
