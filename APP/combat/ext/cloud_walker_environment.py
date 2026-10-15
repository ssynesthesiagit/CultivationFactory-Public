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


def measure(value, *, positive=False):
    """Exact owner-authored pounds/inches: whole numbers or rational text."""
    require(type(value) in (int,str) and len(str(value))<=40,
            'Use whole numbers or exact decimal/fraction text for physical measurements.')
    try:
        result=Fraction(value)
    except (ValueError,ZeroDivisionError):
        raise ValueError('A physical measurement must be a finite exact number.')
    require(result>0 if positive else result>=0,'Physical measurements cannot be negative or have a zero passage width.')
    return result


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
                and {'body_weight_lb','width_inches'}<=set(body)<= {'body_weight_lb','width_inches','item_weights_lb'},
                'Declare each creature’s actual body weight and minimum passage width.')
        measure(body['body_weight_lb']);measure(body['width_inches'],positive=True)
        measurements=body.get('item_weights_lb',{})
        require(isinstance(measurements,dict) and all(isinstance(k,str) and '|' in k for k in measurements),
                'Unknown item measurements must bind the real original-owner ID and item key with |.')
        for value in measurements.values():measure(value)
    identities=set()
    for row in profile.get('surfaces',[]):
        require(isinstance(row,dict) and set(row)=={'id','kind','cells','z','capacity_lb','fragile','trigger'},
                'A surface needs identity, kind, cells, altitude, capacity, fragility and trigger kind.')
        require(isinstance(row['id'],str) and row['id'] and row['id'] not in identities,'Surface identities must be distinct.')
        identities.add(row['id'])
        measure(row['capacity_lb'])
        require(row['kind'] in KINDS and whole(row['z'])
                and type(row['fragile']) is bool and row['trigger'] in {'weight','qi_pressure','none'},'Surface facts have invalid types.')
        require(isinstance(row['cells'],list) and row['cells'] and all(isinstance(c,list) and len(c)==2
                and whole(c[0]) and whole(c[1]) and c[0]<width and c[1]<height for c in row['cells']),
                'Surface cells must be inside the native map.')
        require(row['z']>0 or row['kind']=='solid','Liquid and fragile footing need their real elevated surface plane and underlying ground in this map.')
    for barrier in profile.get('barriers',[]):
        require(isinstance(barrier,dict) and set(barrier)=={'axis','plane','low','high','opening_inches','total_cover','sealed_formation'},
                'A boundary needs its plane, rectangle, actual opening and cover/Formation facts.')
        measure(barrier['opening_inches'])
        require(barrier['axis'] in {'x','y','z'} and whole(barrier['plane'])
                and type(barrier['total_cover']) is bool and type(barrier['sealed_formation']) is bool,
                'Boundary dimensions and flags have invalid types.')
        require(all(isinstance(barrier[k],list) and len(barrier[k])==2 and all(whole(v) for v in barrier[k]) for k in ('low','high'))
                and all(a<=b for a,b in zip(barrier['low'],barrier['high'])), 'Boundary rectangles need ordered whole coordinates.')
    from copy import deepcopy
    return {KEY:deepcopy(profile)}


def environment(engine):
    return ((getattr(engine,'battlefield_document',None) or {}).get('source_data') or {}).get(KEY,{})


def broken(engine):
    return {ev.payload['surface_id'] for ev in engine.events if ev.event_type=='PASSIVE_TRIGGERED'
            and ev.source_definition_id==KEY and ev.payload.get('cloud_surface_failed')==1}


def surfaces(engine,actor,position,*,include_broken=False):
    profile=environment(engine)
    if not profile:return []
    dead=set() if include_broken else broken(engine)
    cells=set(engine._actor_cells(actor,position))
    return [row for row in profile.get('surfaces',()) if row['id'] not in dead and row['z']==position.z
            and cells.intersection(map(tuple,row['cells']))]


