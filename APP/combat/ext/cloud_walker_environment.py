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
    require(isinstance(profile,dict) and set(profile)<= {'source','authority','declared_by','expires','surfaces','bodies','barriers','fields'},
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
    for barrier in profile.get('barriers',[]):
        require(isinstance(barrier,dict) and set(barrier)=={'axis','plane','low','high','opening_inches','total_cover','sealed_formation'},
                'A boundary needs its plane, rectangle, actual opening and cover/Formation facts.')
        measure(barrier['opening_inches'])
        require(barrier['axis'] in {'x','y','z'} and whole(barrier['plane'])
                and type(barrier['total_cover']) is bool and type(barrier['sealed_formation']) is bool,
                'Boundary dimensions and flags have invalid types.')
        require(all(isinstance(barrier[k],list) and len(barrier[k])==2 and all(whole(v) for v in barrier[k]) for k in ('low','high'))
                and all(a<=b for a,b in zip(barrier['low'],barrier['high'])), 'Boundary rectangles need ordered whole coordinates.')
    for field in profile.get('fields',[]):
        require(isinstance(field,dict) and {'id','source_id','source_rule','source_cl','save_dc','kind','cells','min_z','max_z','absolute'}<=set(field)<= {'id','source_id','source_rule','source_cl','save_dc','kind','cells','min_z','max_z','absolute','anchor_object_id'},
                'A pressure field needs its exact source, controlling rule, Source CL, save DC, kind, volume and absolute protection.')
        require(all(isinstance(field[k],str) and 0<len(field[k])<=2000 for k in ('id','source_id','source_rule'))
                and field['id'] not in identities,'Field identity and controlling source must be explicit and distinct.')
        identities.add(field['id'])
        require('anchor_object_id' not in field or isinstance(field['anchor_object_id'],str), 'An anchored field must name its actual native object ID.')
        require(field['kind'] in {'gravity','spatial','weather','conceptual_weight','wind'}
                and whole(field['source_cl'],1) and whole(field['save_dc'],1) and type(field['absolute']) is bool
                and whole(field['min_z']) and whole(field['max_z']) and field['min_z']<=field['max_z'],
                'Field authority and volume must be typed native values.')
        require(isinstance(field['cells'],list) and field['cells'] and all(isinstance(c,list) and len(c)==2
                and whole(c[0]) and whole(c[1]) and c[0]<width and c[1]<height for c in field['cells']),
                'Field cells must be inside the native map.')
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
    if getattr(engine,'_roster_setup',{}).get('physical_scene')==1:return False
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
    if environment(engine) or any(c.condition_id==IMMERSED for c in actor.conditions.values()):
        ground_footing(engine,actor)


@hook('turn_end',priority=-20)
def end_footing(engine,actor):
    if not environment(engine):return
    # The end checkpoint ends the printed own-turn exception before checking
    # actual support; independent flight, a roof or another support remains.
    actor.turn_flags['cloud_footing_end']=1
    from ..flight import profile
    from ..falling import supported
    if not supported(engine,actor) and not profile(engine,actor).speed_ft:
        surface_crossing(engine,actor,actor.position,actor.position,getattr(engine,'_active_intent',None))
    ground_footing(engine,actor)
    if surfaces(engine,actor,actor.position,include_broken=True):
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


def body_crosses(barrier,previous,destination,footprint):
    """Swept native body cells, including entry around a finite plane's edge."""
    from ..space import volume,position
    left=volume(previous,footprint);right=volume(destination,footprint)
    if any(crosses(barrier,position(old),position(new)) for old,new in zip(left,right)):return True
    axis='xyz'.index(barrier['axis']);other=[i for i in range(3) if i!=axis]
    cells=set(right);plane=barrier['plane']
    for cell in cells:
        if cell[axis]!=plane or not all(barrier['low'][j]<=cell[i]<=barrier['high'][j] for j,i in enumerate(other)):continue
        adjacent=list(cell);adjacent[axis]-=1
        if tuple(adjacent) in cells:return True
    return False


@hook('movement_edge_allowed',present=lambda engine: bool(environment(engine)))
def boundaries(engine,actor,previous,destination,*,leap=False):
    rows=[b for b in environment(engine).get('barriers',()) if body_crosses(b,previous,destination,engine._footprint(actor))]
    if not rows:return None
    from .cloud_walker import CARRY
    leap=leap or any(c.condition_id in {SEGMENT,CARRY} for c in actor.conditions.values())
    cloud=bool(form(actor))
    body=environment(engine).get('bodies',{}).get(actor.entity_id)
    width=1 if cloud else measure(body['width_inches'],positive=True) if body else engine._footprint(actor).width_cells*60
    return boundary_permission(rows,width,leap)


def boundary_permission(rows,width,leap=False):
    """Shared source geometry for combat bodies, passengers and journey mist."""
    return all(measure(b['opening_inches'])>=width and not (leap and (b['total_cover'] or b['sealed_formation'])) for b in rows)


def journey_boundaries_geometry(session,aid,previous,destination):
    profile=(session.state['battlefield'].get('source_data') or {}).get(KEY,{})
    if not profile:return None
    from .cloud_walker import travel_mist
    body=profile.get('bodies',{}).get(aid)
    from ..footprints import ActorFootprintDefinition,standard_actor_footprint
    declared=session.state['actors'][aid]['bundle'].get('actor_footprint')
    footprint=ActorFootprintDefinition.model_validate(declared) if declared else standard_actor_footprint()
    from ..dynamic_size import shape,category_name
    footprint=shape(footprint,category_name(session.state['actors'][aid]['size']))
    rows=[b for b in profile.get('barriers',()) if body_crosses(b,previous,destination,footprint)]
    width=1 if travel_mist(session,aid) else measure(body['width_inches'],positive=True) if body else footprint.width_cells*60
    if not boundary_permission(rows,width):return False
    return None


@hook('journey_edge_allowed')
def journey_boundaries(session,aid,previous,destination):
    if journey_boundaries_geometry(session,aid,previous,destination) is False:return False
    from .cloud_walker import travel_mist
    if travel_mist(session,aid):
        from .cloud_walker import WIND
        held=session.state['actors'][aid]['travel_effects'][WIND]
        cl=int(held['source_cl'])
        for field in journey_pressure_fields(session,destination):
            if field['absolute'] or field['source_cl']>cl+2:return False
            route=getattr(session,'cloud_pressure_route',{})
            preview=route.get('actor_id')==aid and route.get('preview')==1
            if field['source_cl']>=cl-2 and not preview and not journey_contest_result(session,aid,field,destination):return False
    return None



def visible_destination(engine,actor,destination):
    """A real opaque scene boundary cannot be bypassed by Leap's menu query."""
    return not any(b['total_cover'] and crosses(b,actor.position,destination)
                   for b in environment(engine).get('barriers',()))


@hook('forced_movement_attempt')
def forced_boundary(engine,actor,previous,destination,intent):
    if boundaries(engine,actor,previous,destination) is False:
        return {'stop':True,'source_id':KEY,'label':f'{actor.display_name} stops at a physical boundary with no opening large enough.'}
    return None


SUPPRESSED='condition:typed.cloud_route_suppressed'
CONTEST='condition:typed.cloud_pressure_contest'


def pressure_fields(engine,position):
    rows=[]
    for r in environment(engine).get('fields',()):
        if not (r['min_z']<=position.z<=r['max_z'] and [position.x,position.y] in r['cells']):continue
        if 'anchor_object_id' in r:
            obj=engine.state.objects.get(r['anchor_object_id'])
            if obj is None or obj.destroyed:continue
            from ..asset_anchor_runtime import source_profile
            native=source_profile(engine,obj)
            if not native['source_cl']:continue
            r={**r,'source_cl':native['source_cl']}
        rows.append(r)
    return rows


def cloud_grants(engine,actor):
    """Independent native grants; a borrowed form never owns another source."""
    from .cloud_walker import SEGMENT,CARRY
    for held in actor.conditions.values():
        action=engine.action_catalog.get(held.source_definition_id)
        source=(action.parameters.get('typed') or {}).get('source') if action else held.source_definition_id
        if held.condition_id in {SEGMENT,CARRY,'condition:typed.cloud_walker_form'} or (
                held.condition_id=='condition:typed.general_flight' and source==STEP):
            yield held


def cloud_authority(engine,actor,held=None):
    if held:
        user=engine.state.actors.get(held.source_actor_id)
        row=ownership(engine,user) if user is not None else {}
        numbers=row.get('numbers',{})
        if 'source_pb' in held.data and 'source_key_mod' in held.data:
            numbers={**numbers,'pb':held.data['source_pb'],'key_mod':held.data['source_key_mod']}
        return int(held.data.get('source_cl',row.get('cl',0))),numbers
    row=ownership(engine,actor)
    return int(row.get('cl',0)),row.get('numbers',{})


def contest_pressure(engine,actor,field,grant):
    """One actual Cultivation Check per source/turn, never an ordinary check."""
    from .cloud_walker import stamp
    scope=field['id']+':'+grant.instance_id+':'+stamp(engine)
    held=next((c for c in actor.conditions.values() if c.condition_id==CONTEST and c.data.get('scope')==scope),None)
    if held:return bool(held.data['success'])
    cl,numbers=cloud_authority(engine,actor,grant)
    require('pb' in numbers and 'key_mod' in numbers,
            'This saved cloud effect lacks its source’s Cultivation Check numbers; resolve the contest with its source present.')
    # R4 Cultivation Checks do not inherit ordinary ability-check bonuses.
    roll=engine.roller.d20(modifier=int(numbers.get('pb',0))+int(numbers.get('key_mod',0)),
        actor_id=actor.entity_id,reason='CLOUD_WALKER_SOURCE_CONTEST')
    engine._record_roll(roll)
    success=roll.total>=field['save_dc']
    engine._append_event('CHECK_ROLLED',field['source_id'],actor_id=actor.entity_id,
        payload={'actor':roll.model_dump(mode='json'),'dc':field['save_dc'],'success':success,
                 'skill':'Cultivation Check','field_id':field['id']})
    engine._apply_condition(actor,CONTEST,field['source_id'],actor.entity_id,expires_on='END_OF_CURRENT_TURN',
        data={'scope':scope,'success':int(success),'field_id':field['id']})
    return success


@hook('movement_step')
def pressure_arrival(engine,actor,previous,destination,intent):
    from .cloud_walker import CARRY,cloud_step_protection
    moving_cloud=any(c.condition_id in {SEGMENT,CARRY} for c in actor.conditions.values())
    if not (moving_cloud or form(actor) or cloud_step_protection(engine,actor)):return None
    grants=list(cloud_grants(engine,actor))
    blocked=None
    for field in pressure_fields(engine,destination):
        # Ordinary/lower authority does not negate printed aerial movement.
        failed=[]
        for grant in grants:
            cl,numbers=cloud_authority(engine,actor,grant)
            if field['source_cl']<cl-2 and not field['absolute']:continue
            if not field['absolute'] and field['source_cl']<=cl+2 and contest_pressure(engine,actor,field,grant):continue
            failed.append(grant)
        if not failed:continue
        travellers=[actor]
        if moving_cloud:
            travellers += [a for a in engine.state.actors.values() if a is not actor and any(
                c.condition_id==CARRY and c.data.get('carrier_id')==actor.entity_id for c in a.conditions.values())]
        for target in travellers:
            target_grants=failed if target is actor else [c for c in cloud_grants(engine,target)
                if c.condition_id==CARRY and c.data.get('carrier_id')==actor.entity_id]
            for grant in target_grants:
                if any(c.condition_id==SUPPRESSED and c.data.get('field_id')==field['id']
                       and c.data.get('grant_id')==grant.instance_id for c in target.conditions.values()):continue
                engine._apply_condition(target,SUPPRESSED,field['source_id'],actor.entity_id,expires_on='UNTIL_REMOVED',
                    data={'field_id':field['id'],'source_cl':field['source_cl'],'grant_id':grant.instance_id,
                          'failure_kind':field['kind'],
                          'label':'Cloud movement suppressed by '+field['kind'].replace('_',' ')})
        blocked=field
    # An impulse consumes its declared segment, not an unrelated surviving
    # flight allowance. Ordinary flight can use any independently legal grant.
    used=[g for g in grants if g.condition_id in {SEGMENT,CARRY}] or grants
    if blocked and all(any(c.condition_id==SUPPRESSED and c.data.get('grant_id')==g.instance_id
                           for c in actor.conditions.values()) for g in used):
        field=blocked
        return {'stop':True,'source_id':field['source_id'],
                'label':f'{actor.display_name} is stopped by the {field["kind"].replace("_"," ")} field.'}
    return None


@hook('turn_end',priority=20)
def pressure_refresh(engine,actor):
    from .condition_ownership import remove_instance
    live={row['id'] for row in pressure_fields(engine,actor.position)}
    for held in list(actor.conditions.values()):
        if held.condition_id==SUPPRESSED and held.data.get('field_id') not in live:
            remove_instance(engine,actor,held.instance_id,held.source_definition_id)


@hook('event',nested=True)
def pressure_activation(engine,event_type,kwargs):
    if event_type!='CONDITION_APPLIED':return
    cid=(kwargs.get('payload') or {}).get('condition_id')
    if cid not in {'condition:typed.general_flight','condition:typed.cloud_walker_form'}:return
    for aid in kwargs.get('target_ids') or ():
        actor=engine.state.actors.get(aid)
        if actor is not None:pressure_arrival(engine,actor,actor.position,actor.position,getattr(engine,'_active_intent',None))


@hook('flight_grant_allowed')
def pressure_flight_grant(engine,actor,condition):
    """Withdraw only this family's suppressed flight, preserving other support."""
    return False if any(c.condition_id==SUPPRESSED and c.data.get('grant_id')==condition.instance_id
                        for c in actor.conditions.values()) else None


IMMERSED='condition:typed.scene_unstable_footing'


def ground_footing(engine,actor,*,moved=False):
    """Commit loss of ground-plane support without inventing depth or injury.

    A two-dimensional liquid/loose-material plane retains the native token at
    its real surface coordinate. The sourced state records swimming/sinking;
    no subterranean altitude, bottom, suffocation deadline or damage is guessed.
    Raised planes continue to use the native falling engine.
    """
    from ..flight import profile
    from .condition_ownership import remove_instance
    from ..falling import supported
    existing=[c for c in actor.conditions.values() if c.condition_id==IMMERSED]
    rows=surfaces(engine,actor,actor.position,include_broken=True) if actor.position.z==0 else []
    load=actual_weight(engine,actor)
    # Unknown equipment cannot make a body lighter. A known body alone may
    # prove loss of support; it can never prove support for an unknown load.
    body=environment(engine).get('bodies',{}).get(actor.entity_id)
    if load is None and body:load=measure(body['body_weight_lb'])
    independent=profile(engine,actor).speed_ft>0 or profile(engine,actor).hover
    row=next((r for r in rows if r['kind'] not in ATMOSPHERE and r['kind']!='solid'
        and load is not None and measure(r['capacity_lb'])<load),None)
    # The own-turn exception permits crossing; it cannot retroactively undo an
    # already resolved end-turn sinking result merely by opening another turn.
    same=bool(row and any(c.data.get('surface_id')==row['id'] for c in existing))
    light_step=moved and crossing_light(engine,actor) and row is not None and measure(row['capacity_lb'])>=1
    needed=row is not None and not independent and not light_step and (same or not supported(engine,actor))
    for held in existing:
        if not needed or held.data.get('surface_id')!=row['id']:
            remove_instance(engine,actor,held.instance_id,KEY)
    if needed and not any(c.condition_id==IMMERSED for c in actor.conditions.values()):
        liquid=row['kind'] in {'water','liquid'}
        sinking=row['kind'] in {'snow','mud','loose_sand','unstable_ground'}
        label=('Swimming in ' if liquid else 'Sinking into ' if sinking else 'Without support on ')+row['kind'].replace('_',' ')
        engine._apply_condition(actor,IMMERSED,KEY,actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'surface_id':row['id'],'kind':row['kind'],'movement_cost':2,
                'label':label+'; moving through it costs 1 extra foot per foot. No depth or injury is assumed.'})


