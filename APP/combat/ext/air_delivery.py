"""Wind-Script Delivery moves one explicitly prepared Tiny object, never uses it.

Routes are open-air, at most 30 feet, straight before Core Formation and with
at most one turn afterward. All legal destinations remain offered. Prepared
identity is sealed in object.component (size=Tiny and prepared provenance) or
an explicitly prepared object kind. It may have been prepared by anyone.
"""
from . import hook
from .fight_ownership import owns_feature
from .air_currents import currents
from .needle import ask, checkpoint_id, cell_id, numbers_of

DELIVERY = 'TAL_AIR_WIND_SCRIPT_DELIVERY'
GATHER = 'AIR_BASE_GATHER_CURRENT'


@hook('compile_action')
def delivery_placement(action, info):
    """A delivery Current has a purpose even when it contains no creatures.

    The existing utility-placement opt-in retains all observed empty-square
    aims in the AI menu. Runtime delivery still requires a perceived prepared
    Tiny object and open effect/air paths; no knowledge bypass is granted.
    """
    if DELIVERY in info['owned_ids'] and (action.parameters.get('typed') or {}).get('source') == GATHER:
        return action.model_copy(update={'parameters': {**action.parameters, 'ai_allow_empty_area': True}})


@hook('compile_passives')
def ownership(passives, info):
    if DELIVERY in info['owned_ids']:
        return [*passives, {'feature_id': DELIVERY, 'block': 'air_delivery', 'kind': 'wind_script'}]


def open_air_path(grid, start, end):
    """Physical delivery leg: solid roof/floor slabs and terrain both block.

    The public roof query respects authored and temporary openings. Physical
    transmission deliberately ignores visual obscuration, so unseen endpoints
    remain legal when there is an actual open air path.
    """
    return not grid.roof_ray_blocked(start, end) and grid.line_of_physical_transmission(start, end)


def routes(engine, origin, corners):
    """All straight rays, or two straight legs within 30 feet.

    Raster directions may change along one geometrically straight ray. Counting
    those changes as corners would wrongly hide unequal-slope destinations.
    Missing endpoints alone enter the one-corner search; no option is truncated.
    """
    from ..gate2_runtime_models import Position
    from ..space import ray
    points = [Position(x=x, y=y, z=z)
        for x in range(max(0, origin.x - 6), min(engine.grid.width, origin.x + 7))
        for y in range(max(0, origin.y - 6), min(engine.grid.height, origin.y + 7))
        for z in range(max(0, origin.z - 6), origin.z + 7)
        if not engine.grid.terrain_at((x, y, z), 'BLOCKED')]
    out = {}
    for point in points:
        if open_air_path(engine.grid, origin, point):
            out[cell_id(point, include_altitude=True)] = (point, ray(origin, point))
    if corners:
        missing = {cell_id(point, include_altitude=True): point for point in points
                   if cell_id(point, include_altitude=True) not in out}
        pivots = [point for point, path in list(out.values()) if engine.grid.distance_ft(origin, point) < 30]
        for pivot in pivots:
            if not missing:
                break
            cost = engine.grid.distance_ft(origin, pivot)
            for key, point in list(missing.items()):
                if cost + engine.grid.distance_ft(pivot, point) <= 30 and open_air_path(engine.grid, pivot, point):
                    out[key] = (point, (*ray(origin, pivot), *ray(pivot, point)[1:]))
                    del missing[key]
    out.pop(cell_id(origin, include_altitude=True), None)
    return out


@hook('choice_reactors')
def owners(engine):
    return tuple(a.entity_id for a in engine.state.actors.values() if owns_feature(engine, a, DELIVERY))


@hook('technique_used')
def deliver(ctx):
    if ctx.typed.get('source') != GATHER or not owns_feature(ctx.engine, ctx.actor, DELIVERY):
        return
    from ..spatial_areas import zone_contains
    from ..senses import perceives_object, perceives_cell
    from ..targeting import line_of_effect
    from ..senses import cell_probe
    areas = currents(ctx.engine, ctx.actor)
    objects = {obj.object_id: obj for obj in ctx.engine.state.objects.values() if not obj.destroyed
        and obj.unattended and (obj.component or {}).get('size') == 'Tiny'
        and (obj.component.get('prepared_by') or obj.component.get('prepared')
             or obj.object_kind.lower() in {'talisman', 'folded_paper', 'ribbon_script', 'incense_spark', 'feather_mark'})
        and perceives_object(ctx.engine, ctx.actor, obj)
        and line_of_effect(ctx.engine, ctx.actor, destination=obj.position)
        and any(zone_contains(ctx.engine, cell_probe(obj.position), zone) for zone in areas)}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'wind_script_object', ctx.source), ctx.actor,
        'choice:needle.wind_script_object', list(objects), name='Wind-Script Delivery', allow_decline=True,
        labels={key: obj.component.get('name') or 'Prepared Tiny object' for key, obj in objects.items()},
        prompt='Wind-Script Delivery: after Gather Current, optionally choose one prepared Tiny object in your Air Current to carry up to 30 feet. This does not activate a talisman or consumable.')
    if not selected:
        return
    obj = objects[selected[0]]
    from ..table_advance import realm_of
    realm = realm_of(int(numbers_of(ctx.engine, ctx.actor).get('cl') or 1))
    corners = int(realm in ('Core Formation', 'Nascent Soul', 'Immortal'))
    paths = routes(ctx.engine, obj.position, corners)
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'wind_script_destination', ctx.source, obj.object_id), ctx.actor,
        'choice:needle.wind_script_destination', list(paths), name='Wind-Script Delivery', allow_decline=True,
        preferred=[key for key, (point, _) in paths.items() if perceives_cell(ctx.engine, ctx.actor, point)],
        labels={key: f'Move to {point.x},{point.y}, altitude {point.z * 5} feet' for key, (point, _) in paths.items()},
        prompt='Wind-Script Delivery: choose the object’s destination along an open air path, up to 30 feet' + (' with at most one corner.' if corners else ' in a straight line.'))
    if chosen:
        ctx.engine._update_object(obj.model_copy(update={'position': paths[chosen[0]][0]}), ctx.source, ctx.actor.entity_id)