def actual_weight(engine,actor):
    body=environment(engine).get('bodies',{}).get(actor.entity_id)
    if body is None:return None
    from ..carry import weight,carrying_of,holds,remaining_quantity
    # Native known load and ownership/transfer receipts remain authoritative.
    # Source-scoped measurements fill only genuinely unknown physical weights;
    # they never create inventory or override a known mechanical item weight.
    extra=Fraction(0);measurements=body.get('item_weights_lb',{})
    for owner in engine.state.actors.values():
        carrying=carrying_of(engine,owner.entity_id) or {}
        unknown=set(carrying.get('unweighed') or ())
        for item in carrying.get('items') or ():
            if item['name'] not in unknown or Fraction(item.get('weight_lb') or '0')>0:continue
            carried=(holds(engine,owner,item['key']) if owner.entity_id==actor.entity_id else any(
                c.data.get('item_key')==item['key'] and c.data.get('held_by')==actor.entity_id for c in owner.conditions.values()))
            if not carried:continue
            key=owner.entity_id+'|'+item['key']
            if key not in measurements:return None
            extra+=measure(measurements[key])*remaining_quantity(engine,owner,item)
    # Native carrying returns a float for historical bundles. Convert through
    # decimal spelling; no binary value is persisted in the scene or event.
    return measure(body['body_weight_lb'])+Fraction(str(weight(engine,actor)))+extra


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


@hook('support_override',present=lambda engine: bool(environment(engine)))
def footing(engine,actor,position):
    all_rows=surfaces(engine,actor,position,include_broken=True)
    floor_rows=[b for b in environment(engine).get('barriers',()) if b['axis']=='z' and b['plane']==position.z
        and b['low'][0]<=position.x<=b['high'][0] and b['low'][1]<=position.y<=b['high'][1]]
    if floor_rows and position.z:
        below=position.model_copy(update={'z':position.z-1})
        if boundaries(engine,actor,position,below) is False:return True
    if not all_rows:return None
    rows=[r for r in all_rows if r['id'] not in broken(engine)]
    load=actual_weight(engine,actor)
    for row in rows:
        if row['kind'] in ATMOSPHERE:
            if atmospheric_step(engine,actor):return True
        elif crossing_light(engine,actor) and measure(row['capacity_lb'])>=1:
            return True
        elif load is not None and measure(row['capacity_lb'])>=load:
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
        if pressure or (row['trigger']=='weight' and tested is not None and tested>measure(row['capacity_lb'])):
            engine._append_event('PASSIVE_TRIGGERED',KEY,actor_id=actor.entity_id,
                payload={'cloud_surface_failed':1,'surface_id':row['id'],'authority':environment(engine)['declared_by'],
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


@hook('movement_edge_allowed',present=lambda engine: bool(environment(engine)))
def boundaries(engine,actor,previous,destination):
    rows=[b for b in environment(engine).get('barriers',()) if crosses(b,previous,destination)]
    if not rows:return None
    leap=any(c.condition_id==SEGMENT for c in actor.conditions.values())
    cloud=bool(form(actor))
    body=environment(engine).get('bodies',{}).get(actor.entity_id)
    width=1 if cloud and not leap else measure(body['width_inches'],positive=True) if body else engine._footprint(actor).width_cells*60
    return all(measure(b['opening_inches'])>=width and not (leap and (b['total_cover'] or b['sealed_formation'])) for b in rows)


def visible_destination(engine,actor,destination):
    """A real opaque scene boundary cannot be bypassed by Leap's menu query."""
    return not any(b['total_cover'] and crosses(b,actor.position,destination)
                   for b in environment(engine).get('barriers',()))


@hook('forced_movement_attempt')
def forced_boundary(engine,actor,previous,destination,intent):
    if boundaries(engine,actor,previous,destination) is False:
        return {'stop':True,'source_id':KEY,'label':f'{actor.display_name} stops at a physical boundary with no opening large enough.'}
    return None
