"""Tidal Wave's delivery choices; saves and payment remain in its reviewed row.

The eligible_recipients hook runs before recipient consent and target reactions.
It resolves one activation-local footprint with native line/cone rasters. The
zone_creation_profile hook records that same footprint for drawing, terrain and
cold continuation. No sibling's acquisition, Court or cone-origin policy changes.
"""
from copy import deepcopy
from math import gcd, hypot

from . import hook
from .needle import ask, checkpoint_id, option_spec, cell_id
from ..gate2_runtime_models import Position

TIDAL = 'TAL_WATER_TIDAL_WAVE'
CURRENT = 'WATER_BASE_SHAPE_CURRENT'
COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
CHOICE = 'choice:water.tidal.'


def owns_wave(typed):
    """Only compiled instances of this owned modifier opt into the provider."""
    return typed.get('source') == CURRENT and any(
        row.get('source_modifier') == TIDAL
        for row in typed.get('effects') or [] if isinstance(row, dict))


@hook('choice_options')
def choices(engine, intent, checkpoint, reactor_id, choice_id, context):
    return option_spec(choice_id, context, CHOICE)


@hook('choice_reactors')
def reactors(engine):
    return tuple(sorted({action.owner_id for action in engine.action_catalog.values()
                         if owns_wave(action.parameters.get('typed') or {})}))


def inside_owned_court(engine, actor):
    """Read the Court producer's public native zone membership, not its helpers."""
    from ..zones import actor_inside_zone
    return any(zone.active and zone.owner_id == actor.entity_id
               and (engine.action_catalog[zone.source_definition_id].parameters.get('typed') or {}).get('source') == COURT
               and actor_inside_zone(engine, actor, zone)
               for zone in engine.state.zones.values() if zone.source_definition_id in engine.action_catalog)


def wave_cells(engine, origin, aim, shape, length, *, corner=None):
    """Return native cells for a straight or single-bend wave.

    A bend spends its first leg from the same length budget. Cone width grows
    with total distance along the two legs. Physical transmission is checked
    independently on each leg; a bend never grants transmission through walls.
    The caller validates the owned Court and perceived corner before using it.
    """
    from ..typed_executor import area_cells
    spec = {'shape': shape, 'size_ft': length, 'width_ft': 15}
    if corner is None:
        return area_cells(engine, origin, aim, spec)
    square = engine.grid.square_size_ft
    spent = engine.grid.distance_ft(origin, corner)
    first = area_cells(engine, origin, corner, {**spec, 'size_ft': spent})
    dx, dy = aim.x - corner.x, aim.y - corner.y
    norm = hypot(dx, dy)
    if not norm or spent >= length:
        return ()
    cells = set(first)
    for x in range(engine.grid.width):
        for y in range(engine.grid.height):
            cell = Position(x=x, y=y, z=corner.z)
            vx, vy = (x-corner.x)*square, (y-corner.y)*square
            along = (vx*dx + vy*dy)/norm
            perpendicular = abs(vx*dy-vy*dx)/norm
            width = 7.5 if shape == 'line' else (spent+along)/2
            if (along >= 0 and spent + engine.grid.distance_ft(corner, cell) <= length
                    and perpendicular <= width
                    and engine.grid.line_of_physical_transmission(corner, cell)
                    and engine.grid.placement_legal((x, y), occupied_cells=set())):
                cells.add(cell)
    return tuple(sorted(cells, key=lambda c: (c.z, c.y, c.x)))