@hook('movement_step_settled')
def settle_ground_footing(engine,actor,previous,destination,intent):
    if environment(engine) or any(c.condition_id==IMMERSED for c in actor.conditions.values()):
        ground_footing(engine,actor,moved=previous!=destination)


@hook('movement_segment_surcharge')
def ground_swimming_cost(engine,actor,previous,destination,mode):
    if mode!='walk' or not environment(engine):return None
    prior=surfaces(engine,actor,previous,include_broken=True)
    current=surfaces(engine,actor,destination,include_broken=True)
    if crossing_light(engine,actor) and all(measure(r['capacity_lb'])>=1 for r in [*prior,*current]):return None
    if any(c.condition_id==IMMERSED and any(r['id']==c.data.get('surface_id') for r in prior)
           for c in actor.conditions.values()):return 5
    if destination.z==0 and surfaces(engine,actor,destination,include_broken=True) and footing(engine,actor,destination) is False:
        return 5
    return None


@hook('event',nested=True)
def ground_support_changed(engine,event_type,kwargs):
    if event_type not in {'CONDITION_APPLIED','CONDITION_REMOVED'}:return
    if (kwargs.get('payload') or {}).get('condition_id')==IMMERSED:return
    # Support can come from any source. In a declared ground scene, an actual
    # condition transition (including release of a carried passenger) rechecks
    # the native support/profile query rather than guessing its source name.
    for aid in kwargs.get('target_ids') or ():
        actor=engine.state.actors.get(aid)
        if actor is not None and (environment(engine) or any(c.condition_id==IMMERSED for c in actor.conditions.values())):
            ground_footing(engine,actor)


