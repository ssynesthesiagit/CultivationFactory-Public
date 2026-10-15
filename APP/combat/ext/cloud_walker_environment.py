"""Cloud Walker's explicit owner-authored scene facts and mechanical consumers.

The owner map save API collects this family's environment under source_data.
Nothing is inferred from pictures, names, damage types, narration or allegiance.
Scene declarations are public map facts, bound to the map owner and expire with
that sealed scene. Native events derive broken surfaces; carried load derives
from committed equipment state. No environment means no new support or boundary.
"""
from fractions import Fraction
from . import hook
from .cloud_walker import ownership, form, STEP, IMMORTAL, SEGMENT
from .qi_subpaths_five import FEATHER, cloud_step_protection

KEY='tianxia.subpath.qi.cloud_walker'
KINDS={'water','liquid','snow','mud','loose_sand','thin_branch','fragile_roof','unstable_ground','hanging_cloth',
       'similar_surface','mist','smoke','rain','cloud','solid'}
ATMOSPHERE={'mist','smoke','rain','cloud'}


def require(ok,message):
    if not ok:raise ValueError(message)


def whole(value,low=0):
    return type(value) is int and value>=low


@hook('map_source_data')
def collect(document,width,height):
    profile=(document.get('source_data') or {}).get(KEY)
    if profile is None:return None
    require(isinstance(profile,dict) and set(profile)<= {'source','authority','declared_by','expires','surfaces','bodies','barriers'},
            'Cloud Walker environment must use its documented scene declaration fields.')
    require(profile.get('source')==KEY and profile.get('authority')=='map_owner'
            and isinstance(profile.get('declared_by'),str) and profile['declared_by'].strip()
            and profile.get('expires')=='scene', 'Scene facts need the named map owner, source and scene expiry.')
    bodies=profile.get('bodies',{})
    require(isinstance(bodies,dict),'Body profiles must name creatures.')
    for aid,body in bodies.items():
        require(isinstance(aid,str) and aid.startswith('actor:') and isinstance(body,dict)
                and set(body)=={'body_weight_lb','width_inches'} and whole(body['body_weight_lb'],1)
                and whole(body['width_inches'],1),'Declare each creature’s actual body weight and minimum passage width as positive whole numbers.')
    identities=set()
    for row in profile.get('surfaces',[]):
        require(isinstance(row,dict) and set(row)=={'id','kind','cells','z','capacity_lb','fragile','trigger'},
                'A surface needs identity, kind, cells, altitude, capacity, fragility and trigger kind.')
        require(isinstance(row['id'],str) and row['id'] and row['id'] not in identities,'Surface identities must be distinct.')
        identities.add(row['id'])
        require(row['kind'] in KINDS and whole(row['z']) and whole(row['capacity_lb'])
                and type(row['fragile']) is bool and row['trigger'] in {'weight','qi_pressure','none'},'Surface facts have invalid types.')
        require(isinstance(row['cells'],list) and row['cells'] and all(isinstance(c,list) and len(c)==2
                and whole(c[0]) and whole(c[1]) and c[0]<width and c[1]<height for c in row['cells']),
                'Surface cells must be inside the native map.')
        require(row['z']>0 or row['kind']=='solid','Liquid and fragile footing need their real elevated surface plane and underlying ground in this map.')
    for barrier in profile.get('barriers',[]):
        require(isinstance(barrier,dict) and set(barrier)=={'axis','plane','low','high','opening_inches','total_cover','sealed_formation'},
                'A boundary needs its plane, rectangle, actual opening and cover/Formation facts.')
        require(barrier['axis'] in {'x','y','z'} and whole(barrier['plane']) and whole(barrier['opening_inches'])
                and type(barrier['total_cover']) is bool and type(barrier['sealed_formation']) is bool,
                'Boundary dimensions and flags have invalid types.')
        require(all(isinstance(barrier[k],list) and len(barrier[k])==2 and all(whole(v) for v in barrier[k]) for k in ('low','high'))
                and all(a<=b for a,b in zip(barrier['low'],barrier['high'])), 'Boundary rectangles need ordered whole coordinates.')
    from copy import deepcopy
    return {KEY:deepcopy(profile)}


def environment(engine):
    return (getattr(engine,'battlefield_document',{}).get('source_data') or {}).get(KEY,{})


def broken(engine):
    return {ev.payload['surface_id'] for ev in engine.events if ev.event_type=='CLOUD_SURFACE_FAILED'}


def surfaces(engine,actor,position,*,include_broken=False):
    dead=set() if include_broken else broken(engine)
    cells=set(engine._actor_cells(actor,position))
    return [row for row in environment(engine).get('surfaces',()) if row['id'] not in dead and row['z']==position.z
            and cells.intersection(map(tuple,row['cells']))]


