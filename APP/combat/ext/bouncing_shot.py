"""Bouncing Shot's visible solid-wall route and World-Needle's final cover clause.

On the square grid a bounce lies in an open cell bordering a solid map wall.
Both legs must be clear; no projectile crosses that wall. Other hard surfaces,
spirit-sense/mark-only surfaces and attended-object AC checks stay manual.
Shared ``applies`` lets sniper_angles distinguish native routed attacks from
legacy saved catalogs, so their cover and availability providers do not overlap.
"""
from . import effect, hook

BOUNCE='TAL_SNIPER_BOUNCING_SHOT'
WORLD='TAL_SNIPER_WORLD_NEEDLE_RICOCHET'
BLOCK='world_needle_ricochet'


@effect('bouncing_shot')
def declared(ctx,row):
    """The modifier declares route ownership; accepted geometry does the work."""
    return None


@hook('compile_block')
def compile_world(block,spec,row,numbers):
    return [{**row,'block':BLOCK}] if block==BLOCK else None


def applies(action):
    return action is not None and any(r.get('type')=='bouncing_shot' for r in action.parameters.get('typed',{}).get('effects',[]))


@hook('sight_path')
def bounce(engine,attacker,target):
    from ..shot_geometry import action
    from ..gate2_runtime_models import Position
    from ..action_geometry import point as origin_point
    if not applies(action(engine,attacker)):
        return None
    origin = origin_point(engine, attacker)
    # Only solid base-map walls: an effect's magical barrier is not inferred to
    # be a mundane hard surface. No map-wide scan or mutable position substitute.
    base=getattr(engine,'_wall_base',None)
    walls=base[0] if base is not None else engine.grid.blocked
    options=set()
    for x,y in walls:
        options.update((x+dx,y+dy) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)))
    routes=[]
    for x,y in sorted(options,key=lambda p:(p[1],p[0])):
        if not engine.grid.in_bounds((x,y)) or (x,y) in engine.grid.blocked:
            continue
        point=Position(x=x,y=y)
        if point in (origin,target.position):
            continue
        if not engine.grid.line_of_sight(origin,point,obscured_cells=engine._obscured_cells()) or not engine.grid.line_of_sight(point,target.position,obscured_cells=engine._obscured_cells()):
            continue
        # A bounce must change direction; a straight line is not a paid bounce.
        incoming=(point.x-origin.x,point.y-origin.y,point.z-origin.z)
        outgoing=(target.position.x-point.x,target.position.y-point.y,target.position.z-point.z)
        if all(incoming[a]*outgoing[b]==incoming[b]*outgoing[a] for a,b in ((0,1),(0,2),(1,2))):
            continue
        distance=engine.grid.distance_ft(origin,point)+engine.grid.distance_ft(point,target.position)
        routes.append((distance,y,x,point))
    if not routes:
        return None
    distance,_,_,point=min(routes)
    return {'source_id':BOUNCE,'label':f'Bouncing Shot bends beside the wall at {point.x},{point.y}; the projectile travels {distance} feet.',
            'path':[p.model_dump(mode='json') for p in (origin,point,target.position)]}


@hook('cover_reduction')
def world_cover(engine,attacker,target,cover):
    from ..shot_geometry import action, route
    if not applies(action(engine,attacker)) or not route(engine,attacker,target):
        return None
    rows = [*getattr(engine,'typed_passive_rows',{}).get(attacker.entity_id,[]),
            *getattr(engine,'typed_reaction_rows',{}).get(attacker.entity_id,[])]
    # One native cover provider also accepts the saved sniper-angle block.
    # Through the Wrong Door shares this routed-cover clause; its unseen-target
    # rider remains in sniper_angles.
    if any(r.get('block')==BLOCK or r.get('block')=='sniper_angles'
           and r.get('kind') in ('through_the_wrong_door','world_needle_ricochet') for r in rows):
        return 2 if cover<=5 else 0  # this printed clause never ignores Total Cover
    return None


@hook('candidate_allowed')
def needs_route(engine,actor,candidate,action):
    if applies(action):
        return bool(candidate.metadata.get('shot_geometry',{}).get('route'))
    return None
