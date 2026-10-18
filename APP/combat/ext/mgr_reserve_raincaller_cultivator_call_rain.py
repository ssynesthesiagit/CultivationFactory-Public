"""Raincaller native producer and consumers.

One sealed controller owns rain geometry, designation, form/decree choices,
source contests and elapsed regional work. Existing zones, concentration,
area_suppression, granted_movement, end_effect and fact_consent_admission own
those general procedures. Without an acquired feature this module is inert.
"""
from copy import deepcopy
from dataclasses import replace
import json
from . import hook, effect

BASE='tianxia.subpath.qi.raincaller_cultivator.feature.'
CALL,SHAPE,WALL,RITE,SOVEREIGN=[BASE+n for n in ('call_rain','shape_the_rain','monsoon_wall','provincial_rain_rite','monsoon_sovereign')]
LEVELS={CALL:3,SHAPE:6,WALL:10,RITE:14,SOVEREIGN:18}
FORMS={'mist':'Mist Rain','heavy':'Heavy Rain','restorative':'Restorative Rain','driving':'Driving Rain','cleansing':'Cleansing Rain'}
DECREES={'gentle':'Gentle Rain','flood':'Driving Flood','purification':'Purification','lightning':'Lightning','veiling':'Veiling Rain','channel':'Safe Channel'}
PROVINCES={'steady':'Steady Rain','drought':'Drought Relief','firebreak':'Firebreak Rain','clearing':'Clearing Rain','cooling':'Cooling Rain','agriculture':'Agricultural Blessing','mist':'Veiling Mist'}
PROVINCE_LABELS={
    'steady':'Steady Rain: about one inch of moderate rain over 8 hours fills cisterns, waters crops and supports irrigation; no flash flood without natural terrain or drainage cause.',
    'drought':'Drought Relief: plants and soil receive one normal day of moisture; dead crops and permanent ecological damage remain.',
    'firebreak':'Firebreak Rain: ordinary wildfire cannot spread into the rain and loses one 10-foot section per minute. Persistent supernatural wildfire of lower Cultivation Level is suppressed in overlap; equal or stronger sources require a Cultivation Check against their save DC.',
    'clearing':'Clearing Rain: clears ordinary airborne smoke, dust, ash, pollen and pollution over 10 minutes. Lower Cultivation Level supernatural sources are suppressed; equal or stronger sources require one Cultivation Check against their save DC when the Rite begins.',
    'cooling':'Cooling Rain: dangerous environmental heat becomes tolerable; active Fire techniques and lava remain dangerous.',
    'agriculture':'Agricultural Blessing: useful living crops and plants gain Advantage against ordinary drought, heat and minor pests for seven days, with a modest yield improvement if the growing season remains viable.',
    'mist':'Veiling Mist: visibility beyond 300 feet is Lightly Obscured for 8 hours; choose recorded roads, buildings or agricultural zones to remain clear.'}
PURIFIABLE_CONDITIONS={'poisoned','blinded','disease','diseased'}
RAIN_SOURCES={'call':CALL,'wall':WALL,'sovereign':SOVEREIGN,'rite':RITE}
RAIN_NAMES={'call':'Call Rain','wall':'Monsoon Wall','sovereign':'Monsoon Sovereign','rite':'Provincial Rain Rite'}
FORM_LABELS={
    'mist':'Mist Rain: Lightly Obscured to hostile creatures; chosen allies see normally.',
    'heavy':'Heavy Rain: difficult terrain for hostiles; chosen allies ignore it.',
    'restorative':'Restorative Rain: each ally gains your proficiency bonus in Temporary Hit Points at its turn start, once per round.',
    'driving':'Driving Rain: each hostile entering or starting saves Strength; push 10 feet on failure or 5 on success, once per turn.',
    'cleansing':'Cleansing Rain: allies have Advantage on saves against Poisoned, disease, smoke, dust, ash and inhaled hazards; existing conditions remain.'}
DECREE_LABELS={
    'gentle':'Gentle Rain: heal up to two allies inside for 2d8 + your key ability modifier Hit Points each.',
    'flood':'Driving Flood: choose hostiles in a 20-foot radius; Strength save, push or pull 15 feet and knock Prone on failure, 5 feet without Prone on success.',
    'purification':'Purification: choose up to your proficiency bonus in allies; end qualifying poison, airborne Blindness or one ordinary disease, or repeat a stronger source’s save with Advantage. Source strength uses Cultivation Level.',
    'lightning':'Lightning: hostiles in a 10-foot-radius, 30-foot-high cylinder save Dexterity; 5d8 Lightning and no Reactions until their next turn on failure, half damage on success.',
    'veiling':'Veiling Rain: a 20-foot-radius area is Heavily Obscured to hostiles until your next turn; chosen allies see normally.',
    'channel':'Safe Channel: up to two willing allies each choose a legal destination inside, moving up to 15 feet without provoking.'}


def bind_rain_concentration(engine,owner,zone):
    """Bind the newly started copy before another child can move it to held state.

    Re-publish the existing concentration event with its completed state so the
    mechanical reducer and cold reload retain this exact zone, too.
    """
    owner.concentration.zone_id=zone.zone_id
    zone.concentration_link=True
    engine._append_event('CONCENTRATION_STARTED',zone.source_definition_id,actor_id=owner.entity_id,
                         payload={'reason':'AREA_BOUND'})


RECORD_HASHES={CALL:'a8bcdb4d48b5dda4a47ffa36f1a063a91bec5e8dcf71e55d851cfba0668447b0',
              SHAPE:'4a9f4e7122e34cbf20fdebd608e29a38bce33e7cd1579c5e5405e29ab43f777f',
              WALL:'b124b00ab6d2f068fe0ec3bf2e85c8928c33c80d0152c3c3bbccdb8cad7fab71',
              RITE:'f7aa14f0bbd78335df068fe952c7efff4b6b6fde98e014a74edd532e045098b3',
              SOVEREIGN:'ea63198549a9775a1081d2e5abff44bbaf537d13767da190ea44bc59743cc522'}


def rain_source_profile(source,numbers,concentrating):
    """The actual rain-producing source, in the existing ZoneSource contract."""
    from ..zone_sources import SCHEMA
    return {'schema':SCHEMA,'mechanic_id':source,'sphere_id':'','text_sha256':RECORD_HASHES[source],
            'source_tags':['Rain'],'source_cl':int(numbers['cl']),'save_dc':int(numbers['save_dc']),
            'duration_kind':'hours' if source==RITE else 'minutes','activation_duration_kind':'minutes',
            'concentration':int(concentrating),'mundane':0}


def owner_start(engine,actor):
    from .effect_durations import token
    return token('start',actor.entity_id,actor.turns_started+1)


def source_of(action):
    return (action.parameters.get('typed') or {}).get('source') if action else None


@hook('compile_passives')
def acquired(rows,info):
    return [*[r for r in rows if r.get('feature_id') not in LEVELS],
            *[{'block':'raincaller_acquired','feature_id':s,'cl':int(info['numbers']['cl']),'numbers':deepcopy(info['numbers'])}
              for s,level in LEVELS.items() if s in info['owned_ids'] and int(info['numbers']['cl'])>=level]]


def owns(engine,actor,source):
    return any(r.get('block')=='raincaller_acquired' and r.get('feature_id')==source
               for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,()))


def journey_owns(session,aid,source):
    return any(r.get('block')=='raincaller_acquired' and r.get('feature_id')==source
               for r in session.state['actors'][aid]['bundle'].get('typed_passives',()))


def rainzones(engine,owner=None,kind=None):
    return [z for z in engine.state.zones.values() if z.active
            and (owner is None or z.owner_id==getattr(owner,'entity_id',owner))
            and (p:=z.trigger_profile.get('profile',{})).get('rain_family')
            and z.owner_id in engine.state.actors
            and owns(engine,engine.state.actors[z.owner_id],source_of(engine.action_catalog.get(z.source_definition_id)) or z.source_definition_id)
            and (kind is None or p['rain_family']==kind)]


def record(engine,zone,**values):
    from .tabik_dark import republish
    zone.trigger_profile['profile']={**zone.trigger_profile.get('profile',{}),**values}
    republish(engine,zone,zone.source_definition_id)


def inside(engine,zone,subject):
    from ..spatial_areas import positions_inside_zone
    return bool(positions_inside_zone(engine,[(subject.position.x,subject.position.y,subject.position.z)],zone))


def point_inside(engine,zone,point):
    from ..spatial_areas import positions_inside_zone
    return bool(positions_inside_zone(engine,[(point.x,point.y,point.z)],zone))


def enemy(engine,zone,actor):
    from ..relations import relation,ENEMY
    return relation(engine,engine.state.actors[zone.owner_id],actor)==ENEMY


def ally(engine,zone,actor):
    return actor.entity_id in zone.trigger_profile.get('profile',{}).get('allies',())


def is_ally(engine,zone,actor):
    from ..relations import relation,ALLY
    owner=engine.state.actors[zone.owner_id]
    return actor is owner or relation(engine,owner,actor)==ALLY


def ask(ctx,key,options,**kwargs):
    from .needle import ask as choose,checkpoint_id
    return choose(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'raincaller',ctx.source,key),ctx.actor,
                  'choice:needle.rain_'+key,list(options),name=ctx.action.display_name,feature_id=ctx.source,**kwargs)


def choose_allies(ctx):
    from ..relations import relation,ALLY
    from ..target_knowledge import located
    options=[a for a in ctx.engine.state.actors.values() if a.active
             and (a is ctx.actor or relation(ctx.engine,ctx.actor,a)==ALLY)
             and located(ctx.engine,ctx.actor,a)]
    return ask(ctx,'allies',[a.entity_id for a in options],labels={a.entity_id:a.display_name for a in options},
               minimum=0,maximum=len(options),allow_decline=True,preferred=[a.entity_id for a in options],default='all',
               prompt=f'{ctx.action.display_name}: designate allies who benefit from this rain for its one-minute duration. No extra cost.') if options else []


@hook('compile_action')
def action_contract(action,info):
    source=source_of(action)
    if source not in LEVELS or (action.parameters.get('raincaller_collection') or action.parameters.get('raincaller_origin') or action.parameters.get('raincaller_end')):return None
    typed=deepcopy(action.parameters['typed'])
    typed.update(min_cl=LEVELS[source],manual_inline_choice=True,modifier=None,options=None,riders=[],zone_spec=None,
                 # The source controller admits concentration after actual area
                 # selection, because Sovereign can replace that requirement.
                 duration={'kind':'instant'},tags=['Rain'],effects=[{'type':'raincaller_area','kind':{CALL:'call',WALL:'wall',SOVEREIGN:'sovereign',RITE:'rite',SHAPE:'shape'}[source]}])
    if source in (SHAPE,RITE):
        return action.model_copy(update={'parameters':{**action.parameters,'typed':typed}})
    size=50 if source==SOVEREIGN else 20
    typed['area']={'shape':'cylinder','size_ft':size,'height_ft':50 if source==SOVEREIGN else 20} if source!=WALL else None
    return action.model_copy(update={'target_kind':'CELL','range_ft':120 if source==SOVEREIGN else 60,
        'parameters':{**action.parameters,'typed':typed,'any_cell':True,'ai_allow_empty_area':True,
                      'description':f'{action.display_name}: Action, { {CALL:1,WALL:4,SOVEREIGN:8}[source]} Qi; rain lasts 1 minute with Concentration.'}})