def journey_pressure_fields(session,position):
    """Typed scene fields, using actual anchored map/encounter object profiles."""
    profile=(session.state['battlefield'].get('source_data') or {}).get(KEY,{})
    for row in profile.get('fields',()):
        if not (row['min_z']<=position.z<=row['max_z'] and [position.x,position.y] in row['cells']):continue
        if 'anchor_object_id' in row:
            oid=row['anchor_object_id']
            actual=session.state.get('cloud_anchor_states',{}).get(oid)
            if actual is None:
                from ..journey_assets import JourneyAssetContext
                from ..asset_anchor_runtime import source_profile
                context=JourneyAssetContext(session)
                obj=context.state.objects.get(oid)
                if obj is None or obj.destroyed:continue
                native=source_profile(context,obj)
                if not native['source_cl']:continue
                actual={'source_cl':native['source_cl'],'destroyed':0}
            if actual['destroyed'] or not actual['source_cl']:continue
            row={**row,'source_cl':actual['source_cl']}
        yield row


def journey_contest_scope(session,field,destination):
    from ..fact_consent_admission import digest
    route=getattr(session,'cloud_pressure_route',{})
    clock=route.get('clock',str(session.clock()))
    return digest({'field':field,'destination':destination.model_dump(mode='json'),'clock':clock})