def actual_weight(engine,actor):
    body=environment(engine).get('bodies',{}).get(actor.entity_id)
    if body is None:return None
    from ..carry import weight
    # Native carrying returns a float for historical bundles. Convert through
    # decimal spelling; no binary value is persisted in the scene or event.
    return Fraction(body['body_weight_lb'])+Fraction(str(weight(engine,actor)))


def during_turn(engine,actor):
    boundary=next((ev for ev in reversed(engine.events) if ev.event_type in {'TURN_STARTED','TURN_ENDED'}),None)
    return (engine.state.current_actor_id==actor.entity_id and not actor.turn_flags.get('cloud_footing_end')
            and (boundary is None or boundary.event_type=='TURN_STARTED'))


def crossing_light(engine,actor):
    return (during_turn(engine,actor)
            and FEATHER in ownership(engine,actor).get('features',()))


def atmospheric_step(engine,actor):
    return (during_turn(engine,actor)
            and (cloud_step_protection(engine,actor) or form(actor,'immortal')))


@hook('support_override')
def footing(engine,actor,position):
    all_rows=surfaces(engine,actor,position,include_broken=True)
    if not all_rows:return None
    rows=[r for r in all_rows if r['id'] not in broken(engine)]
    load=actual_weight(engine,actor)
    for row in rows:
        if row['kind'] in ATMOSPHERE:
            if atmospheric_step(engine,actor):return True
        elif crossing_light(engine,actor) and row['capacity_lb']>=1:
            return True
        elif load is not None and row['capacity_lb']>=load:
            return True
    # Authored roofs and finite solid columns are independent real support.
    if engine.grid.roof_supported(position,engine._footprint(actor)) or (position.z and any(
            engine.grid.terrain_at((x,y,position.z-1),'BLOCKED') for x,y in engine._actor_cells(actor,position))):
        return True
    return False


@hook('movement_step_settled')
def surface_crossing(engine,actor,previous,destination,intent):
    rows=surfaces(engine,actor,destination)
    if not rows:return None
    load=actual_weight(engine,actor)
    for row in rows:
        if not row['fragile']:continue
        pressure=row['trigger']=='qi_pressure' and crossing_light(engine,actor)
        tested=1 if crossing_light(engine,actor) and not pressure else load
        if pressure or (row['trigger']=='weight' and tested is not None and tested>row['capacity_lb']):
            engine._append_event('CLOUD_SURFACE_FAILED',KEY,actor_id=actor.entity_id,
                payload={'surface_id':row['id'],'authority':environment(engine)['declared_by'],
                         'trigger':row['trigger'],'label':f'{actor.display_name}: {row["kind"].replace("_"," ")} gives way.'})
    return None


@hook('turn_start')
def begin_footing(engine,actor):
    actor.turn_flags.pop('cloud_footing_end',None)


@hook('turn_end')
def end_footing(engine,actor):
    if not environment(engine):return
    # The end checkpoint ends the printed own-turn exception before checking
    # actual support; independent flight, a roof or another support remains.
    actor.turn_flags['cloud_footing_end']=1
    if surfaces(engine,actor,actor.position):
        from ..falling import settle
        settle(engine,KEY,getattr(engine,'_active_intent',None))


def crosses(barrier,previous,destination):
    axis='xyz'.index(barrier['axis'])
    a=[previous.x,previous.y,previous.z];b=[destination.x,destination.y,destination.z]
    plane=barrier['plane']
    # A plane is the shared face immediately before its integer coordinate.
    if not (min(a[axis],b[axis])<plane<=max(a[axis],b[axis])):return False
    other=[i for i in range(3) if i!=axis]
    return all(max(a[i],b[i])>=barrier['low'][j] and min(a[i],b[i])<=barrier['high'][j]
               for j,i in enumerate(other))


@hook('movement_edge_allowed')
def boundaries(engine,actor,previous,destination):
    rows=[b for b in environment(engine).get('barriers',()) if crosses(b,previous,destination)]
    if not rows:return None
    leap=any(c.condition_id==SEGMENT for c in actor.conditions.values())
    cloud=bool(form(actor))
    body=environment(engine).get('bodies',{}).get(actor.entity_id)
    width=1 if cloud and not leap else body['width_inches'] if body else engine._footprint(actor).width_cells*60
    return all(b['opening_inches']>=width and not (leap and (b['total_cover'] or b['sealed_formation'])) for b in rows)


def visible_destination(engine,actor,destination):
    """A real opaque scene boundary cannot be bypassed by Leap's menu query."""
    return not any(b['total_cover'] and crosses(b,actor.position,destination)
                   for b in environment(engine).get('barriers',()))
