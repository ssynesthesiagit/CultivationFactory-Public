"""Bouncing Shot's visible solid-wall route and World-Needle's final cover clause.

On the square grid a bounce touches the face bordering an open waypoint cell.
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
    from ..shot_geometry import action, length, valid as valid_route
    from ..gate2_runtime_models import Position
    from ..action_geometry import point as origin_point
    if not applies(action(engine,attacker)):
        return None
    origin = origin_point(engine, attacker)
    # Only solid base-map walls: an effect's magical barrier is not inferred to
    # be a mundane hard surface. No map-wide scan or mutable position substitute.
    base=getattr(engine,'_wall_base',None)
    walls=base[0] if base is not None else engine.grid.blocked
    faces={}
    for x,y in walls:
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            faces.setdefault((x+dx,y+dy),set()).add((x,y))
    routes=[]
    base_spans=getattr(engine,'_wall_base_spans',None)
    if base_spans is None:
        base_spans=engine.grid.terrain_spans
    blocked_spans=base_spans.get('BLOCKED',{})
    for x,y in sorted(faces,key=lambda p:(p[1],p[0])):
        if not engine.grid.in_bounds((x,y)):
            continue
        point=Position(x=x,y=y)
        if point in (origin,target.position):
            continue
        distance_in=engine.grid.distance_ft(origin,point)
        distance_out=engine.grid.distance_ft(point,target.position)
        total=distance_in+distance_out
        if not total:
            continue
        altitude=(origin.z*distance_out+target.position.z*distance_in+total//2)//total
        point=Position(x=x,y=y,z=altitude)
        contact_cells=[(wx,wy) for wx,wy in sorted(faces[(x,y)])
                       if any(bottom<=altitude*5 and (top is None or altitude*5<top)
                              for bottom,top in blocked_spans.get((wx,wy),[(0,None)]))]
        if not contact_cells:
            continue
        # The shared validator checks the actual face vectors for a bend;
        # neither grid distance nor waypoint-centre vectors decide reflection.
        for wall_cell in contact_cells:
            row={'source_id':BOUNCE,'label':'Bouncing Shot route',
                 'path':[p.model_dump(mode='json') for p in (origin,point,target.position)],
                 'surface_contacts':[{'path_index':1,'cell':{'x':wall_cell[0],'y':wall_cell[1]}}]}
            if valid_route(engine,attacker,target,row):
                routes.append((length(engine,row),y,x,point,wall_cell))
    if not routes:
        return None
    distance,_,_,point,wall_cell=min(routes)
    return {'source_id':BOUNCE,'label':f'Bouncing Shot bends at a wall; the projectile travels {distance} feet.',
            'path':[p.model_dump(mode='json') for p in (origin,point,target.position)],
            'surface_contacts':[{'path_index':1,'cell':{'x':wall_cell[0],'y':wall_cell[1]}}]}


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