def journey_contest_result(session,aid,field,destination):
    scope=journey_contest_scope(session,field,destination)
    return session.state['actors'][aid].get('cloud_pressure_checks',{}).get(scope,{}).get('success')==1


@hook('journey_options')
def journey_contest_options(session,aid):
    from .cloud_walker import travel_mist
    held=travel_mist(session,aid)
    if not held or session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:return None
    cl=int(held['source_cl']);options=[]
    from ..gate2_runtime_models import Position
    origin=Position.model_validate(session.state['actors'][aid]['position'])
    scene=(session.state['battlefield'].get('source_data') or {}).get(KEY,{})
    for cell in session.adjacent(aid):
        destination=Position.model_validate(cell)
        # A pressure check cannot create a route through ordinary solid geometry
        # or reveal a square this automatic traveller cannot see.
        if session.grid.terrain_at(destination,'BLOCKED') or not session.grid.line_of_physical_transmission(origin,destination):continue
        if origin.z==destination.z and not session.grid.step_legal(origin,destination):continue
        if session.state['actors'][aid]['control_mode']=='LOCAL_AUTO' and not session.grid.line_of_sight(origin,destination):continue
        if journey_boundaries_geometry(session,aid,origin,destination) is False:continue
        for field in journey_pressure_fields(session,destination):
            if field['absolute'] or not cl-2<=field['source_cl']<=cl+2:continue
            scope=journey_contest_scope(session,field,destination)
            if scope in session.state['actors'][aid].get('cloud_pressure_checks',{}):continue
            options.append({'id':'cloud_pressure:'+scope,'kind':'cloud_pressure_contest',
                'payload':{'field_id':field['id'],'destination':cell},
                'label':f"Wind Walk: {session.state['actors'][aid]['name']}, make a Cultivation Check (DC {field['save_dc']}) against {field['kind'].replace('_',' ')} pressure to travel to ({destination.x}, {destination.y}), {destination.z*5} feet high. No Qi cost."})
    if scene.get('fields'):options.extend(journey_pressure_routes(session,aid,held))
    return options