def bend_corners(engine, actor, aim, length):
    """Perceived clear first-leg squares beside a represented solid obstacle."""
    from ..senses import perceives_cell
    if not inside_owned_court(engine, actor):
        return {}
    origin = actor.position
    result = {}
    # A ray fixes the first direction the player selected in the native menu.
    dx, dy = aim.x-origin.x, aim.y-origin.y
    scale = max(abs(dx), abs(dy))
    if not scale:
        return result
    for n in range(1, length//engine.grid.square_size_ft):
        corner = Position(x=origin.x+round(dx*n/scale), y=origin.y+round(dy*n/scale), z=origin.z)
        if not (0 <= corner.x < engine.grid.width and 0 <= corner.y < engine.grid.height):
            break
        if not engine.grid.line_of_physical_transmission(origin, corner):
            break
        if not engine.grid.placement_legal((corner.x, corner.y), occupied_cells=set()):
            break
        if engine.grid.distance_ft(origin, corner) >= length or not perceives_cell(engine, actor, corner):
            continue
        nearby = [Position(x=corner.x+x, y=corner.y+y, z=corner.z)
                  for x, y in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        if any(0 <= p.x < engine.grid.width and 0 <= p.y < engine.grid.height
               and not engine.grid.placement_legal((p.x, p.y), occupied_cells=set())
               and perceives_cell(engine, actor, p) for p in nearby):
            result[cell_id(corner)] = corner
    return result


def bend_headings(engine, origin, corner, length):
    """All distinct map-representable outgoing rays, without a top-N cutoff."""
    headings = {}
    incoming = (corner.x-origin.x, corner.y-origin.y)
    for x in range(engine.grid.width):
        for y in range(engine.grid.height):
            dx,dy = x-corner.x,y-corner.y
            if not (dx or dy) or not incoming[0]*dy-incoming[1]*dx:
                continue
            factor = gcd(abs(dx),abs(dy))
            dx,dy = dx//factor,dy//factor
            end = Position(x=corner.x+dx,y=corner.y+dy,z=corner.z)
            # An aim names a direction, not the wave's endpoint. A distant
            # primitive ray remains legal for a short remaining wave. Use its
            # native first raster step rather than rounding it to a diagonal.
            first_xy = engine.grid.ray_cells(corner,end)[1]
            first = Position(x=first_xy[0],y=first_xy[1],z=corner.z)
            if engine.grid.volume_step_legal((corner.x,corner.y,corner.z),(first.x,first.y,first.z)):
                headings[cell_id(end)] = end
    return headings


def _ask(ctx, key, options, labels, prompt, *, areas=None, preferred=None):
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'TIDAL_WAVE', ctx.source, key),
                   ctx.actor, CHOICE+key, list(options), labels=labels,
                   preferred=preferred or list(options)[:1], name='Tidal Wave', feature_id=TIDAL,
                   prompt=f'Tidal Wave during {ctx.action.display_name}: {prompt}', space_areas=areas)
    return selected[0] if selected else next(iter(options))


def _preview(cells):
    return [p.model_dump(mode='json') for p in cells]


