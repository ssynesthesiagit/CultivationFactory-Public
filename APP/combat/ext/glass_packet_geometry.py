"""Faultline Marks from actual committed attack paths through Glass Surfaces.

Uses the existing Glass ownership/choice implementation. This owns no attack,
damage, object or mark schema and never reconstructs a centre-to-centre ray.
Held gear has no invented occupied volume; explicit body/armor/shield attacks
retain their separate printed trigger in glass_refraction.
"""
from . import hook

CONSUMER = 'glass_faultline_surfaces'


def crossed_owners(engine, actor, target, geometry):
    from .glass_faultline_marks import owners, surface_owners
    from .glass_surface_profiles import profiles, body_is_surface
    from ..object_geometry import aim_cells
    from ..space import point
    trace = []
    for part in geometry['segments']:
        for cell in part['cells']:
            value = tuple(cell)
            if not trace or value != trace[-1]:
                trace.append(value)
    interior = set(trace[1:-1])
    contacts = []
    for contact in geometry['surface_contacts']:
        index = contact['path_index']
        if 1 <= index <= len(geometry['segments']):
            contacts.append((contact['cell']['x'], contact['cell']['y'],
                geometry['segments'][index - 1]['end'][4]))
    touched_cells = interior | set(contacts)
    result = {}
    minimum = min((p[2] for p in touched_cells), default=0)
    maximum = max((p[2] for p in touched_cells), default=0)
    for obj in engine.state.objects.values():
        if obj.destroyed:
            continue
        controlled = surface_owners(engine, obj)
        if not controlled:
            continue
        against = geometry['target_kind'] == 'object' and target.object_id == obj.object_id
        through = bool(touched_cells.intersection(point(p) for p in aim_cells(engine, obj,
            minimum_z=minimum, maximum_z=maximum)))
        if against or through:
            result.update((owner.entity_id, owner) for owner in controlled)
    regions = {r['region_id']: r for r in (engine.battlefield_document or {}).get('terrain_regions', ())}
    for owner in owners(engine):
        from .glass_refraction import surface_zones
        from ..spatial_areas import positions_inside_zone
        if any(positions_inside_zone(engine, interior, zone) for zone in surface_zones(engine, owner)):
            result[owner.entity_id] = owner
        # An attack does not pass through its own user's body merely because
        # the selected origin lies inside that body's occupied space.
        if (owner is not actor and owner is not target and body_is_surface(engine, owner)
                and interior.intersection(engine._actor_volume(owner))):
            result[owner.entity_id] = owner
        for profile in profiles(engine, owner):
            if profile.data['surface_kind'] != 'terrain':
                continue
            region = regions.get(profile.data['surface_ref'])
            if region is None or region.get('terrain_type') != 'BLOCKED':
                continue
            footprint = {(p['x'], p['y']) for p in region.get('cells', ())}
            bottom, height = int(region.get('base_altitude_ft') or 0), region.get('height_ft')
            if any((x, y) in footprint and (z + 1) * 5 > bottom
                    and (height is None or z * 5 < bottom + height)
                    for x, y, z in (*interior, *contacts)):
                result[owner.entity_id] = owner
    return tuple(result[key] for key in sorted(result))


@hook('packet_geometry_tracking')
def tracking(engine, actor, target, spec, source):
    from .glass_faultline_marks import owners
    from .glass_surface_profiles import profiles, body_is_surface
    from .glass_pane import panes_of
    from .glass_refraction import surface_zones
    for owner in owners(engine):
        if (panes_of(engine, owner) or surface_zones(engine, owner)
                or any(c.data['surface_kind'] in ('object', 'terrain') for c in profiles(engine, owner))
                or owner is not actor and owner is not target and body_is_surface(engine, owner)):
            return (CONSUMER,)
    return None


@hook('packet_geometry_relevant')
def relevant(engine, actor, target, source, geometry):
    if CONSUMER in geometry['consumers']:
        return {CONSUMER: bool(crossed_owners(engine, actor, target, geometry))}


@hook('packet_geometry_committed')
def mark_crossing(engine, actor, target, source, geometry, roll):
    if CONSUMER not in geometry['consumers']:
        return
    from .glass_faultline_marks import offer_surface_mark
    from .ability_source import source_label
    name = source_label(engine, source) or 'the triggering attack'
    for owner in crossed_owners(engine, actor, target, geometry):
        from .glass_faultline_marks import surface_owners
        direct = geometry['target_kind'] == 'object' and owner in surface_owners(engine, target)
        offer_surface_mark(engine, owner, actor,
            (f'{actor.display_name} attacks your Glass Surface with {name}' if direct else
             f'{actor.display_name} attacks through, across, or against your Glass Surface with {name}'),
            unseen_trigger='an unseen creature attacks through, across, or against your Glass Surface')