def journey_pressure_routes(session,aid,held):
    """Full native transit routes, including contests beyond the first occupant.

    A preview skips only equal-band adjudication, never geometry, support,
    occupancy, source/absolute barriers or automatic-seat observation gates.
    Its transient declaration context is not persisted or runtime patching.
    """
    from ..gate2_runtime_models import Position
    from ..fact_consent_admission import digest
    previous=getattr(session,'cloud_pressure_route',None)
    session.cloud_pressure_route={'actor_id':aid,'clock':str(session.clock()),'preview':1}
    try:paths=session.menu_routes(aid)
    finally:
        if previous is None:del session.cloud_pressure_route
        else:session.cloud_pressure_route=previous
    origin=Position.model_validate(session.state['actors'][aid]['position'])
    cl=int(held['source_cl']);out=[]
    for path in paths:
        cells=[Position.model_validate(c) for c in path]
        if session.state['actors'][aid]['control_mode']=='LOCAL_AUTO' and any(
                not session.grid.line_of_sight(origin,c) for c in cells):continue
        pairs=[(f,c) for c in cells for f in journey_pressure_fields(session,c)
               if not f['absolute'] and cl-2<=f['source_cl']<=cl+2]
        if not pairs:continue
        checks=session.state['actors'][aid].get('cloud_pressure_checks',{})
        scopes=[journey_contest_scope(session,f,c) for f,c in pairs]
        if any(scope in checks and not checks[scope]['success'] for scope in scopes):continue
        end=cells[-1];name=session.state['actors'][aid]['name']
        out.append({'id':'cloud_pressure_route:'+digest(path),'kind':'cloud_pressure_travel','payload':{'path':path},
            'label':f'Wind Walk: {name}, travel to ({end.x}, {end.y}), {end.z*5} feet high; '
                    'cross creatures as difficult terrain and make the required Cultivation Checks against pressure. '
                    'A failed check stops you before departure. No Qi cost.'})
    return out


