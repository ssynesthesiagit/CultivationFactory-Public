"""Hollowing Field's source-owned, spatial Ruin Vulnerability.

New reviewed marker seals the policy; unstamped catalogs remain unchanged.
Defense queries are pure and read the live zone volume on every packet.
"""
from . import effect, hook
from .. import unmaking, pending_damage

MARKER = 'unmaking_field_vulnerability'


@effect(MARKER)
def field_marker(ctx, row):
    """Inert policy marker read only from this fight's sealed action."""


def fields(engine, actor):
    if actor is None:
        return []
    result = []
    for zone in engine.state.zones.values():
        if not zone.active or zone.owner_id != actor.entity_id:
            continue
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (action.parameters or {}).get('typed', {}) if action else {}
        if any(row.get('type') == MARKER for row in typed.get('effects', ())):
            result.append(zone)
    return result


@hook('damage_defenses')
def construct_vulnerability(engine, target, damage_type, typed, source_actor_id):
    from .creature_kinds import matches
    from ..spatial_areas import zone_contains
    owner = engine.state.actors.get(source_actor_id or '')
    if owner is None or damage_type != 'FORCE' or not matches(target, ('construct',)) or target.summon is None:
        return None
    packet = pending_damage.current(engine)
    qualifies = typed.get('sphere') == unmaking.UNMAKING
    if packet is not None and packet.target_id == target.entity_id and packet.source_actor_id == source_actor_id:
        qualifies = unmaking.my_unmaking_source(engine, owner, packet.source_id)
    if qualifies and any(zone_contains(engine, target, zone) for zone in fields(engine, owner)):
        return [{'kind': 'vulnerability', 'damage_types': ['FORCE']}]
    return None


@hook('object_damage_defenses')
def object_vulnerability(engine, actor, obj, packets, source):
    from ..typed_executor import in_area
    from ..object_geometry import target_cells
    if not unmaking.my_unmaking_source(engine, actor, source) or not any(kind.upper() == 'FORCE' for _, kind in packets):
        return None
    if any(in_area(engine, zone.center, zone.center, cell, zone.trigger_profile)
           for zone in fields(engine, actor) for cell in target_cells(engine, obj)):
        return [{'kind': 'vulnerability', 'damage_types': ['FORCE']}]
    return None