@hook('eligible_recipients')
def delivery(ctx):
    if not owns_wave(ctx.typed):
        return None
    from ..target_knowledge import located
    engine, actor = ctx.engine, ctx.actor
    aim = ctx.damage_cache.get('_checkpoint_aim') or actor.position
    forms = {f'line:{n}': ('line', n) for n in range(5, 91, 5)}
    forms['cone:30'] = ('cone', 30)
    rasters = {key: wave_cells(engine, actor.position, aim, *value) for key, value in forms.items()}
    labels = {key: (f'{size}-foot line, 15 feet wide' if shape == 'line' else '30-foot cone')
              for key, (shape, size) in forms.items()}
    # Automatic selection uses only located hostiles; every legal form remains
    # offered to humans and in the automatic choice pool, with no truncation.
    hostiles = [a for a in engine.state.actors.values() if a.active and a.team_id != actor.team_id
                and located(engine, actor, a)]
    preferred = sorted(forms, key=lambda k: (-sum(engine._footprint_intersects(a, rasters[k]) for a in hostiles),
                                            -forms[k][1], k))
    selected = _ask(ctx, 'form', forms, labels,
                    'choose a line up to 90 feet long and 15 feet wide, or a 30-foot cone. '
                    'The wave costs 2 additional Cultivation Points, already included in this action.',
                    areas={k: _preview(v) for k, v in rasters.items()}, preferred=preferred[:1])
    shape, length = forms[selected]
    cells = rasters[selected]
    corners = bend_corners(engine, actor, aim, length)
    if corners:
        routes_by_corner = {}
        for key,corner in corners.items():
            routes_by_corner[key] = {k:wave_cells(engine,actor.position,p,shape,length,corner=corner)
                                     for k,p in bend_headings(engine,actor.position,corner,length).items()}
        def score(footprint):
            return sum(engine._footprint_intersects(a,footprint) for a in hostiles)
        best_corner = max(corners, key=lambda key: max([score(cells), *[score(v) for v in routes_by_corner[key].values()]]))
        corner_preference = [best_corner] if any(score(v)>score(cells) for v in routes_by_corner[best_corner].values()) else ['straight']
        route = _ask(ctx, 'corner', ['straight', *corners],
                     {'straight': 'Keep the wave straight', **{k: f'Curve once beside the obstacle at {p.x}, {p.y}' for k, p in corners.items()}},
                     'inside your Court of the Endless Tide, you may curve once around a perceived corner or obstacle.',
                     preferred=corner_preference)
        if route != 'straight':
            corner = corners[route]
            headings = bend_headings(engine,actor.position,corner,length)
            if headings:
                routes = routes_by_corner[route]
                out = _ask(ctx, 'heading', headings, {k:f'Continue toward {p.x}, {p.y}' for k,p in headings.items()},
                           'choose the outgoing direction after the one corner.', areas={k:_preview(v) for k,v in routes.items()},
                           preferred=[max(routes,key=lambda k:score(routes[k]))])
                cells = routes[out]
                ctx.typed['_tidal_corner'] = [corner.x, corner.y, corner.z]
                ctx.typed['_tidal_heading'] = [headings[out].x-corner.x, headings[out].y-corner.y]
    ctx.typed['_tidal_cells'] = _preview(cells)
    # Do not mutate the compiled action or a sibling's area dictionary.
    ctx.typed['area'] = {**ctx.typed['area'], 'shape': shape, 'size_ft': length, 'width_ft': 15}
    return [a for a in engine.state.actors.values() if a.active and a is not actor
            and a.entity_id not in ctx.missed_target_ids and engine._footprint_intersects(a, cells)]


@hook('zone_creation_profile')
def footprint(zone, ctx):
    if not owns_wave(ctx.typed) or '_tidal_cells' not in ctx.typed:
        return None
    profile = deepcopy(zone.trigger_profile)
    profile.update(footprint_is_authoritative=1, footprint_height_ft=ctx.engine.grid.square_size_ft,
                   shape=ctx.typed['area']['shape'],size_ft=ctx.typed['area']['size_ft'],width_ft=15)
    return zone.model_copy(update={'affected_cells': tuple(Position(**p) for p in ctx.typed['_tidal_cells']),
                                   'trigger_profile': profile,
                                   'radius_cells': ctx.typed['area']['size_ft']//ctx.engine.grid.square_size_ft})


@hook('forced_movement_direction')
def push_direction(ctx, target, distance_ft):
    # Named save packets retain their modifier attribution through the fail
    # branch. Do not redirect Shape Current's own push or another modifier's
    # movement merely because this activation also contains a Tidal Wave.
    if (not owns_wave(ctx.typed) or '_tidal_corner' not in ctx.typed
            or ctx.effect_source != 'passive:'+TIDAL):
        return None
    corner = Position(x=ctx.typed['_tidal_corner'][0], y=ctx.typed['_tidal_corner'][1], z=ctx.typed['_tidal_corner'][2])
    from ..typed_executor import area_cells
    first = area_cells(ctx.engine, ctx.actor.position, corner,
                       {**ctx.typed['area'], 'size_ft': ctx.engine.grid.distance_ft(ctx.actor.position, corner)})
    if not ctx.engine._footprint_intersects(target, first):
        return tuple(1 if v>0 else -1 if v<0 else 0 for v in ctx.typed['_tidal_heading'])
    return None