@hook('journey_command')
def journey_contest_command(session,aid,kind,payload):
    if kind!='cloud_pressure_contest':return None
    from .cloud_walker import travel_mist
    from ..gate2_runtime_models import Position
    from ..gate2_rolls import DeterministicRollAuthority
    held=travel_mist(session,aid)
    require(held and session.state['phase']=='travel','Travel mist is required to contest this route.')
    require(set(payload)=={'field_id','destination'},'Choose the exact field and adjacent route destination.')
    destination=Position.model_validate(payload['destination'])
    origin=Position.model_validate(session.state['actors'][aid]['position'])
    require(session.grid.distance_cells(origin,destination)==1,'Choose an adjacent route destination.')
    field=next((r for r in journey_pressure_fields(session,destination) if r['id']==payload['field_id']),None)
    cl=int(held['source_cl'])
    require(field and not field['absolute'] and cl-2<=field['source_cl']<=cl+2,'That authority does not permit an equal-band contest.')
    scope=journey_contest_scope(session,field,destination)
    checks=session.state['actors'][aid].setdefault('cloud_pressure_checks',{})
    require(scope not in checks,'This route contest is already resolved at this time.')
    require(any(o['kind']==kind and o['payload']==payload for o in journey_contest_options(session,aid) or ()),
            'A pressure contest needs an open visible route and a live source.')
    roll_journey_contest(session,aid,held,field,destination)
    return True