@hook('candidate_allowed')
def admission(engine,actor,candidate,action):
    source=source_of(action)
    if source not in LEVELS or (action.parameters.get('raincaller_collection') or action.parameters.get('raincaller_origin') or action.parameters.get('raincaller_end')):return None
    if not owns(engine,actor,source) or source in (RITE,SHAPE):return False
    if source==SOVEREIGN and any(c.condition_id=='condition:typed.raincaller_scene_use' for c in actor.conditions.values()):return False
    aim=candidate.destination
    if aim is None:return False
    from ..gate2_runtime_models import Position
    from ..action_geometry import point as origin_point
    if engine.grid.terrain_at(aim,'BLOCKED') or not engine.grid.line_of_physical_transmission(origin_point(engine,actor),aim):return False
    if source==CALL:
        height=20
        if any(engine.grid.terrain_at(Position(x=aim.x,y=aim.y,z=aim.z+z),'BLOCKED') for z in range(height//5)):return False
        if not engine.grid.line_of_physical_transmission(aim,Position(x=aim.x,y=aim.y,z=aim.z+3)):return False
        held=combat_site(actor)
        if held and (held.data['state']['site']['sealed'] or not held.data['state']['site']['open_space']):return False
        return open_air(engine,aim)
    return True


def open_air(engine,aim):
    """Derive an air route from actual walls, apertures and roofs; no narration.

    An unroofed native cell is positively open. For a roofed point, use the
    physical-transmission graph to find a real open aperture/air route. The
    native map's outside edge is never itself evidence that a sealed roof opens.
    """
    from collections import deque
    from ..gate2_runtime_models import Position
    from ..read_queries import memo
    def derive():
        grid=engine.grid
        roof=grid.roof_at(aim.x,aim.y)
        if roof is None or aim.z*5>=roof.height_ft:return True
        top=max([aim.z+1,*[(grid.roof_height_at(x,y) or 0)//5+1 for x in range(grid.width) for y in range(grid.height)]])
        start=(aim.x,aim.y,aim.z);queue=deque([start]);seen={start}
        while queue:
            x,y,z=queue.popleft();cover=grid.roof_at(x,y)
            if cover is None or z*5>=cover.height_ft:return True
            for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                nxt=(x+dx,y+dy,z+dz)
                if nxt in seen or not (0<=nxt[0]<grid.width and 0<=nxt[1]<grid.height and 0<=nxt[2]<=top):continue
                seen.add(nxt);point=Position(x=nxt[0],y=nxt[1],z=nxt[2])
                if grid.terrain_at(point,'BLOCKED'):continue
                if grid.line_of_physical_transmission(Position(x=x,y=y,z=z),point):queue.append(nxt)
        return False
    return memo(engine,('raincaller_open_air',aim.x,aim.y,aim.z),derive)


def form_profile(form):
    return {'difficult':'hostile' if form=='heavy' else None,'obscured':'light' if form=='mist' else None,
            'triggers':[{'on':['enter','start'],'who':'hostile','effects':[{'type':'raincaller_push','wall':False}]}] if form=='driving' else []}


def set_form(engine,zone,form):
    from .tabik_dark import republish
    zone.trigger_profile.update(form_profile(form))
    zone.trigger_profile['profile']['form']=form
    republish(engine,zone,zone.source_definition_id)


@effect('raincaller_area')
def activate(ctx,row):
    source=source_of(ctx.action)
    if source not in LEVELS or not owns(ctx.engine,ctx.actor,source):return
    kind=row['kind']
    if kind not in ('call','wall','sovereign'):return
    from .. import zones,concentration
    from .tabik_dark import republish
    allies=choose_allies(ctx)
    form=''
    if kind=='call' and owns(ctx.engine,ctx.actor,SHAPE):
        form=(ask(ctx,'form',FORMS,labels=FORM_LABELS,prompt='Call Rain: choose one Rain Form for the one-minute area. You may change it at the start of your turns without an action; activation costs 1 Qi.') or ['mist'])[0]
    if kind=='call':
        for old in rainzones(ctx.engine,ctx.actor,'call'):zones.remove(ctx.engine,old,'REPLACED')
    aim=ctx.intent.destination
    size,height=(50,50) if kind=='sovereign' else (30,10) if kind=='wall' else (20,20)
    spec={'name':ctx.action.display_name,'shape':'cylinder','size_ft':size,'height_ft':height,
          'placed':True,'duration':{'kind':'minutes','amount':1},'profile':{'rain_family':kind,'allies':allies,'form':form},
          'visual':{'material':'water'},'terrain':[]}
    if kind=='call':spec.update(form_profile(form))
    if kind=='wall':
        spec.update(shape='wall',obscured='heavy',difficult='hostile',wall={'height_ft':10,'thick_ft':5,'obscures':'hostile'},
                    triggers=[{'on':['enter','start'],'who':'hostile','effects':[{'type':'raincaller_push','wall':True}]}])
    if kind=='sovereign':spec['difficult']='hostile'
    prospective=zones.prospective_zone(ctx,spec,aim)
    # Native in_area supplies physical barrier and finite-height clipping.
    from ..gate2_runtime_models import Position
    parent=next((z for z in rainzones(ctx.engine,kind='sovereign')
                 if all(point_inside(ctx.engine,z,Position(x=c.x,y=c.y,z=aim.z+height//5-1))
                        and point_inside(ctx.engine,z,Position(x=c.x,y=c.y,z=aim.z)) for c in prospective.affected_cells)),None) if kind in ('call','wall') else None
    if parent is None:
        ctx.engine._start_concentration(ctx.actor,ctx.source)
        spec['duration']['concentration']=True
    else:spec['profile']['sovereign_parent']=parent.zone_id
    spec['source_profile']=rain_source_profile(source,ctx.numbers,parent is None)
    zone=zones.create(ctx,spec)
    if zone is None:return
    if kind=='sovereign':
        ctx.engine._apply_condition(ctx.actor,'condition:typed.raincaller_scene_use',ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Monsoon Sovereign used this scene'})
        for child in rainzones(ctx.engine):
            if child is zone or child.trigger_profile['profile']['rain_family'] not in ('call','wall'):continue
            h=int(child.trigger_profile.get('height_ft') or 0)//5
            if all(point_inside(ctx.engine,zone,Position(x=c.x,y=c.y,z=child.center.z+h-1)) and point_inside(ctx.engine,zone,c)
                   for c in child.affected_cells):
                child_owner=ctx.engine.state.actors[child.owner_id]
                concentrations=[held for _,held in concentration.held(child_owner)]+([child_owner.concentration] if child_owner.concentration else [])
                for held in concentrations:
                    if held.zone_id==child.zone_id:concentration.end_copy(ctx.engine,child_owner,held.started_sequence,'SOVEREIGN',retain_zone=True)
                child.concentration_link=False
                record(ctx.engine,child,sovereign_parent=zone.zone_id)
    record(ctx.engine,zone,wet=1)
    reconcile_environment(ctx.engine,zone)
    settle_combat_site(ctx.engine,zone)
    for target in ctx.engine.state.actors.values():wash_ordinary_irritants(ctx.engine,zone,target)


@hook('zone_obscuration_ignored')
def clear_allies(engine,zone,viewer,seen):
    if not zone.trigger_profile.get('profile',{}).get('rain_family'):return None
    return not enemy(engine,zone,viewer)


@hook('obscurement_ignored')
def clear_allies_legacy(engine,zone,viewer,seen):
    return clear_allies(engine,zone,viewer,seen)


@hook('zone_recipient_allowed')
def chosen_recipient(engine,zone,actor,spec):
    if not zone.trigger_profile.get('profile',{}).get('rain_family'):return None
    if spec.get('who')=='hostile':return enemy(engine,zone,actor)
    return None


@hook('save_mode')
def rain_saves(engine,target,ability,dc,source_id,roll_context):
    # Native d20 named/source classification is explicit, never damage/name inference.
    named={str(v).lower() for v in (roll_context or {}).get('named',())}
    for zone in rainzones(engine):
        if not inside(engine,zone,target):continue
        profile=zone.trigger_profile['profile']
        if profile['rain_family']=='call' and ally(engine,zone,target) and named & {'environmental heat','environmental_heat'}:return 'ADVANTAGE'
        if is_ally(engine,zone,target) and profile.get('form')=='cleansing' and named & {'poisoned','disease','smoke','dust','ash','inhaled_hazard','inhaled hazards'}:return 'ADVANTAGE'
    return None


@hook('zone_trigger_context')
def push_context(ctx,zone,creature,moment):
    if zone.trigger_profile.get('profile',{}).get('rain_family'):
        ctx.damage_cache['rain_zone']=zone.zone_id


@effect('raincaller_push',harmful=True)
def push(ctx,row):
    from .. import typed_executor as te
    target=ctx.target
    zone=ctx.engine.state.zones.get(ctx.damage_cache.get('rain_zone'))
    if target is None or zone is None:return
    effects=[{'type':'forced_movement','applies_to':'target','distance_ft':15 if row['wall'] else 10}]
    if row['wall']:effects.append({'type':'speed','applies_to':'target','flat':-10,'duration':'until_start_of_next_turn'})
    ctx.damage_cache['rain_nearest_edge']=zone.zone_id if row['wall'] else None
    te.run_effects(ctx,[{'type':'save','ability':'str','dc':'technique_save_dc','on_fail':effects,
                         'on_success':[{'type':'forced_movement','applies_to':'target','distance_ft':5}]}])


@hook('forced_movement_direction')
def nearest_edge(ctx,target,distance_ft):
    zid=ctx.damage_cache.get('rain_nearest_edge')
    if not zid:return None
    z=ctx.engine.state.zones.get(zid)
    if z is None:return None
    cells={(p.x,p.y) for p in z.affected_cells};routes=[]
    for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
        n=1
        while (target.position.x+dx*n,target.position.y+dy*n) in cells:n+=1
        routes.append((n,dx,dy))
    best=min(r[0] for r in routes);opts=[f'{dx},{dy}' for n,dx,dy in routes if n==best]
    picked=ask(ctx,'edge',opts,labels={v:'Push toward the nearest '+{'1,0':'east','-1,0':'west','0,1':'south','0,-1':'north'}[v]+' edge of the wall' for v in opts},
        prompt=f'Monsoon Wall: choose a nearest edge to push {target.display_name} {distance_ft} feet.',target_id=target.entity_id)
    return tuple(map(int,(picked or opts)[0].split(',')))


def crossing(engine,zone,a,b):
    from ..zone_attack_geometry import path_distance_ft
    from ..action_geometry import point
    origin=point(engine,a)
    projected=a.model_copy(update={'position':origin})
    return path_distance_ft(engine,zone,projected,b)


@hook('attack_geometry_mode')
def ranged_rain(engine,attacker,target,ranged):
    if ranged is not True:return None
    frame=engine.d20_context() or {}
    if frame.get('attack_delivery')!='weapon':return None
    if any(enemy(engine,z,attacker) and crossing(engine,z,attacker,target)>=10
           for z in rainzones(engine,kind='sovereign')):
        return {'mode':'DISADVANTAGE','cause':'weather'}
    return None


@hook('damage_defenses')
def fire_defense(engine,target,damage_type,typed,source_actor_id):
    if str(damage_type).upper()!='FIRE':return None
    if any(is_ally(engine,z,target) and inside(engine,z,target) for z in rainzones(engine,kind='sovereign')):
        return [{'kind':'resistance','damage_types':['FIRE']}]
    source=engine.state.actors.get(source_actor_id)
    # The confirmed native packet and its scoped d20 descriptor distinguish
    # ranged attacks from an unrelated ranged save or damage aura.
    packet=engine.damage_context()
    frame=engine.d20_context() or {}
    if (source is None or packet is None or packet.attacker_id!=source_actor_id or packet.target_id!=target.entity_id
            or frame.get('kind')!='attack' or (frame.get('spec') or {}).get('range_ft') is None):return None
    if any(crossing(engine,z,source,target)>=5 for z in rainzones(engine,kind='wall')):
        return [{'kind':'resistance','damage_types':['FIRE']}]
    return None


@hook('effect_origins')
def sovereign_origins(engine,actor,action):
    if action.parameters.get('raincaller_origin') or action.parameters.get('raincaller_collection'):return None
    typed=action.parameters.get('typed') or {}
    tags={str(s).lower() for s in typed.get('tags',())}
    tags.update(str(tag).lower() for row in typed.get('effects',()) for tag in row.get('source_tags',()))
    if not tags&{'water','rain','mist','lightning','weather'} or not owns(engine,actor,SOVEREIGN):return None
    from ..gate2_runtime_models import Position
    for c in actor.conditions.values():
        if c.condition_id!='condition:typed.raincaller_origin':continue
        z=engine.state.zones.get(c.data['zone_id']);point=Position.model_validate(c.data['position'])
        if z in rainzones(engine,actor,'sovereign') and point_inside(engine,z,point):
            return [{'id':z.zone_id+':'+str(c.instance_id),'label':'Chosen Monsoon Sovereign rain origin','position':point.model_dump(mode='json')}]
    return None


def reconcile_environment(engine,rain):
    """Operate on explicitly classified native areas, never names or damage."""
    from ..zone_sources import of
    from .area_suppression import suppress
    profile=rain.trigger_profile['profile'];kind=profile['rain_family'];owner=engine.state.actors[rain.owner_id]
    mine=int(rain.trigger_profile['numbers']['cl'])
    for other in list(engine.state.zones.values()):
        if other is rain or not other.active:continue
        source=of(other)
        if source is None:continue
        tags={v.lower() for v in source.get('source_tags',())}
        ordinary=source.get('mundane')==1
        fire='fire' in tags;particles=bool(tags&{'dust','ash','smoke','pollen'})
        if not (fire or particles):continue
        overlap=[p for p in other.affected_cells if point_inside(engine,rain,p)]
        if not overlap:continue
        effects=set(profile.get('effects',()))
        age=(engine.state.round_number-rain.created_round)*6+int(profile.get('civil_age_seconds',0))
        permitted=ordinary and (kind=='call' and (particles or fire and (source.get('unattended')==1 or 'unattended' in tags))
                   or kind=='wall' and fire and (source.get('unattended')==1 or 'unattended' in tags)
                   or kind=='sovereign' and fire
                   or kind=='rite' and particles and 'clearing' in effects and age>=600)
        if ordinary and kind=='rite' and fire and 'wildfire' in tags and 'firebreak' in effects:
            minutes=age//60
            clocks=profile.setdefault('firebreak_minutes',{})
            loss=max(0,minutes-clocks.get(other.zone_id,0))*2
            if loss:
                overlap=overlap[:loss]
                clocks[other.zone_id]=minutes
                record(engine,rain,firebreak_minutes=clocks)
                permitted=True
        supernatural=(kind=='wall' and fire or kind=='rite' and ('firebreak' in effects and fire and 'wildfire' in tags
                          or 'clearing' in effects and particles)) and not ordinary and source.get('duration_kind')!='instant'
        if supernatural and not counterprocedure_allowed(engine,other.source_definition_id,source,WALL if kind=='wall' else RITE):continue
        if supernatural:
            contests=profile.setdefault('contests',{})
            if other.zone_id not in contests:
                if int(source['source_cl'])<mine:contests[other.zone_id]=1
                else:
                    # Clearing Rain gets its equal/higher contest only when
                    # the Rite begins, against sources actually present then.
                    birth=lambda zid:next((e.sequence for e in engine.events if e.event_type=='ZONE_CREATED' and (e.payload.get('zone') or {}).get('zone_id')==zid),engine.state.event_sequence+1)
                    if kind=='rite' and 'clearing' in effects and particles and birth(other.zone_id)>birth(rain.zone_id):
                        contests[other.zone_id]=0
                    else:
                        from .ability_source import cultivation_check
                        contests[other.zone_id]=int(cultivation_check(engine,owner,rain.trigger_profile['numbers'],int(source['save_dc']),rain.source_definition_id,'Raincaller Cultivation Check'))
                record(engine,rain,contests=contests)
            permitted=bool(contests[other.zone_id])
        if permitted:
            if ordinary and (fire or kind=='rite' and particles):
                from .. import zones
                from .tabik_dark import republish
                gone={(p.x,p.y,p.z) for p in overlap}
                other.affected_cells=tuple(p for p in other.affected_cells if (p.x,p.y,p.z) not in gone)
                if not other.affected_cells:zones.remove(engine,other,'ORDINARY_FIRE_EXTINGUISHED')
                else:republish(engine,other,rain.source_definition_id)
            else:suppress(engine,owner,other,'UNTIL_REMOVED',rain.zone_id,cells=overlap)


@hook('choice_reactors')
def rain_decision_owners(engine):
    owners={z.owner_id for z in rainzones(engine)}
    for zone in rainzones(engine,kind='sovereign'):
        owners.update(a.entity_id for a in engine.state.actors.values() if a.active and is_ally(engine,zone,a) and inside(engine,zone,a))
    return tuple(sorted(owners))


@hook('turn_start_choice')
def rain_turn(engine,actor):
    from . import placed
    from .. import typed_executor as te,zones
    from ..gate2_runtime_models import Position
    for z in list(rainzones(engine)):
        p=z.trigger_profile['profile'];owner=engine.state.actors[z.owner_id]
        ctx=placed.context(engine,owner,z.source_definition_id,z.trigger_profile['numbers'])
        ctx.typed['manual_inline_choice']=True
        if owner is actor:
            if p['rain_family']=='call' and owns(engine,owner,SHAPE):
                form=(ask(ctx,'form',FORMS,labels=FORM_LABELS,preferred=[p.get('form') or 'mist'],
                    prompt='Shape the Rain: choose this turn’s Rain Form. No action or Qi; the original one-minute duration continues.') or [p.get('form') or 'mist'])[0]
                set_form(engine,z,form)
            if p['rain_family']=='sovereign':decree(ctx,z)
        if not z.active:continue
        if p['rain_family']=='call' and p.get('form')=='restorative' and is_ally(engine,z,actor) and inside(engine,z,actor):
            key='_round_rain_restore:'+owner.entity_id
            if actor.turn_flags.get(key)!=engine.state.round_number:
                actor.turn_flags[key]=engine.state.round_number
                engine._grant_temp_hp(actor,int(z.trigger_profile['numbers']['pb']),z.source_definition_id,owner.entity_id)
        reconcile_environment(engine,z)
        settle_combat_site(engine,z)


def choose_subjects(ctx,zone,key,maximum):
    from ..target_knowledge import located
    options=[a for a in ctx.engine.state.actors.values() if a.active and is_ally(ctx.engine,zone,a)
             and inside(ctx.engine,zone,a) and located(ctx.engine,ctx.actor,a)]
    selected=ask(ctx,key,[a.entity_id for a in options],labels={a.entity_id:a.display_name for a in options},minimum=0,maximum=min(maximum,len(options)),allow_decline=True,
                 preferred=[a.entity_id for a in options[:maximum]],prompt=f'Monsoon Sovereign: choose up to {maximum} allies in the rain for {DECREES[key]}. No extra Qi.') if options else []
    return [a for a in options if a.entity_id in selected]


def decree(ctx,zone):
    from .. import typed_executor as te
    from ..gate2_runtime_models import Position
    from . import placed
    mode=(ask(ctx,'decree',DECREES,labels=DECREE_LABELS,prompt='Monsoon Sovereign: choose one decree at the start of this turn. No extra action or Qi; the one-minute rain continues. An ally may receive one non-area decree each turn.') or ['gentle'])[0]
    numbers=ctx.numbers
    if mode in ('gentle','purification','channel'):
        selected_targets=choose_subjects(ctx,zone,mode,int(numbers['pb']) if mode=='purification' else 2)
        eligible=[]
        for target in selected_targets:
            key='_round_rain_decree:'+str(ctx.engine.state.current_slot_index)+':'+str(ctx.engine.state.current_actor_id)
            token=str(ctx.engine.state.round_number)+':'+str(ctx.engine.state.actors[ctx.engine.state.current_actor_id].turns_started)
            if target.turn_flags.get(key)==token:continue
            target.turn_flags[key]=token
            if mode=='gentle':
                eligible.append(target)
                continue
            sub=replace(ctx,target=target,targets=[target])
            if mode=='purification':purify(sub)
            else:
                from .granted_movement import choices,move
                paths=[c for c in choices(ctx.engine,target,15) if point_inside(ctx.engine,zone,c.destination)]
                by={f'{c.destination.x},{c.destination.y},{c.destination.z}':c for c in paths}
                dest=channel_destination(ctx,target,by) if by else []
                if dest:move(ctx.engine,target,by[dest[0]],ctx.intent,15,[a.entity_id for a in ctx.engine.state.actors.values() if a.entity_id!=target.entity_id],name='Safe Channel')
        if mode=='gentle' and eligible:
            te.run_effects(replace(ctx,target=None,targets=eligible),[{'type':'healing','applies_to':'target','dice':{'count':2,'sides':8},'formula':'key_ability_modifier'}])
        return
    # Player may choose every point in the actual 3D field, even empty ground.
    points={f'{c.x},{c.y},{h}':Position(x=c.x,y=c.y,z=h) for c in zone.affected_cells for h in range(zone.center.z,zone.center.z+10)
            if point_inside(ctx.engine,zone,Position(x=c.x,y=c.y,z=h))}
    choice=ask(ctx,'point',points,labels={k:'Rain point '+k for k in points},prompt=f'{DECREES[mode]}: choose a point inside Monsoon Sovereign.')
    if not choice:return
    point=points[choice[0]];area={'shape':'cylinder','size_ft':10 if mode=='lightning' else 20,'height_ft':30 if mode=='lightning' else 50}
    if mode=='veiling':
        cells=placed.area(ctx.engine,point,'sphere',20)
        veil=placed.place(ctx.engine,ctx.actor,source=ctx.source,tag='rain_veil',cells=cells,shape='cylinder',size_ft=20,name='Veiling Rain',obscured='heavy',
            placed={'until':owner_start(ctx.engine,ctx.actor)},extra={'height_ft':50,'profile':{'rain_family':'veil','allies':list(zone.trigger_profile['profile']['allies'])}},numbers=numbers)
        return
    from ..relations import relation,ENEMY
    from ..target_knowledge import located
    targets=[a for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine,ctx.actor,a)==ENEMY
             and te.in_area(ctx.engine,point,point,a.position,area) and (mode=='lightning' or located(ctx.engine,ctx.actor,a))]
    if mode=='flood':
        picked=ask(ctx,'flood_targets',[a.entity_id for a in targets],labels={a.entity_id:a.display_name for a in targets},minimum=0,maximum=len(targets),allow_decline=True,
            preferred=[a.entity_id for a in targets],default='all',prompt='Driving Flood: choose hostile creatures in the 20-foot-radius area.') if targets else []
        targets=[a for a in targets if a.entity_id in picked]
    sub=replace(ctx,targets=targets,target=None,typed={**ctx.typed,'area':area,'_area_centre':(point.x,point.y)})
    if mode=='lightning':
        te.run_effects(sub,[{'type':'save','ability':'dex','dc':'technique_save_dc','on_fail':[{'type':'damage','applies_to':'target','dice':{'count':5,'sides':8},'damage_types':['lightning']},
            {'type':'reaction_denied','applies_to':'target','duration':'until_start_of_next_turn'}],'on_success':[{'type':'half_damage'}]}])
    else:
        direction=(ask(ctx,'flood_direction',['away_center','toward_center'],labels={'away_center':'Push away from chosen point','toward_center':'Pull toward chosen point'},prompt='Driving Flood: push or pull the chosen hostile creatures?') or ['away_center'])[0]
        te.run_effects(sub,[{'type':'save','ability':'str','dc':'technique_save_dc','on_fail':[{'type':'forced_movement','applies_to':'target','distance_ft':15,'direction':direction},
            {'type':'condition','applies_to':'target','condition':'prone'}],'on_success':[{'type':'forced_movement','applies_to':'target','distance_ft':5,'direction':direction}]}])


def purify(ctx):
    """The decree selects a procedure; disease alone limits removal to one episode.

    The patient chooses private episode details using their own controller. The
    caster never receives a menu of private diagnoses, causes or Source CLs.
    """
    from .end_effect import source_action
    from .repeat_saves import save_of
    from .condition_ownership import remove_instance
    from .journey_effects import end_combat_effect
    groups={key:[] for key in ('poison','airborne','disease','repeat')}
    for iid,c in ctx.target.conditions.items():
        name=c.condition_id.removeprefix('condition:typed.')
        from ..observer_information import source_profile
        profile=source_profile(ctx.engine,c.source_definition_id,c.data)
        tags=set(profile.get('tags') or c.data.get('categories') or [])
        if not counterprocedure_allowed(ctx.engine,c.source_definition_id,profile,SOVEREIGN):continue
        action=source_action(ctx,c)
        level=profile.get('source_cl')
        if level is None:level=(action.parameters.get('typed',{}).get('numbers',{}).get('cl') if action else None)
        from .area_suppression import effect_mundane
        ordinary=profile.get('mundane')==1 or c.data.get('mundane') is True or effect_mundane(ctx.engine,c.source_definition_id,c.source_actor_id) is True
        disease=name in ('disease','diseased') or 'disease' in tags
        poison=name=='poisoned'
        airborne=name=='blinded' and 'injury' not in tags and bool(tags&{'dust','smoke','ash','airborne_irritant'})
        if disease and ordinary:groups['disease'].append((iid,c))
        if level is not None and level<=int(ctx.numbers['cl']):
            if poison:groups['poison'].append((iid,c))
            if airborne:groups['airborne'].append((iid,c))
        elif level is not None and level>int(ctx.numbers['cl']) and (poison or airborne or disease) and save_of(c):
            groups['repeat'].append((iid,c))
    labels={'poison':'End Poisoned from sources at or below your Cultivation Level','airborne':'End airborne-irritant Blindness from sources at or below your Cultivation Level',
            'disease':'End one ordinary disease','repeat':'Repeat one poison, disease or airborne-condition save from a higher Cultivation Level with Advantage'}
    selected=ask(ctx,'purify',labels,labels=labels,prompt='Purification: choose a cleansing procedure for '+ctx.target.display_name+'. Injury-based Blindness is excluded.')
    if not selected:return
    mode=selected[0];rows=groups[mode]
    if mode in ('disease','repeat') and rows:
        # An episode can impose several states. Present it once, then remove
        # all states belonging to precisely the selected disease episode.
        episodes={}
        for iid,c in rows:episodes.setdefault(c.data.get('journey_effect_id',iid),(iid,c))
        patient=replace(ctx,actor=ctx.target)
        picked=ask(patient,'purify_episode',episodes,
                   labels={key:(c.data.get('private_label') or c.data.get('label') or c.condition_id.removeprefix('condition:typed.')) for key,(iid,c) in episodes.items()},
                   prompt='Purification: choose your affected episode.',allow_decline=True)
        rows=[episodes[picked[0]]] if picked else []
    if mode=='repeat' and rows:
        iid,c=rows[0];save=save_of(c)
        from .adaptations import ending_save_scope
        with ending_save_scope(ctx.engine,ctx.target,c):
            rolled=ctx.engine._roll_save(ctx.target,str(save['ability']).upper(),int(save['dc']),ctx.source,'ADVANTAGE',
                                        roll_context={'source_actor_id':c.source_actor_id,'named':[c.condition_id.removeprefix('condition:typed.')]})
        if rolled is None or rolled.total<int(save['dc']):return
        from .journey_effects import resolve_combat_save_success
        resolve_combat_save_success(ctx.engine,ctx.target,c,ctx.source)
        return
    for iid,c in rows:
        if mode=='disease' and c.data.get('journey_effect_id'):
            end_combat_effect(ctx.engine,ctx.target,c.data['journey_effect_id'],ctx.source)
        elif iid in ctx.target.conditions:remove_instance(ctx.engine,ctx.target,iid,ctx.source)

# Elapsed-time source producer. World facts establish unknown civil/environment
# facts; all water, suppression, agricultural and wildfire results are derived
# from the accepted activations and committed native clock below.
SITE_KINDS={'ordinary_fire','supernatural_fire','smoke','dust','ash','pollen','pollution','plant','soil','pond','cistern','irritant','heat','lava','drought','minor_pests'}


def journey_state(session,aid):
    return session.state['actors'][aid].get('source_states',{}).get(BASE)


@hook('fact_admission_schema')
def site_schema(session,source,subject,kind):
    if source!=CALL or kind not in ('rain_site','rain_environment_event') or not journey_owns(session,subject,CALL):return None
    return {'value_type':'document','maximum_seconds':604800,'authority':'table_owner',
            'description':'Raincaller site: actual open space, ordinary flames, air, water stores, plants and terrain. The table owner supplies unknown world facts; rain results follow native time.'}


def validate_site(session,value):
    from ..journey import require,integer
    from ..gate2_runtime_models import Position
    require(set(value)=={'plane','center','open_space','sealed','features','containers','clear_zones','allies'},'Supply a complete Raincaller site.')
    require(type(value['plane']) is str and bool(value['plane']) and value['open_space'] in (0,1) and value['sealed'] in (0,1),'Use a named plane and explicit open-space/sealed flags.')
    center=Position.model_validate(value['center']);require(session.grid.in_bounds((center.x,center.y)),'The site center must be on this map.')
    require(isinstance(value['features'],list) and isinstance(value['containers'],list) and isinstance(value['clear_zones'],list),'Supply bounded site lists.')
    require(isinstance(value['allies'],list) and all(type(a) is str for a in value['allies']) and len(value['allies'])==len(set(value['allies'])) and set(value['allies'])<=set(session.state['actors']),'The table owner must identify actual allies in this scene.')
    ids=[]
    for f in value['features']:
        required={'id','name','kind','position','source_cl','save_dc','ordinary','attended','amount','alive','viable','permanent','useful','save_bonus'}
        require(required<=set(f)<=required|{'authority_grade','counterprocedures','authority_basis','fire_kind','source_duration'},'Use the complete typed environmental feature profile.')
        require(type(f['id']) is str and bool(f['id']) and type(f['name']) is str and bool(f['name'].strip()) and type(f['kind']) is str and f['kind'] in SITE_KINDS,'Use a known environmental kind and identity.')
        require(all(integer(f[k]) for k in ('source_cl','save_dc','amount')) and all(type(f[k]) is int and f[k] in (0,1) for k in ('ordinary','attended','alive','viable','permanent','useful')),'Environmental amounts and authority must be bounded whole numbers.')
        require(type(f['save_bonus']) is int and -100<=f['save_bonus']<=100,'Supply the source’s ordinary save bonus.')
        require(f['ordinary']==1 or f['source_cl']>=1 and f['save_dc']>=1,'A supernatural source needs its actual Source CL and save DC.')
        require(f.get('authority_grade','ordinary' if f['ordinary']==1 else '') in ('ordinary','artifact','secret','immortal','absolute'),'A supernatural environmental source needs its actual authority grade.')
        from .journey_effects import validate_counterprocedures
        validate_counterprocedures(f)
        if f['kind'] in ('ordinary_fire','supernatural_fire'):
            require(f.get('fire_kind') in ('flame','wildfire'),'Record ordinary flame versus actual wildfire explicitly.')
        if f['kind'] in ('ordinary_fire','supernatural_fire') or f['ordinary']==0 and f['kind'] in ('smoke','dust','ash','pollen','pollution'):
            require(f.get('source_duration') in ('instant','persistent'),'Record whether this is an instantaneous source or a persistent area.')
        Position.model_validate(f['position']);ids.append(f['id'])
    for c in value['containers']:
        require(set(c)=={'id','name','kind','position','capacity','water','open'} and type(c['id']) is str and bool(c['id']) and type(c['name']) is str and bool(c['name'].strip()) and type(c['kind']) is str and c['kind'] in ('container','cistern','pond','irrigation') and type(c['open']) is int and c['open'] in (0,1) and integer(c['capacity'],1) and integer(c['water']) and c['water']<=c['capacity'],'Supply actual collection containers and capacities in waterskins.')
        Position.model_validate(c['position']);ids.append(c['id'])
    require(len(ids)==len(set(ids)),'Site identities must be distinct.')
    for z in value['clear_zones']:
        require(set(z)=={'kind','center','radius_ft'} and z['kind'] in ('road','building','agricultural_zone') and integer(z['radius_ft'],1),'Only designated roads, buildings and agricultural zones may remain clear.')
        Position.model_validate(z['center'])
    return deepcopy(value)


def distance_ft(session,a,b):
    from ..gate2_runtime_models import Position
    return session.grid.distance_ft(Position.model_validate(a),Position.model_validate(b))


def civil_reaches(session,rain,position):
    from math import hypot
    a=rain['center'];dx=(position['x']-a['x'])*5;dy=(position['y']-a['y'])*5
    dz=(position.get('z',0)-a.get('z',0))*5
    if hasattr(session,'engine'):
        zone=session.engine.state.zones.get(rain.get('native_zone',''))
        if zone is not None:
            from ..gate2_runtime_models import Position
            return point_inside(session.engine,zone,Position.model_validate(position))
    if rain['kind']=='wall':
        return [position['x'],position['y']] in rain['wall_cells'] and 0<=dz<10
    if rain['kind'] in ('call','sovereign'):
        return hypot(dx,dy)<=rain['radius_ft'] and 0<=dz<(50 if rain['kind']=='sovereign' else 20)
    return hypot(dx,dy,dz)<=rain['radius_ft']


@hook('journey_options')
def rain_journey_options(session,aid):
    if session.state['phase']!='travel':return None
    if not journey_owns(session,aid,CALL):return journey_water_choices(session,aid)
    actor=session.state['actors'][aid];state=journey_state(session,aid)
    if actor['incapacitated']:return []
    options=[{'id':'rain_site','kind':'rain_site','payload':{'scope':'site'},'auto_select':0,
              'label':'Raincaller: collect a site profile already supplied by the table owner.'}]
    if not state:return options
    if state.get('selection'):return rain_selection_options(session,aid,state['selection'])
    surveyed=state['site_expiry']>session.clock()
    if surveyed and actor['resources'].get('resource:core.qi',0)>=1:
        for form in FORMS if journey_owns(session,aid,SHAPE) else ['']:
            options.append({'id':'rain_call'+(':'+form if form else ''),'kind':'rain_call',
                'payload':{**({'form':form} if form else {}),'allies':[aid]},'auto_select':0,
                'label':'Call Rain'+(': '+FORM_LABELS[form] if form else '')+' Action and 1 Qi; 20-foot-radius, 20-foot-high rain within 60 feet for one minute with Concentration.'})
    for key,source,cost in (('wall',WALL,4),('sovereign',SOVEREIGN,8)):
        if not surveyed:continue
        if not journey_owns(session,aid,source) or actor['resources'].get('resource:core.qi',0)<cost:continue
        if key=='sovereign' and actor['travel_uses'].get(SOVEREIGN):continue
        options.append({'id':'rain_'+key,'kind':'rain_'+key,'payload':{'allies':[aid]},'auto_select':0,
            'label':RAIN_NAMES[key]+f': Action and {cost} Qi; '+('wall up to 30 feet long, 10 feet high and 5 feet thick within 60 feet' if key=='wall' else '50-foot-radius, 50-foot-high field within 120 feet; once per scene')+'; one minute with Concentration.'})
    if (surveyed and journey_owns(session,aid,RITE) and actor['resources'].get('resource:core.qi',0)>=5
            and state['site']['open_space']==1 and state['site']['sealed']==0
            and distance_ft(session,actor['position'],state['site']['center'])==0):
        from itertools import combinations
        for count in range(3):
            for effects in combinations(PROVINCES,count):
                options.append({'id':'rain_rite:'+(','.join(effects) or 'none'),'kind':'rain_rite',
                    'payload':{'effects':list(effects),'clear_zones':[]},'auto_select':0,
                    'label':'Provincial Rain Rite: '+(' '.join(PROVINCE_LABELS[e] for e in effects) or 'no effects')+'; 10 minutes and 5 Qi, one-mile radius for 8 hours. Replaces your prior Rite.'})
    # Keep quick defaults and expose the same complete staged configuration to
    # human and automatic seats. Draft steps never spend time or resources.
    options.extend({'id':o['id']+':configure','kind':'rain_prepare',
        'payload':{'kind':o['kind'],'parameters':deepcopy(o['payload'])},'auto_select':0,
        'label':'Choose placement and recipients for '+o['label']}
        for o in list(options) if o['kind'] in ('rain_call','rain_wall','rain_sovereign','rain_rite'))
    active=state['rains'].get('call')
    if active and journey_owns(session,aid,SHAPE) and active.get('form_slot',-1)<(int(session.clock())-active['created_at'])//6:
        options.extend({'id':'rain_form:'+form,'kind':'rain_form','payload':{'form':form},'auto_select':0,
            'label':'Shape the Rain: '+FORM_LABELS[form]+' Switch at this turn’s start; no action or Qi. Original rain duration continues.'} for form,name in FORMS.items())
    for plant in state['site']['features']:
        if plant['kind']!='plant' or not plant['alive']:continue
        for hazard in state['site']['features']:
            if hazard['kind'] in ('heat','drought','minor_pests') and hazard['save_dc']>=1:
                options.append({'id':'rain_crop_save:'+plant['id']+':'+hazard['id'],'kind':'rain_crop_save','payload':{'plant':plant['id'],'hazard':hazard['id']},'auto_select':0,
                    'label':'Agricultural Blessing: resolve '+plant['name']+' against '+hazard['name']+' using its normal save, with Advantage only while a matching ordinary blessing applies.'})
    options.extend(journey_water_choices(session,aid))
    options.extend({'id':'rain_end:'+key,'kind':'rain_end','payload':{'kind':key},'auto_select':0,
        'label':'End your '+RAIN_NAMES[rain['kind']]+' now; no Qi or extra time.'} for key,rain in state['rains'].items())
    return options


def rain_selection_options(session,aid,draft):
    """Lazy travel choices: every finite layout/subset remains reachable.

    The admitted site and travel party are the chooser's available knowledge;
    this reads no encounter roster, hidden fact or model service. Each step is
    an ordinary menu option for both manual and explicitly selected AI seats.
    """
    from ..gate2_runtime_models import Position
    state=journey_state(session,aid);site=state['site'];p=draft['parameters']
    kind=draft['kind'];center=p['center'];z=center.get('z',0)
    label=RAIN_NAMES[kind.removeprefix('rain_')]
    result=[]
    def option(identity,step,value,text):
        result.append({'id':'rain_select:'+identity,'kind':'rain_select',
            'payload':{'step':step,'value':value},'auto_select':0,'label':label+': '+text})
    def legal(point):
        return (kind=='rain_rite' or distance_ft(session,session.state['actors'][aid]['position'],point)
                <=(120 if kind=='rain_sovereign' else 60)) and not session.grid.terrain_at(Position.model_validate(point),'BLOCKED')
    if kind=='rain_rite':
        # A regional site is a table-owner fact, not a freely movable origin.
        # Keep its sole legal point selectable, including omitted ground z.
        at=Position.model_validate(site['center'])
        point={'x':at.x,'y':at.y,'z':at.z}
        option(f"center:{point['x']},{point['y']},{point['z']}",'center',point,
            f"use the recorded ritual site at ({point['x']}, {point['y']}), {point['z']*5} feet high; choose clear zones and confirm next.")
    else:
        for x in range(session.grid.width):
            for y in range(session.grid.height):
                point={'x':x,'y':y,'z':z}
                if legal(point):option(f'center:{x},{y},{z}','center',point,f'place origin at ({x}, {y}), {z*5} feet high; choose allies and confirm next.')
    for height in () if kind=='rain_rite' else (z-1,z+1):
        if height<0:continue
        # Height is navigated independently of horizontal origin so a source
        # at an elevated position can reach every legal altitude slice.
        actor_z=session.state['actors'][aid]['position'].get('z',0)
        if kind!='rain_rite' and abs(height-actor_z)*5>(120 if kind=='rain_sovereign' else 60):continue
        option('height:'+str(height),'height',height,f'browse origins {height*5} feet high; no time or Qi spent.')
    if kind!='rain_rite':
        for ally in site['allies']:
            name=session.state['actors'][ally]['name']
            chosen=ally in p.get('allies',[])
            option('ally:'+ally,'ally',ally,('stop designating ' if chosen else 'designate ')+name+' for allied rain benefits inside the area.')
    else:
        for index,zone in enumerate(site['clear_zones']):
            chosen=zone in p.get('clear_zones',[])
            at=zone['center']
            option('clear:'+str(index),'clear',index,('include in mist: ' if chosen else 'keep clear of Veiling Mist: ')+zone['kind'].replace('_',' ')+f" at ({at['x']}, {at['y']}), {zone['radius_ft']}-foot radius.")
    if kind=='rain_wall':
        cells=p['wall_cells'];x,y=cells[-1]
        if len(cells)<6:
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    cell=[x+dx,y+dy];point={'x':cell[0],'y':cell[1],'z':z}
                    if (dx or dy) and cell not in cells and session.grid.in_bounds(tuple(cell)) and legal(point):
                        option(f'wall:{cell[0]},{cell[1]}','wall',cell,f'add a five-foot wall section at ({cell[0]}, {cell[1]}); total {(len(cells)+1)*5} feet, up to 30 feet.')
        if len(cells)>1:option('undo','undo',0,'remove the last five-foot wall section.')
    cost={'rain_call':1,'rain_wall':4,'rain_sovereign':8,'rain_rite':5}[kind]
    names=', '.join(session.state['actors'][a]['name'] for a in p.get('allies',[])) or 'none'
    details=(f"{len(p['wall_cells'])*5}-foot wall; " if kind=='rain_wall' else '')
    details+=(f"{len(p.get('clear_zones',[]))} recorded zones clear of mist; " if kind=='rain_rite' else 'designated allies: '+names+'; ')
    option('confirm','confirm',0,f"confirm origin ({center['x']}, {center['y']}), {z*5} feet high; "+details+f'{"10 minutes" if kind=="rain_rite" else "Action"} and {cost} Qi, {"8 hours" if kind=="rain_rite" else "one minute with Concentration"}.')
    option('cancel','cancel',0,'cancel configuration; no time or Qi spent; return to all travel options.')
    return result


def rain_selection_command(session,aid,kind,payload):
    from ..journey import require
    require(journey_owns(session,aid,CALL) and not session.state['actors'][aid]['incapacitated'],'An able Raincaller must choose this rain.')
    state=journey_state(session,aid)
    require(state is not None,'Collect a current site first.')
    if kind=='rain_prepare':
        require(any(o['kind']=='rain_prepare' and o['payload']==payload for o in rain_journey_options(session,aid)),
                'Choose a currently offered rain configuration.')
        draft=deepcopy(payload);p=draft['parameters'];p['center']=deepcopy(state['site']['center'])
        if draft['kind']!='rain_rite' and distance_ft(session,session.state['actors'][aid]['position'],p['center'])>(120 if draft['kind']=='rain_sovereign' else 60):
            p['center']=deepcopy(session.state['actors'][aid]['position'])
        if draft['kind']=='rain_wall':p['wall_cells']=[[p['center']['x'],p['center']['y']]]
        state['selection']=draft
    else:
        draft=state.get('selection')
        require(draft is not None and any(o['payload']==payload for o in rain_selection_options(session,aid,draft)),
                'Choose a currently offered rain placement or designation.')
        p=draft['parameters'];step=payload['step'];value=payload['value']
        if step in ('cancel','confirm'):
            del state['selection']
            if step=='confirm':rain_journey_command(session,aid,draft['kind'],deepcopy(p))
        elif step=='center':
            p['center']=deepcopy(value)
            if draft['kind']=='rain_wall':p['wall_cells']=[[value['x'],value['y']]]
        elif step=='height':p['center']['z']=value
        elif step=='wall':p['wall_cells'].append(list(value))
        elif step=='undo':p['wall_cells'].pop()
        else:
            key='allies' if step=='ally' else 'clear_zones'
            choice=value if step=='ally' else state['site']['clear_zones'][value]
            selected=p.setdefault(key,[])
            if choice in selected:selected.remove(choice)
            else:selected.append(deepcopy(choice))
    session.emit('RAIN_SELECTION_CHANGED',aid,step=kind if kind=='rain_prepare' else payload['step'])
    return True


@hook('journey_command')
def rain_journey_command(session,aid,kind,payload):
    if kind in ('rain_prepare','rain_select'):
        return rain_selection_command(session,aid,kind,payload)
    if kind not in ('rain_site','rain_call','rain_wall','rain_sovereign','rain_rite','rain_collect','rain_form','rain_crop_save','rain_end'):return None
    from ..journey import require
    if kind=='rain_collect':
        require(not session.state['actors'][aid]['incapacitated'],'An incapacitated creature cannot collect water.')
        return journey_collect_water(session,aid,payload)
    require(journey_owns(session,aid,CALL),'This creature has not acquired Call Rain.')
    actor=session.state['actors'][aid]
    require(not actor['incapacitated'],'An incapacitated creature cannot cultivate rain.')
    if kind=='rain_site':
        from ..fact_consent_admission import read
        require(set(payload)=={'scope'},'Choose the source-scoped site declaration.')
        declaration=read(session,CALL,aid,'rain_site',payload['scope'],aid)
        require(declaration is not None,'The table owner must first supply this Raincaller site.')
        site=validate_site(session,declaration['value'])
        state=actor.setdefault('source_states',{}).setdefault(BASE,{'rains':{},'blessings':[]})
        # A declaration can be collected once; recollection cannot rewind water,
        # restored flames or other mechanical work already committed here.
        require(state.get('site_receipt')!=declaration['receipt_id'],'This site input was already collected.')
        require(not state.get('rains'),'End the current rain before replacing this site profile.')
        state.update(site=site,site_receipt=declaration['receipt_id'],site_expiry=declaration['expires_at'])
        session.emit('RAIN_SITE_COLLECTED',aid,source=CALL,receipt=declaration['receipt_id'])
        return True
    state=journey_state(session,aid)
    if kind=='rain_end':
        require(state is not None,'Choose one of your active rain areas.')
        require(set(payload)=={'kind'} and type(payload['kind']) is str and payload['kind'] in state['rains'],'Choose one of your active rain areas.')
        rain=state['rains'].pop(payload['kind']);release_site_claim(state,rain)
        session.emit('RAIN_ENDED',aid,source=rain['source'],reason='CREATOR_ENDED')
        return True
    require(state is not None,'Collect a current site profile first.')
    if kind=='rain_crop_save':
        require(state['site_expiry']>session.clock(),'Collect a current site profile first.')
        require(set(payload)=={'plant','hazard'},'Choose a recorded useful plant and hazard source.')
        plant=next((f for f in state['site']['features'] if f['id']==payload['plant'] and f['kind']=='plant'),None)
        hazard=next((f for f in state['site']['features'] if f['id']==payload['hazard'] and f['kind'] in ('heat','drought','minor_pests')),None)
        require(plant is not None and plant['alive'] and hazard is not None and hazard['save_dc']>=1,'Use actual living plants and a sourced ordinary saving throw.')
        protected=hazard['ordinary']==1 and any(b['feature']==plant['id'] and b['expires_at']>session.clock() for b in state['blessings'])
        from ..gate2_rolls import DeterministicRollAuthority
        roller=DeterministicRollAuthority(session.state['journey_id']+':crop:'+str(len(session.state['events'])))
        roll=roller.d20(modifier=plant['save_bonus'],actor_id=plant['id'],reason='AGRICULTURAL_BLESSING_SAVE',mode='ADVANTAGE' if protected else 'NORMAL')
        session.emit('RAIN_CROP_SAVE',aid,source=RITE,plant=plant['id'],hazard=hazard['id'],roll=roll.model_dump(mode='json'),dc=hazard['save_dc'],success=int(roll.total>=hazard['save_dc']))
        return True
    if kind=='rain_form':
        require(journey_owns(session,aid,SHAPE) and set(payload)=={'form'} and type(payload['form']) is str and payload['form'] in FORMS and state['rains'].get('call'),'Choose a known form for your active Call Rain.')
        rain=state['rains']['call'];slot=(int(session.clock())-rain['created_at'])//6
        require(rain.get('form_slot',-1)<slot,'Switch your Rain Form once at the start of a six-second turn.')
        rain['form_slot']=slot;rain['form']=payload['form']
        session.emit('RAIN_FORM_CHANGED',aid,source=SHAPE,form=payload['form']);return True
    if kind=='rain_rite':
        session.command(aid,'activity_start',{'source':RITE,'parameters':payload})
        return True
    require(state['site_expiry']>session.clock(),'Collect a current site profile first.')
    site=state['site']
    require(site['open_space']==1 and site['sealed']==0,'Cultivated rain requires sufficient open space; it cannot override a sealed environment.')
    center=payload.get('center',site['center'])
    key=kind.removeprefix('rain_');source=RAIN_SOURCES[key]
    require(journey_owns(session,aid,source),'This rain ability has not been acquired.')
    require(distance_ft(session,actor['position'],center)<=(120 if key=='sovereign' else 60),'Choose a rain origin within the ability’s range.')
    require(set(payload)<={'center','form','allies','wall_cells'} and type(payload.get('form','mist')) is str and payload.get('form','mist') in FORMS,'Choose one Rain Form, a point and designated allies.')
    require(key=='call' or 'form' not in payload,'Only Call Rain has a Rain Form.')
    require(key=='wall' or 'wall_cells' not in payload,'Only Monsoon Wall uses a wall layout.')
    require(key!='sovereign' or not actor['travel_uses'].get(SOVEREIGN),'Monsoon Sovereign is limited to once per scene.')
    if key=='wall':
        from ..gate2_runtime_models import Position
        cells=payload.get('wall_cells',[[center['x'],center['y']]])
        require(isinstance(cells,list) and 1<=len(cells)<=6 and all(isinstance(c,list) and len(c)==2 and all(type(n) is int for n in c) for c in cells),'Choose up to six connected five-foot wall sections.')
        require(len({tuple(c) for c in cells})==len(cells) and cells[0]==[center['x'],center['y']],'Start the wall at its origin without duplicate sections.')
        require(all(max(abs(a[0]-b[0]),abs(a[1]-b[1]))==1 for a,b in zip(cells,cells[1:])),'Wall sections must form a connected straight or gently curved wall.')
        require(all(session.grid.in_bounds(tuple(c)) and not session.grid.terrain_at(Position(x=c[0],y=c[1],z=center.get('z',0)),'BLOCKED') and distance_ft(session,actor['position'],{'x':c[0],'y':c[1],'z':center.get('z',0)})<=60 for c in cells),'Place the wall in open cells within 60 feet.')
        payload={**payload,'wall_cells':cells}
    require(journey_owns(session,aid,SHAPE) or 'form' not in payload,'Shape the Rain has not been acquired.')
    require(isinstance(payload.get('allies',[aid]),list) and all(type(a) is str for a in payload.get('allies',[aid])) and set(payload.get('allies',[aid]))<=set(site['allies']),'Choose actual allies recorded for this site.')
    session.spend_resource(aid,'resource:core.qi',{'call':1,'wall':4,'sovereign':8}[key],source)
    session.tick(6)
    begin_civil_rain(session,aid,key,payload)
    if key=='sovereign':actor['travel_uses'][SOVEREIGN]=1
    return True


def begin_civil_rain(session,aid,key,payload):
    from ..journey import require
    actor=session.state['actors'][aid];state=journey_state(session,aid)
    source=RAIN_SOURCES[key]
    now=int(session.clock());duration=28800 if key=='rite' else 60
    numbers=next((r['numbers'] for r in actor['bundle']['typed_passives'] if r.get('block')=='raincaller_acquired' and r.get('feature_id')==source),None)
    require(numbers is not None,'The acquired source must carry its native compiled cultivation numbers.')
    rain={'kind':key,'center':deepcopy(payload.get('center',state['site']['center'])),'created_at':now,'expires_at':now+duration,
          'radius_ft':{'rite':5280,'sovereign':50,'wall':30,'call':20}[key],'effects':list(payload.get('effects',[])),
          'form':payload.get('form',''),'allies':list(payload.get('allies',[aid])),'clear_zones':deepcopy(payload.get('clear_zones',[])),
          'numbers':deepcopy(numbers),'contests':{},'last_second':now,'source':source,'concentration':int(key!='rite')}
    rain['claim_id']=session.state['journey_id']+':'+aid+':'+source+':'+str(len(session.state['events']))
    if key=='wall':rain['wall_cells']=deepcopy(payload['wall_cells'])
    slot='wall:'+str(now) if key=='wall' else key
    if slot in state['rains']:release_site_claim(state,state['rains'][slot])
    state['rains'][slot]=rain
    session.emit('RAIN_ACTIVATED',aid,source=source,effects=rain['effects'],center=rain['center'],
                 qi_paid={'rite':5,'call':1,'wall':4,'sovereign':8}[key],expires_at=now+duration,ritual_seconds=600 if key=='rite' else 6)
    apply_civil_rain(session,aid,rain,now,now)


@hook('activity_spec')
def provincial_activity(session,aid,source,parameters):
    if source!=RITE:return None
    from ..journey import require
    require(journey_owns(session,aid,RITE),'Provincial Rain Rite has not been acquired.')
    require(session.state['actors'][aid]['resources'].get('resource:core.qi',0)>=5,'Provincial Rain Rite costs 5 Qi.')
    validate_provincial_activity(session,aid,parameters)
    return {'seconds':600,'label':'Provincial Rain Rite: choose up to two civil weather effects, then maintain one eight-hour Rite'}


def validate_provincial_activity(session,aid,parameters):
    from ..journey import require
    from ..gate2_runtime_models import Position
    state=journey_state(session,aid)
    require(state is not None and state['site_expiry']>session.clock(),'Collect a current site before the ten-minute Rite.')
    require(state['site']['open_space']==1 and state['site']['sealed']==0,'Cultivated rain requires sufficient open space; it cannot override a sealed environment.')
    require(set(parameters)<={'effects','clear_zones','center'} and isinstance(parameters.get('effects'),list)
            and len(parameters['effects'])<=2 and all(type(e) is str for e in parameters['effects']) and len(set(parameters['effects']))==len(parameters['effects']) and set(parameters['effects'])<=set(PROVINCES),'Choose up to two distinct Provincial Effects.')
    require(isinstance(parameters.get('clear_zones',[]),list) and all(z in state['site']['clear_zones'] for z in parameters.get('clear_zones',[])),'Only recorded roads, buildings and agricultural zones may remain clear.')
    site_center=Position.model_validate(state['site']['center'])
    require(Position.model_validate(session.state['actors'][aid]['position'])==site_center,'Perform the Rite at its actual recorded ritual site.')
    require(Position.model_validate(parameters.get('center',state['site']['center']))==site_center,'The Rite must use its actual recorded regional site on this plane.')


@hook('activity_started')
def provincial_pay(session,aid,row):
    if row['source']==RITE:session.spend_resource(aid,'resource:core.qi',5,RITE)


@hook('activity_validate')
def provincial_still_valid(session,aid,row):
    if row['source']==RITE:validate_provincial_activity(session,aid,row['parameters'])


@hook('activity_finished')
def provincial_complete(session,aid,row):
    if row['source']==RITE:begin_civil_rain(session,aid,'rite',row['parameters'])


@hook('activity_command_interrupts')
def provincial_interrupted_by_action(session,who,row,aid,kind,payload):
    if row['source']==RITE and who==aid and kind in ('rain_call','rain_collect','rain_wall','rain_sovereign'):
        return True
    return None


def apply_civil_rain(session,aid,rain,before,now):
    state=journey_state(session,aid);site=state['site'];effects=rain['effects'];kind=rain['kind']
    source=rain['source'];cl=int(rain['numbers']['cl'])
    for f in site['features']:
        if not civil_reaches(session,rain,f['position']):continue
        ordinary=f['ordinary']==1;k=f['kind']
        if k in ('ordinary_fire','supernatural_fire','smoke','dust','ash','pollen','pollution','irritant') and not counterprocedure_allowed(getattr(session,'engine',None),f['id'],f,source):continue
        if ordinary and k=='ordinary_fire' and (kind in ('call','wall') and not f['attended'] or kind=='sovereign' or 'firebreak' in effects and f.get('fire_kind')=='wildfire'):
            loss=f['amount'] if kind in ('call','wall','sovereign') else max(0,(now-rain['created_at'])//60-(before-rain['created_at'])//60)
            f['amount']=max(0,f['amount']-loss);mark_site_feature(f,'spread_blocked_until',rain)
        if k in ('smoke','dust','ash','pollen','pollution') and ordinary and (kind=='call' and k!='pollution' or 'clearing' in effects and now-rain['created_at']>=600):mark_site_feature(f,'suppressed_until',rain)
        if k in ('smoke','dust','ash','pollen','pollution') and ordinary and 'clearing' in effects and now-rain['created_at']>=600:f['amount']=0
        contest=(k=='supernatural_fire' and (kind=='wall' or 'firebreak' in effects and f.get('fire_kind')=='wildfire') or k in ('smoke','dust','ash','pollen','pollution') and 'clearing' in effects) and not ordinary and f.get('source_duration')=='persistent'
        if contest and f['id'] not in rain['contests']:
            # Outside-combat uses a deterministic native journaled roller with
            # the scene/source sequence as seed, not a client-submitted outcome.
            from ..gate2_rolls import DeterministicRollAuthority
            if f['source_cl']<cl:success=True
            else:
                if hasattr(session,'engine'):
                    from .ability_source import cultivation_check
                    success=cultivation_check(session.engine,session.engine.state.actors[aid],rain['numbers'],f['save_dc'],session.source,'Raincaller Cultivation Check')
                else:
                    roller=DeterministicRollAuthority(session.state['journey_id']+':rain:'+str(len(session.state['events']))+':'+f['id'])
                    roll=roller.d20(modifier=int(rain['numbers']['pb'])+int(rain['numbers']['key_mod']),actor_id=aid,reason='RAIN_CULTIVATION_CHECK')
                    success=roll.total>=f['save_dc'];session.emit('RAIN_CULTIVATION_CHECK',aid,source=source,feature=f['id'],roll=roll.model_dump(mode='json'),dc=f['save_dc'],success=int(success))
            rain['contests'][f['id']]=int(success)
        if contest and rain['contests'][f['id']]:mark_site_feature(f,'suppressed_until',rain)
        if k=='irritant' and ordinary and kind=='call':f['amount']=0
        if k=='heat' and ordinary and 'cooling' in effects:mark_site_feature(f,'tolerable_until',rain)
        if 'drought' in effects and (k=='soil' or k=='plant' and f['alive']):f['normal_moisture_days']=max(1,f.get('normal_moisture_days',0))
        if k in ('plant','soil','pond','cistern') and 'steady' in effects:
            # Store integer depth numerator/denominator, avoiding cumulative
            # rounding and ensuring 1 inch only after the full eight hours.
            f['rain_inches_num']=min(28800,now-rain['created_at']);f['rain_inches_den']=28800
        if k=='plant' and 'agriculture' in effects and f['alive'] and f['useful']:
            if not any(b['feature']==f['id'] and b['created_at']==rain['created_at'] for b in state['blessings']):
                state['blessings']=[b for b in state['blessings'] if b['feature']!=f['id']]
                state['blessings'].append({'feature':f['id'],'created_at':rain['created_at'],'expires_at':rain['created_at']+604800,'advantage':['ordinary_drought','ordinary_heat','minor_pests'],'yield_improved':int(bool(f['viable']))})
    if 'steady' in effects:
        for c in site['containers']:
            if c['open'] and c['kind'] in ('cistern','pond','irrigation') and civil_reaches(session,rain,c['position']):
                # Native cisterns retain the captured increment separately from
                # existing water; a replacement never empties a real store.
                collected=rain.setdefault('steady_collected',{})
                total=min(c['capacity'],c['capacity']*max(0,now-rain['created_at'])//28800)
                add=max(0,total-collected.get(c['id'],0))
                c['water']=min(c['capacity'],c['water']+add);collected[c['id']]=total
    if kind!='rite' or effects:state['wet_until']=max(state.get('wet_until',0),rain['expires_at'])
    rain['last_second']=now
    session.emit('RAIN_CIVIL_SETTLED',aid,source=source,from_second=before,to_second=now,
                 text='Cultivated rainfall settles ordinary fire, air, water and agriculture only within its recorded area and printed limits.')


@hook('journey_elapsed')
def civil_elapsed(session,aid,previous,seconds,moving):
    state=journey_state(session,aid)
    if not state:return
    end=int(session.clock())
    state['clock_journey']=session.state['journey_id'];state['clock_second']=end
    for key,rain in list(state.get('rains',{}).items()):
        before=max(rain['created_at'],int(previous));now=min(end,rain['expires_at'])
        if now>=before:
            apply_civil_rain(session,aid,rain,before,now)
            civil_restorative(session,aid,rain,before,now)
        if end>=rain['expires_at']:
            release_site_claim(state,rain)
            del state['rains'][key];session.emit('RAIN_ENDED',aid,source=rain['source'],at_second=rain['expires_at'])
    state['blessings']=[b for b in state['blessings'] if b['expires_at']>end]


@hook('journey_properties')
def civil_properties(session,aid):
    state=journey_state(session,aid)
    if not state:return None
    now=int(session.clock());rains=state['rains']
    return {'raincaller':{'wet':int(state.get('wet_until',0)>now),'rains':deepcopy(rains),'blessings':deepcopy(state['blessings']),
                         'features':deepcopy(state['site']['features']),'containers':deepcopy(state['site']['containers'])}}


@hook('journey_scene_end')
def rain_scene_end(session,previous,current):
    # Scene transitions do not recover Qi or erase an eight-hour regional Rite.
    for actor in session.state['actors'].values():
        actor.get('travel_uses',{}).pop(SOVEREIGN,None)


@hook('event')
def rain_native_environment(engine,event_type,kwargs):
    if event_type=='CONCENTRATION_ENDED':
        # Ending a parent Concentration removes its zone first. That nested
        # removal can resume children before the parent's ENDED notification;
        # publish the surviving current copy after that notification as well.
        source=kwargs.get('source_definition_id')
        if (source_of(engine.action_catalog.get(source)) or source)==SOVEREIGN:
            owner=engine.state.actors.get(kwargs.get('actor_id'))
            current=owner.concentration if owner else None
            if current and current.zone_id and engine.state.zones[current.zone_id].active:
                engine._append_event('CONCENTRATION_STARTED',current.source_definition_id,actor_id=owner.entity_id,
                                     payload={'reason':'SOVEREIGN_CHILD_RESUMED'})
        return
    if event_type not in ('ZONE_CREATED','ZONE_REMOVED'):return
    if getattr(engine,'_rain_environment_busy',False):
        if event_type=='ZONE_REMOVED':
            ended=engine.state.zones.get((kwargs.get('payload') or {}).get('zone_id'))
            if ended is not None and ended.trigger_profile.get('profile',{}).get('rain_family'):
                release_combat_site(engine,ended)
                from .area_suppression import release_source
                release_source(engine,ended.zone_id)
        return
    engine._rain_environment_busy=True
    try:
        if event_type=='ZONE_REMOVED':
            zid=(kwargs.get('payload') or {}).get('zone_id')
            ended=engine.state.zones.get(zid)
            if ended is not None and ended.trigger_profile.get('profile',{}).get('rain_family'):
                release_combat_site(engine,ended)
            if ended is not None and ended.trigger_profile.get('profile',{}).get('rain_family'):
                from .area_suppression import release_source
                release_source(engine,zid)
                from .. import zones
                for child in list(rainzones(engine)):
                    if child.trigger_profile['profile'].get('sovereign_parent')==zid:
                        # Re-establish the child's own concentration when the
                        # printed exemption ends; its original clock continues.
                        owner=engine.state.actors[child.owner_id]
                        from .needle import incapacitated
                        if not owner.active or incapacitated(owner):
                            zones.remove(engine,child,'OWNER_CANNOT_CONCENTRATE')
                            continue
                        engine._start_concentration(owner,child.source_definition_id)
                        bind_rain_concentration(engine,owner,child)
                        record(engine,child,sovereign_parent='')
        for rain in list(rainzones(engine)):reconcile_environment(engine,rain)
    finally:engine._rain_environment_busy=False


@hook('journey_combat_bundle')
def civil_to_combat(bundle,session,aid):
    state=journey_state(session,aid)
    if not state:return bundle
    result=deepcopy(bundle)
    result['raincaller_setup']={'state':deepcopy(state),'seconds':int(session.clock()),
                               'scene_used':int(session.state['actors'][aid]['travel_uses'].get(SOVEREIGN,0))}
    return result


SITE_CONDITION='condition:typed.raincaller_site'


def combat_site(actor):
    return next((c for c in actor.conditions.values() if c.condition_id==SITE_CONDITION),None)


def save_combat_site(engine,actor,state):
    from .condition_ownership import remove_instance
    for c in list(actor.conditions.values()):
        if c.condition_id==SITE_CONDITION:remove_instance(engine,actor,c.instance_id,CALL)
    engine._apply_condition(actor,SITE_CONDITION,CALL,actor.entity_id,expires_on='UNTIL_REMOVED',
                            data={'label':'Recorded Raincaller site','state':deepcopy(state)})


@hook('match_initialize')
def import_civil_rain(engine):
    from . import placed
    from ..gate2_runtime_models import Position
    initialized=False
    for bundle in getattr(engine,'typed_bundle_documents',()):
        setup=bundle.get('raincaller_setup');actor=engine.state.actors.get(bundle['actor_id'])
        if not setup or actor is None or not owns(engine,actor,CALL):continue
        initialized=True;save_combat_site(engine,actor,setup['state'])
        if setup['scene_used']:
            engine._apply_condition(actor,'condition:typed.raincaller_scene_use',SOVEREIGN,actor.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Monsoon Sovereign used this scene'})
        # The parent must exist before children resume their exemption.
        rains=sorted(setup['state']['rains'].items(),key=lambda item:item[1]['kind']!='sovereign')
        for key,rain in rains:
            kind=rain['kind']
            seconds=rain['expires_at']-setup['seconds']
            if seconds<=0:continue
            center=Position.model_validate(rain['center']);height={'call':20,'wall':10,'sovereign':50}.get(kind)
            cells=([Position(x=x,y=y,z=center.z) for x,y in rain['wall_cells']] if kind=='wall'
                   else placed.area(engine,center,'sphere',rain['radius_ft']))
            source=next((a.source_definition_id for a in engine.action_catalog.values() if a.owner_id==actor.entity_id and source_of(a)==rain['source']),rain['source'])
            parent=None
            if kind in ('call','wall'):
                parent=next((z for z in rainzones(engine,kind='sovereign') if all(
                    point_inside(engine,z,c) and point_inside(engine,z,Position(x=c.x,y=c.y,z=center.z+height//5-1)) for c in cells)),None)
            concentrating=kind!='rite' and parent is None
            if concentrating:engine._start_concentration(actor,source)
            extra=json.loads(rain.get('trigger_profile_json','{}'))
            extra.update(**({'height_ft':height} if height is not None else {}),source_profile=rain_source_profile(rain['source'],rain['numbers'],concentrating),
                profile={'rain_family':kind,'allies':list(rain['allies']),'form':rain['form'],
                    'sovereign_parent':parent.zone_id if parent else '',
                    'effects':list(rain['effects']),'contests':deepcopy(rain.get('contests',{})),
                    'civil_age_seconds':setup['seconds']-rain['created_at'],'civil':1,'civil_expires_at':rain['expires_at'],'civil_started_at':rain['created_at'],
                    'clear_zones':deepcopy(rain['clear_zones'])})
            if kind=='wall':extra['wall']={'height_ft':10,'thick_ft':5,'obscures':'hostile'}
            zone=placed.place(engine,actor,source=source,tag='raincaller_civil',cells=cells,
                name=RAIN_NAMES[kind],shape='wall' if kind=='wall' else 'sphere' if kind=='rite' else 'cylinder',size_ft=rain['radius_ft'],
                duration_rounds=(seconds+5)//6,concentration=concentrating,numbers=rain['numbers'],
                difficult='hostile' if kind in ('wall','sovereign') else None,obscured='heavy' if kind=='wall' else None,
                triggers=[{'on':['enter','start'],'who':'hostile','effects':[{'type':'raincaller_push','wall':True}]}] if kind=='wall' else [],
                extra=extra,material='water')
            # Preserve the selected center even for a clipped cylinder footprint.
            zone.center=center
            if concentrating:bind_rain_concentration(engine,actor,zone)
            if kind=='call':
                set_form(engine,zone,rain['form'])
            else:record(engine,zone)
            transferred=deepcopy(combat_site(actor).data['state'])
            migrate_site_claim(transferred,transferred['rains'][key],zone.zone_id)
            save_combat_site(engine,actor,transferred)
            settle_combat_site(engine,zone)
    return True if initialized else None


@hook('journey_snapshot_actor')
def rain_snapshot(creature,session,aid,engine):
    if not journey_owns(session,aid,CALL):return creature
    result=creature.model_copy(deep=True)
    # The site is exported as source state, not as a second encounter copy.
    result.conditions={k:c for k,c in result.conditions.items() if c.condition_id not in (SITE_CONDITION,'condition:typed.raincaller_scene_use')}
    own_sources={z.source_definition_id for z in rainzones(engine,aid)}
    if result.concentration and result.concentration.source_definition_id in own_sources:result.concentration=None
    from ..concentration import HELD
    result.conditions={k:c for k,c in result.conditions.items() if not (c.condition_id==HELD and (c.data.get('held') or {}).get('source_definition_id') in own_sources)}
    # A native concentration duration marker belongs to the same exported source.
    result.conditions={k:c for k,c in result.conditions.items() if not (c.source_definition_id in own_sources and c.condition_id.endswith('concentration_deadline'))}
    return result


@hook('journey_encounter_settled')
def rain_return(session,aid,engine,creature):
    if not journey_owns(session,aid,CALL):return
    state=journey_state(session,aid)
    held=combat_site(creature)
    if state is None and held is None and not rainzones(engine,aid):return
    if held is not None:
        session.state['actors'][aid].setdefault('source_states',{})[BASE]=deepcopy(held.data['state'])
        state=journey_state(session,aid)
    if state is None:
        # A field cast during combat needs continuation even when no civil
        # environmental survey was collected. Empty records confer no world
        # facts or permission to start a new civil activation.
        state={'rains':{},'blessings':[],'site_expiry':0,
               'site':{'features':[],'containers':[],'allies':list(session.state['actors'])}}
        session.state['actors'][aid].setdefault('source_states',{})[BASE]=state
    if session.state.get('raincaller_settled_match')!=engine.state.match_id:
        elapsed=max(0,engine.state.round_number-1)*6
        session.tick(elapsed)
        session.state['raincaller_settled_match']=engine.state.match_id
    now=int(session.clock())
    active={(z.trigger_profile['profile']['rain_family'] if z.trigger_profile['profile']['rain_family'] in ('call','rite','sovereign') else z.zone_id):z
            for z in rainzones(engine,aid) if z.trigger_profile['profile']['rain_family'] in ('call','wall','sovereign','rite')}
    for key in list(state['rains']):
        if key not in active:
            # A surviving wall changes its native zone id on encounter entry;
            # retain that exact claim until it is migrated below.
            if not any(rain.get('native_zone')==z.zone_id for rain in [state['rains'][key]] for z in active.values()):release_site_claim(state,state['rains'][key])
            del state['rains'][key]
    for key,z in active.items():
        kind=z.trigger_profile['profile']['rain_family']
        p=z.trigger_profile['profile'];remaining=max(0,int(z.duration_rounds or 0)-(engine.state.round_number-z.created_round))*6
        if p.get('civil_expires_at') is not None:remaining=min(remaining,max(0,int(p['civil_expires_at'])-now))
        if remaining<=0:continue
        old=state['rains'].get(key,{})
        created_at=int(p.get('civil_started_at',old.get('created_at',now)))
        state['rains'][key]={**old,'kind':kind,'source':RAIN_SOURCES[kind],
            'center':z.center.model_dump(mode='json'),'created_at':created_at,'expires_at':min(int(old.get('expires_at',now+remaining)),now+remaining),
            'native_zone':z.zone_id,'radius_ft':int(z.trigger_profile['size_ft']),'effects':p.get('effects',[]),'form':p.get('form',''),
            'allies':list(p['allies']),'clear_zones':p.get('clear_zones',[]),'numbers':deepcopy(z.trigger_profile['numbers']),
            'contests':deepcopy(p.get('contests',{})),'last_second':now,
            'trigger_profile_json':json.dumps(z.trigger_profile,sort_keys=True),'concentration':int(z.concentration_link),
            'sovereign_parent':p.get('sovereign_parent','')}
        if kind=='wall':state['rains'][key]['wall_cells']=[[c.x,c.y] for c in z.affected_cells]
    state.pop('combat_rains',None)
    if any(c.condition_id=='condition:typed.raincaller_scene_use' for c in creature.conditions.values()):
        session.state['actors'][aid]['travel_uses'][SOVEREIGN]=1
    session.emit('RAIN_ENCOUNTER_SETTLED',aid,source=CALL,remaining_rains=list(state['rains']))


@hook('compile_actions')
def water_collection_action(info):
    if CALL not in info['owned_ids']:return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.raincaller.collect",display_name='Call Rain: collect clean water',
        owner_id=info['actor_id'],economy='ACTION',resolution_kind='TYPED',target_kind='SELF',
        parameters={'raincaller_collection':1,'typed':{'source':CALL,'numbers':info['numbers'],'duration':{'kind':'instant'},
           'manual_inline_choice':True,'effects':[{'type':'raincaller_collect'}],'riders':[]},
           'description':'Action: collect one waterskin of clean Call Rain water into an actual adjacent container inside the rain; once per round, no Qi.'})]


def collectible(engine,actor):
    from ..gate2_runtime_models import Position
    from ..senses import perceives_cell
    result=[]
    for z in rainzones(engine,kind='call'):
        if z.trigger_profile['profile'].get('collected_round')==engine.state.round_number:continue
        site_owner=engine.state.actors[z.owner_id];held=combat_site(site_owner)
        if held is None:continue
        for c in held.data['state']['site']['containers']:
            p=Position.model_validate(c['position'])
            if c['open']==1 and c['water']<c['capacity'] and point_inside(engine,z,p) and engine.grid.distance_ft(actor.position,p)<=5 and perceives_cell(engine,actor,p):
                result.append((z,c,site_owner))
    return result


SHARED_COLLECTION='system:raincaller.collect'


@hook('match_start')
def shared_water_collection(engine):
    if not any(owns(engine,a,CALL) for a in engine.state.actors.values()):return
    from ..gate2_runtime_models import ActionDefinition
    engine.action_catalog[SHARED_COLLECTION]=ActionDefinition(source_definition_id=SHARED_COLLECTION,
        display_name='Call Rain: collect clean water',owner_id='*',economy='ACTION',resolution_kind='TYPED',target_kind='SELF',
        parameters={'raincaller_collection':1,'typed':{'source':CALL,'numbers':{},'duration':{'kind':'instant'},
            'manual_inline_choice':True,'effects':[{'type':'raincaller_collect'}],'riders':[]},
            'description':'Action: collect one waterskin of clean rainwater into an actual adjacent open vessel inside Call Rain. One waterskin per rain area per round; no Qi or cultivation ownership is required.'})


@hook('additional_actions')
def ordinary_collection(engine,actor):
    if owns(engine,actor,CALL) or SHARED_COLLECTION not in engine.action_catalog:return []
    return [SHARED_COLLECTION] if collectible(engine,actor) else []


@hook('candidate_allowed')
def collection_allowed(engine,actor,candidate,action):
    if action is None or not action.parameters.get('raincaller_collection'):return None
    return bool(collectible(engine,actor))


@effect('raincaller_collect')
def collect_water(ctx,row):
    options={z.zone_id+'|'+c['id']:(z,c,owner) for z,c,owner in collectible(ctx.engine,ctx.actor)}
    picked=ask(ctx,'container',options,labels={k:'Fill '+c['name']+' with one waterskin of clean water' for k,(z,c,owner) in options.items()},
               prompt='Call Rain: collect one waterskin of clean water into an adjacent container inside the rain. Action, no Qi; once per round for this rain area.') if options else []
    if not picked:return
    z,c,owner=options[picked[0]];held=combat_site(owner);state=deepcopy(held.data['state'])
    for container in state['site']['containers']:
        if container['id']==c['id']:
            container['water']+=1
            container['clean_rainwater']=container.get('clean_rainwater',0)+1
            container.setdefault('rainwater_sources',{})[z.zone_id]=container.get('rainwater_sources',{}).get(z.zone_id,0)+1
    save_combat_site(ctx.engine,owner,state);record(ctx.engine,z,collected_round=ctx.engine.state.round_number)
    from .placed import note
    note(ctx.engine,ctx.source,ctx.actor,'Collected one waterskin of clean rainwater into '+c['name']+'.')


def wash_ordinary_irritants(engine,rain,target):
    if rain.trigger_profile['profile']['rain_family']!='call' or not inside(engine,rain,target):return
    from .condition_ownership import remove_instance
    for c in list(target.conditions.values()):
        p=c.data.get('information_profile') or {};tags=set(p.get('tags',()))
        if not counterprocedure_allowed(engine,c.source_definition_id,p,CALL):continue
        if (c.condition_id=='condition:typed.blinded' and p.get('mundane')==1
                and tags&{'dust','smoke','ash','pollen','airborne_irritant','skin_irritant'} and 'injury' not in tags):
            remove_instance(engine,target,c.instance_id,rain.source_definition_id)


@hook('zone_arrival')
def rain_washes_arrival(engine,mover,start,end,forced):
    for rain in rainzones(engine):wash_ordinary_irritants(engine,rain,mover)


@hook('condition_applied')
def rain_washes_new_irritant(ctx,name,subject):
    if name!='blinded':return
    for rain in rainzones(ctx.engine):wash_ordinary_irritants(ctx.engine,rain,subject)


@hook('zone_view_blocked')
def monsoon_wall_view(engine,zone,viewer,seen,*,sight_only=False):
    if zone.trigger_profile.get('profile',{}).get('rain_family')!='wall' or not enemy(engine,zone,viewer):return None
    from .. import senses
    if senses.pierces_wall(engine,zone,viewer,seen,sight_only=sight_only):return None
    return True if crossing(engine,zone,viewer,seen)>0 else None


def lightly_obscured_for(engine,zone,viewer,seen):
    profile=zone.trigger_profile['profile']
    if profile.get('form')=='mist' and enemy(engine,zone,viewer):
        return crossing(engine,zone,viewer,seen)>0 or inside(engine,zone,viewer) or inside(engine,zone,seen)
    if profile['rain_family']=='rite' and 'mist' in profile.get('effects',()):
        if engine.grid.distance_ft(viewer.position,seen.position)<=300:return False
        from ..gate2_runtime_models import Position
        for clear in profile.get('clear_zones',()):
            center=Position.model_validate(clear['center'])
            if engine.grid.distance_ft(center,viewer.position)<=clear['radius_ft'] and engine.grid.distance_ft(center,seen.position)<=clear['radius_ft']:
                return False
        return crossing(engine,zone,viewer,seen)>0
    return False


@hook('stealth_search_mode')
def rain_visual_search(engine,viewer,seen):
    if any(lightly_obscured_for(engine,z,viewer,seen) for z in rainzones(engine)):
        return 'DISADVANTAGE'
    return None


@hook('skill_check_mode')
def rain_visual_check(ctx,subject,ability,skill):
    if str(skill).lower()!='perception' or ctx.typed.get('perception_sense')!='sight' or ctx.target is None:return None
    if any(lightly_obscured_for(ctx.engine,z,subject,ctx.target) for z in rainzones(ctx.engine)):
        return 'DISADVANTAGE'
    return None


@hook('compile_actions')
def origin_selector(info):
    if SOVEREIGN not in info['owned_ids'] or int(info['numbers']['cl'])<18:return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.raincaller.origin",display_name='Monsoon Sovereign: choose rain origin',
        owner_id=info['actor_id'],economy='NONE',resolution_kind='TYPED',target_kind='SELF',
        parameters={'setting_only':True,'raincaller_origin':1,'typed':{'source':SOVEREIGN,'numbers':info['numbers'],'duration':{'kind':'instant'},
            'manual_inline_choice':True,'effects':[{'type':'raincaller_origin'}],'riders':[]},
            'description':'Free choice: select any point inside your Monsoon Sovereign rain as an optional origin for Water-, Rain-, Mist-, Lightning- or Weather-tagged techniques. Range, costs and legal targets stay the same.'})]


@hook('candidate_allowed')
def origin_selector_available(engine,actor,candidate,action):
    if action is None or not action.parameters.get('raincaller_origin'):return None
    return owns(engine,actor,SOVEREIGN) and bool(rainzones(engine,actor,'sovereign'))


@effect('raincaller_origin')
def select_origin(ctx,row):
    from ..gate2_runtime_models import Position
    options={}
    for z in rainzones(ctx.engine,ctx.actor,'sovereign'):
        for c in z.affected_cells:
            for height in range(z.center.z,z.center.z+10):
                point=Position(x=c.x,y=c.y,z=height)
                if point_inside(ctx.engine,z,point):options[f'{point.x},{point.y},{point.z}']=(z,point)
    chosen=ask(ctx,'origin',options,labels={key:f'Rain point ({p.x}, {p.y}), {p.z*5} feet high' for key,(z,p) in options.items()},
        prompt='Monsoon Sovereign: choose any point inside your rain as an optional origin for your tagged techniques. No action or Qi cost. Your own position remains available.') if options else []
    if not chosen:return
    from .condition_ownership import refresh_owned
    refresh_owned(ctx.engine,ctx.actor,'condition:typed.raincaller_origin',ctx.actor.entity_id,SOVEREIGN)
    z,point=options[chosen[0]]
    ctx.engine._apply_condition(ctx.actor,'condition:typed.raincaller_origin',SOVEREIGN,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'label':'Chosen Monsoon Sovereign technique origin','zone_id':z.zone_id,'position':point.model_dump(mode='json')})


def initial_health_snapshot(actor):
    """Use the installed native genesis maximum only when no encounter exists.

    Existing canonical encounter health/conditions always take precedence.
    The source adds Temporary HP, never heals, revives or invents life-state facts.
    """
    template=actor['bundle']['actor_template']
    return actor.setdefault('encounter_snapshot',{'current_hp':template['maximum_hp'],'maximum_hp':template['maximum_hp'],
        'temporary_hp':0,'active':1,'life_state':'','conditions':{},'death_saves':{'ok':0,'bad':0}})


def civil_restorative(session,aid,rain,before,now):
    if rain['kind']!='call' or rain.get('form')!='restorative':return
    state=journey_state(session,aid)
    first=max(1,(before-rain['created_at'])//6+1)
    last=min(9,(now-rain['created_at'])//6)
    for slot in range(first,last+1):
        for who in state['site']['allies']:
            actor=session.state['actors'][who]
            if not civil_reaches(session,rain,actor['position']):continue
            snapshot=initial_health_snapshot(actor)
            if not snapshot['active']:continue
            snapshot['temporary_hp']=max(snapshot['temporary_hp'],int(rain['numbers']['pb']))
            session.emit('RAIN_TEMP_HP_GRANTED',who,source=SHAPE,caster=aid,round=slot,temporary_hp=int(rain['numbers']['pb']),
                         at_second=rain['created_at']+slot*6)


@hook('journey_state_changed')
def civil_concentration_lifecycle(session,aid):
    state=journey_state(session,aid)
    if not state:return
    if session.state['actors'][aid]['incapacitated']:
        for key,rain in list(state['rains'].items()):
            if key!='rite':
                release_site_claim(state,rain)
                del state['rains'][key]
                session.emit('RAIN_ENDED',aid,source=rain['source'],reason='The source owner cannot maintain Concentration.')


def channel_destination(ctx,target,paths):
    """The moving creature's actual route choice establishes willing movement.

    Alliance never stands in for acceptance. Manual/Ask recipients retain their
    own off-turn choice, including during another creature's automatic turn.
    AI options use that recipient's own perception, never the caster's roster.
    """
    from .needle import ask as choose,checkpoint_id
    from ..senses import perceives_cell
    known=[key for key,path in paths.items() if perceives_cell(ctx.engine,target,path.destination)]
    return choose(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'RAIN_SAFE_CHANNEL',target.entity_id),target,
        'choice:needle.rain_channel_destination',list(paths),
        labels={k:f'Move {target.display_name} to ({path.destination.x}, {path.destination.y}), {path.destination.z*5} feet high, without provoking' for k,path in paths.items()},
        minimum=0,maximum=1,allow_decline=True,default='decline',automatic_options=known,
        name='Safe Channel',feature_id=SOVEREIGN,target_id=target.entity_id,
        prompt=f'Safe Channel: {target.display_name} may accept movement up to 15 feet to a legal destination inside Monsoon Sovereign rain. Choose your destination, or stay. No action, Reaction or Qi cost; no opportunity attacks.')


@hook('journey_before_command')
def remember_source_clock(session,aid,kind,payload):
    # Source-state clocks are relative to the current journey. Retain the last
    # committed offset so beginning another journey cannot renew old durations.
    for owner in session.state['actors']:
        state=journey_state(session,owner)
        if state is not None:
            state['clock_journey']=session.state['journey_id']
            state['clock_second']=int(session.clock())


@hook('journey_initialize')
def rebase_source_clock(session,aid):
    state=journey_state(session,aid)
    if not state or state.get('clock_journey')==session.state['journey_id']:return
    offset=int(state.get('clock_second',0))
    # Pin legacy civil identities before changing created_at. Source claims
    # retain their keys across clocks, reloads and further journey transitions.
    for rain in state.get('rains',{}).values():rain.setdefault('claim_id',site_claim_id(rain))
    timestamp_keys={'created_at','expires_at','last_second','site_expiry','wet_until',
                    'suppressed_until','spread_blocked_until','tolerable_until'}
    def shift(value):
        if isinstance(value,dict):
            for key,held in value.items():
                if key in timestamp_keys and type(held) is int:value[key]=held-offset
                elif key=='rain_claims':
                    for claims in held.values():
                        for identity,deadline in claims.items():claims[identity]=deadline-offset
                else:shift(held)
        elif isinstance(value,list):
            for held in value:shift(held)
    shift(state)
    state['clock_journey']=session.state['journey_id'];state['clock_second']=int(session.clock())
    # Ending a journey does not end a scene. The once-per-scene use is kept in
    # travel_uses by the existing native continuation producer.


@hook('combat_world_fact_committed')
def rain_washes_world_irritants(engine,receipt):
    # World-produced conditions use the same explicit cause profile as native
    # techniques. This notification follows the producer in the strict commit.
    for rain in rainzones(engine,kind='call'):
        for target in engine.state.actors.values():wash_ordinary_irritants(engine,rain,target)


@hook('fact_admission_validate')
def validate_site_input(session,source,subject,kind,scope,value):
    if source!=CALL or kind not in ('rain_site','rain_environment_event'):return None
    if kind=='rain_site':validate_site(session,value)
    else:validate_environment_event(session,subject,value)
    return True


@hook('combat_world_fact_committed')
def collect_combat_site(engine,receipt):
    if receipt['source']!=CALL or receipt['kind']!='rain_site':return
    actor=engine.state.actors[receipt['subject']]
    if not owns(engine,actor,CALL):return
    held=combat_site(actor)
    from ..journey import require
    require(held is None,'An encounter site cannot overwrite already committed water or environmental work.')
    save_combat_site(engine,actor,{'rains':{},'blessings':[],'site':deepcopy(receipt['value']),
        'site_receipt':receipt['receipt_id'],'site_expiry':receipt['expires_at']})
    for rain in rainzones(engine,actor):settle_combat_site(engine,rain)


class RainSiteSettlement:
    """Family adapter over an admitted site and the committed encounter clock.

    This is the same Raincaller civil derivation, using the live engine roller
    and event journal. It creates no combatants, abilities or trigger receipts.
    """
    def __init__(self,engine,actor,state,source):
        self.engine=engine;self.source=source;self.grid=engine.grid
        self.state={'actors':{actor.entity_id:{'source_states':{BASE:state}}}}
        self.seconds=next((b['raincaller_setup']['seconds'] for b in engine.typed_bundle_documents
                           if b['actor_id']==actor.entity_id and b.get('raincaller_setup')),0)+max(0,engine.state.round_number-1)*6
    def clock(self):return self.seconds
    def emit(self,kind,aid,**payload):
        source=payload.pop('source',self.source)
        self.engine._append_event(kind,source,actor_id=aid,target_ids=(aid,),payload=payload)


def settle_combat_site(engine,zone):
    actor=engine.state.actors[zone.owner_id];held=combat_site(actor)
    if held is None:return
    state=deepcopy(held.data['state']);adapter=RainSiteSettlement(engine,actor,state,zone.source_definition_id)
    now=adapter.clock();profile=zone.trigger_profile['profile'];kind=profile['rain_family']
    if kind not in ('call','wall','sovereign','rite'):return
    source=(source_of(engine.action_catalog.get(zone.source_definition_id)) or zone.source_definition_id)
    age=max(0,engine.state.round_number-zone.created_round)*6+int(profile.get('civil_age_seconds',0))
    rain=state.setdefault('combat_rains',{}).setdefault(zone.zone_id,
        {'kind':kind,'source':source,'center':zone.center.model_dump(mode='json'),
         'created_at':now-age,'expires_at':now+max(0,int(zone.duration_rounds or 0)-(engine.state.round_number-zone.created_round))*6,
         'radius_ft':int(zone.trigger_profile['size_ft']),'form':profile.get('form',''),
         'effects':list(profile.get('effects',[])),'numbers':deepcopy(zone.trigger_profile['numbers']),
         'contests':{},'last_second':now-age,'allies':list(profile['allies']),'clear_zones':deepcopy(profile.get('clear_zones',[]))})
    stamp=str(now)
    if rain.get('settled_at')==stamp:return
    rain['settled_at']=stamp;rain['native_zone']=zone.zone_id
    apply_civil_rain(adapter,actor.entity_id,rain,rain['last_second'],min(now,rain['expires_at']))
    save_combat_site(engine,actor,state)


def journey_water_choices(session,aid):
    if session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:return []
    result=[]
    for owner in session.state['actors']:
        state=journey_state(session,owner)
        if not state:continue
        rain=state['rains'].get('call')
        if not rain or rain['expires_at']<=session.clock():continue
        for vessel in state['site']['containers']:
            if (vessel['open'] and vessel['water']<vessel['capacity'] and civil_reaches(session,rain,vessel['position'])
                    and distance_ft(session,session.state['actors'][aid]['position'],vessel['position'])<=5):
                result.append({'id':'rain_collect:'+owner+':'+vessel['id'],'kind':'rain_collect',
                    'payload':{'owner':owner,'container':vessel['id']},'auto_select':0,
                    'label':'Collect one waterskin of clean rainwater into adjacent '+vessel['name']+'; one per rain area per round, no Qi.'})
    return result


def journey_collect_water(session,aid,payload):
    from ..journey import require
    require(set(payload)<={'owner','container'} and 'container' in payload,'Choose an actual rain source and vessel.')
    owner=payload.get('owner',aid)
    require(type(owner) is str and owner in session.state['actors'],'Choose a present rain source owner.')
    state=journey_state(session,owner)
    require(state is not None,'Call Rain must still be active.')
    rain=state['rains'].get('call')
    require(rain is not None and rain['expires_at']>session.clock(),'Call Rain must still be active.')
    vessel=next((c for c in state['site']['containers'] if c['id']==payload['container']),None)
    require(vessel is not None and vessel['open'] and vessel['water']<vessel['capacity']
            and civil_reaches(session,rain,vessel['position']) and distance_ft(session,session.state['actors'][aid]['position'],vessel['position'])<=5,
            'Choose a nonfull open vessel within 5 feet and inside Call Rain.')
    slot=(int(session.clock())-rain['created_at'])//6
    require(rain.get('collected_slot',-1)<slot,'Only one waterskin of clean water can be collected each round.')
    rain['collected_slot']=slot;vessel['water']+=1
    vessel['clean_rainwater']=vessel.get('clean_rainwater',0)+1
    identity=site_claim_id(rain)
    vessel.setdefault('rainwater_sources',{})[identity]=vessel.get('rainwater_sources',{}).get(identity,0)+1
    session.emit('RAIN_WATER_COLLECTED',aid,source=CALL,rain_owner=owner,container=vessel['id'],waterskins=1,slot=slot)
    return True


def site_claim_id(rain):
    return rain.get('native_zone') or rain.get('claim_id') or rain['source']+':'+str(rain['created_at'])


def mark_site_feature(feature,key,rain):
    claims=feature.setdefault('rain_claims',{}).setdefault(key,{})
    claims[site_claim_id(rain)]=rain['expires_at']
    feature[key]=max(claims.values())


def release_site_claim(state,rain):
    identity=site_claim_id(rain)
    for feature in state['site']['features']:
        for key,claims in list(feature.get('rain_claims',{}).items()):
            claims.pop(identity,None)
            if claims:feature[key]=max(claims.values())
            else:
                feature.pop(key,None);del feature['rain_claims'][key]
        if not feature.get('rain_claims'):feature.pop('rain_claims',None)


def release_combat_site(engine,zone):
    owner=engine.state.actors.get(zone.owner_id)
    held=combat_site(owner) if owner is not None else None
    if held is None:return
    state=deepcopy(held.data['state']);rain=state.get('combat_rains',{}).pop(zone.zone_id,None)
    if rain is None:return
    release_site_claim(state,rain);save_combat_site(engine,owner,state)


def migrate_site_claim(state,rain,zone_id):
    previous=site_claim_id(rain)
    for feature in state['site']['features']:
        for claims in feature.get('rain_claims',{}).values():
            if previous in claims:claims[zone_id]=claims.pop(previous)
    rain['native_zone']=zone_id


@hook('compile_actions')
def end_rain_action(info):
    if CALL not in info['owned_ids']:return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.raincaller.end",display_name='Raincaller: end your rain',
        owner_id=info['actor_id'],economy='NONE',resolution_kind='TYPED',target_kind='SELF',
        parameters={'raincaller_end':1,'setting_only':True,'typed':{'source':CALL,'numbers':info['numbers'],
            'duration':{'kind':'instant'},'manual_inline_choice':True,'effects':[{'type':'raincaller_end'}],'riders':[]},
            'description':'Free choice: end one of your Call Rain, Monsoon Wall or Monsoon Sovereign areas and its Concentration. Other areas keep their own clocks. No Qi.'})]


@hook('candidate_allowed')
def end_rain_available(engine,actor,candidate,action):
    if action is None or not action.parameters.get('raincaller_end'):return None
    return bool([z for z in rainzones(engine,actor) if z.trigger_profile['profile']['rain_family'] in ('call','wall','sovereign')])


@effect('raincaller_end')
def end_rain(ctx,row):
    from .. import zones,concentration
    options={z.zone_id:z for z in rainzones(ctx.engine,ctx.actor) if z.trigger_profile['profile']['rain_family'] in ('call','wall','sovereign')}
    selected=ask(ctx,'end',options,labels={key:z.trigger_profile['name'] for key,z in options.items()},
        prompt='End one of your rain areas now? No action or Qi; the area and its own Concentration end.') if options else []
    if not selected:return
    zone=options[selected[0]]
    held=[state for _,state in concentration.held(ctx.actor)]+([ctx.actor.concentration] if ctx.actor.concentration else [])
    for state in held:
        if state.zone_id==zone.zone_id:concentration.end_copy(ctx.engine,ctx.actor,state.started_sequence,'CREATOR_ENDED')
    if zone.active:zones.remove(ctx.engine,zone,'CREATOR_ENDED')


@hook('condition_metadata')
def remember_native_condition_source(ctx,subject,row,current):
    """Opt-in source snapshot before a possible later Sovereign cleansing.

    CL/DC come from the actual resolving Context, not a later caster sheet.
    Missing causes remain unknown until the native owner supplies them.
    """
    # Only conditions Purification can later name (poison, airborne Blindness, disease) on a creature
    # that a Monsoon Sovereign owner could treat as an ally. Everything else is left untouched.
    from ..relations import relation,ALLY
    if str(row.get('condition') or '').lower() not in PURIFIABLE_CONDITIONS:return None
    if not any(owns(ctx.engine,a,SOVEREIGN) and (a is subject or relation(ctx.engine,a,subject)==ALLY) for a in ctx.engine.state.actors.values()):return None
    level=ctx.numbers.get('cl')
    if type(level) is not int:return None
    known=current.get('information_profile') or {};profile={}
    if known.get('source_cl') is None:profile['source_cl']=level
    if known.get('save_dc') is None:profile['save_dc']=int(ctx.numbers.get('save_dc') or 0)
    mundane=row.get('mundane',ctx.typed.get('mundane'))
    if type(mundane) is bool and known.get('mundane') is None:profile['mundane']=int(mundane)
    return {'information_profile':profile} if profile else None


def counterprocedure_allowed(engine,source,profile,feature):
    """Numerical Source CL does not erase an explicit superior authority.

    Source owners can record the exact printed exception as a permitted
    counterprocedure; unknown exceptions are never invented by the counterer.
    """
    authority=profile.get('authority') or profile.get('authority_grade')
    protected=authority in ('protected','artifact','secret','immortal','absolute')
    from .source_eligibility import stored_power,protected_power
    power=stored_power(engine,source) if engine is not None else None
    if power and protected_power(*power):protected=True
    return not protected or feature in profile.get('counterprocedures',())


def environment_event_state(session,aid):
    if hasattr(session,'engine'):
        held=combat_site(session.engine.state.actors[aid])
        return held.data['state'] if held else None
    return journey_state(session,aid)


def validate_environment_event(session,aid,value):
    from ..journey import require,integer
    state=environment_event_state(session,aid)
    require(state is not None,'First record the actual environmental site.')
    kind=value.get('kind');extra={'source_feature','sections'} if kind=='ordinary_spread' else set()
    require(kind in ('ordinary_ignition','ordinary_spread') and set(value)=={'kind','feature','cause'}|extra
            and type(value['cause']) is str and bool(value['cause'].strip()),'Record an actual external ignition or wildfire-spread attempt and its cause.')
    feature=next((f for f in state['site']['features'] if f['id']==value['feature']),None)
    require(feature is not None and feature['kind']=='ordinary_fire' and feature['ordinary']==1,'Choose the actual ordinary fire site.')
    if kind=='ordinary_spread':
        source=next((f for f in state['site']['features'] if f['id']==value['source_feature']),None)
        require(source is not None and source is not feature and source['kind']=='ordinary_fire' and source['ordinary']==1
                and source.get('fire_kind')=='wildfire' and source['amount']>0 and feature.get('fire_kind')=='wildfire'
                and distance_ft(session,source['position'],feature['position'])<=10 and integer(value['sections'],1)
                and value['sections']<=1000,'Wildfire spread needs an actual adjacent burning source and a positive number of ten-foot sections.')
    return state,feature


def apply_environment_event(session,aid,value,receipt_id):
    original,original_feature=validate_environment_event(session,aid,value)
    state=deepcopy(original);feature=next(f for f in state['site']['features'] if f['id']==original_feature['id'])
    covering=[]
    if hasattr(session,'engine'):
        from ..gate2_runtime_models import Position
        for zone in rainzones(session.engine):
            if point_inside(session.engine,zone,Position.model_validate(feature['position'])):
                p=zone.trigger_profile['profile'];covering.append((p['rain_family'],p.get('effects',())))
    else:
        for owner in session.state['actors']:
            held=journey_state(session,owner)
            if not held or held['site']['plane']!=state['site']['plane']:continue
            covering.extend((r['kind'],r['effects']) for r in held['rains'].values()
                            if r['expires_at']>session.clock() and civil_reaches(session,r,feature['position']))
    blocked=any(kind in ('call','sovereign') or kind=='wall' and not feature['attended']
                or kind=='rite' and 'firebreak' in effects and value['kind']=='ordinary_spread'
                for kind,effects in covering)
    if not blocked:feature['amount']+=value.get('sections',1)
    if hasattr(session,'engine'):
        save_combat_site(session.engine,session.engine.state.actors[aid],state)
    else:session.state['actors'][aid]['source_states'][BASE]=state
    session.emit('RAIN_FIRE_PREVENTED' if blocked else 'ORDINARY_FIRE_CREATED',aid,source='system:raincaller.environment',
                 authority='table_owner',input_receipt_id=receipt_id,feature=feature['id'],attempt_kind=value['kind'],cause=value['cause'],sections=value.get('sections',1),
                 text='Cultivated rain prevents the ordinary fire attempt.' if blocked else 'The actual ordinary fire attempt creates fire.')


@hook('journey_world_fact_committed')
def journey_environment_event(session,receipt):
    if receipt['source']==CALL and receipt['kind']=='rain_environment_event':apply_environment_event(session,receipt['subject'],receipt['value'],receipt['receipt_id'])


@hook('combat_world_fact_committed')
def combat_environment_event(engine,receipt):
    if receipt['source']!=CALL or receipt['kind']!='rain_environment_event':return
    actor=engine.state.actors[receipt['subject']];held=combat_site(actor)
    adapter=RainSiteSettlement(engine,actor,deepcopy(held.data['state']),CALL)
    apply_environment_event(adapter,actor.entity_id,receipt['value'],receipt['receipt_id'])