def roll_journey_contest(session,aid,held,field,destination):
    """Resolve one declared destination check using its actual source numbers."""
    from ..gate2_rolls import DeterministicRollAuthority
    scope=journey_contest_scope(session,field,destination)
    checks=session.state['actors'][aid].setdefault('cloud_pressure_checks',{})
    if scope in checks:return bool(checks[scope]['success'])
    owner=session.state['actors'].get(held['source_actor_id'])
    numbers=next((r.get('numbers',{}) for r in (owner or {}).get('bundle',{}).get('typed_passives',()) if r.get('block')=='cloud_walker'),{})
    if 'source_pb' in held and 'source_key_mod' in held:
        numbers={**numbers,'pb':held['source_pb'],'key_mod':held['source_key_mod']}
    require('pb' in numbers and 'key_mod' in numbers,'This old travel effect lacks its source’s Cultivation Check numbers; resolve the contest with its source present in combat.')
    roll=DeterministicRollAuthority(session.state['journey_id']+':'+aid+':'+scope).d20(
        modifier=int(numbers.get('pb',0))+int(numbers.get('key_mod',0)),actor_id=aid,reason='CLOUD_WALKER_SOURCE_CONTEST')
    success=int(roll.total>=field['save_dc'])
    checks[scope]={'success':success,'field_id':field['id']}
    session.emit('CULTIVATION_CHECK',aid,source=field['source_id'],field_id=field['id'],
        roll=roll.model_dump(mode='json'),dc=field['save_dc'],success=success,
        text='Wind Walk: '+session.state['actors'][aid]['name']+' makes a Cultivation Check against '+field['kind'].replace('_',' ')+' pressure.')
    return bool(success)


@hook('journey_command')
def journey_pressure_travel(session,aid,kind,payload):
    if kind!='cloud_pressure_travel':return None
    from .cloud_walker import travel_mist
    from ..gate2_runtime_models import Position
    held=travel_mist(session,aid)
    require(held and any(o['kind']==kind and o['payload']==payload for o in journey_contest_options(session,aid) or ()),
            'Choose a currently available Wind Walk route through pressure.')
    previous=getattr(session,'cloud_pressure_route',None)
    session.cloud_pressure_route={'actor_id':aid,'clock':str(session.clock()),'preview':0}
    departed=False
    try:
        cl=int(held['source_cl'])
        for cell in payload['path']:
            destination=Position.model_validate(cell)
            for field in journey_pressure_fields(session,destination):
                if not field['absolute'] and cl-2<=field['source_cl']<=cl+2:
                    if not roll_journey_contest(session,aid,held,field,destination):
                        session.emit('CLOUD_PRESSURE_ROUTE_STOPPED',aid,source=field['source_id'],
                            text='Wind Walk: '+session.state['actors'][aid]['name']+' fails the pressure check and stays at the route’s departure.')
                        return True
        departed=True
        session.move(aid,payload)
    finally:
        if departed:session.state['actors'][aid].pop('cloud_pressure_checks',None)
        if previous is None:del session.cloud_pressure_route
        else:session.cloud_pressure_route=previous
    return True


@hook('journey_elapsed')
def clear_journey_contests(session,aid,before,seconds,moving):
    route=getattr(session,'cloud_pressure_route',{})
    if seconds>0 and route.get('actor_id')!=aid:session.state['actors'][aid].pop('cloud_pressure_checks',None)


@hook('journey_encounter_settled')
def export_journey_anchors(session,aid,engine,creature):
    profile=environment(engine)
    ids={r['anchor_object_id'] for r in profile.get('fields',()) if 'anchor_object_id' in r}
    if not ids:return
    from ..asset_anchor_runtime import source_profile
    states=session.state.setdefault('cloud_anchor_states',{})
    for oid in ids:
        obj=engine.state.objects.get(oid)
        states[oid]={'destroyed':int(obj is None or obj.destroyed),
                     'source_cl':int(source_profile(engine,obj)['source_cl'] or 0) if obj else 0}
    from ..fact_consent_admission import digest
    key=digest(session.state['battlefield'])
    actor=session.state['actors'][aid]
    actor.setdefault('source_states',{})[KEY+'.environment']={'map':key,'anchors':dict(states)}


@hook('journey_initialize')
def restore_journey_anchors(session,aid):
    from ..fact_consent_admission import digest
    saved=session.state['actors'][aid].get('source_states',{}).get(KEY+'.environment')
    if saved and saved.get('map')==digest(session.state['battlefield']):
        session.state.setdefault('cloud_anchor_states',{}).update(saved['anchors'])
