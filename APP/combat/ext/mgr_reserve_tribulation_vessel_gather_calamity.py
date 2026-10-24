"""Tribulation Vessel's source-owned collection and five-stage progression.

Public source interface: journey_acquisition + journey_source_sheet implement
Restricted Scripture admission. World-owned calamity profiles describe actual
sources, never claim that an exposure occurred. Face Calamity resolves that
profile through ordinary native saves, paid costs and damage. Charges are only
collected from settled native receipts, and their receipt IDs are retained.
All state is condition/event backed or source_states journey state; no patches.
"""
from copy import deepcopy
from dataclasses import replace
import json
from . import hook, effect
from ..journey import require
from .condition_ownership import remove_instance
from ..relations import relation,ENEMY
P='tianxia.subpath.qi.tribulation_vessel'
F=P+'.feature.'
NAMES=('gather_calamity','calamity_tempering','tribulation_release','calamity_furnace','walking_tribulation')
LEVELS=(3,6,10,14,18)
LEDGER='condition:typed.tribulation_vessel'
QI='resource:core.qi'
CHARGES='resource:named.calamity_charge'
NATIVE_DAMAGE=('acid','bludgeoning','cold','fire','force','lightning','necrotic','piercing','poison','psychic','radiant','slashing','thunder')
TYPES=('Flame','Frost','Lightning','Storm','Force','Gravity','Blood','Shadow','Spirit','General')
DAMAGE={'Flame':['fire'],'Frost':['cold'],'Lightning':['lightning'],'Storm':['thunder','lightning'],'Force':['force'],'Gravity':['force','bludgeoning'],'Blood':['necrotic'],'Shadow':['necrotic','psychic'],'Spirit':['psychic','radiant'],'General':['force']}


def owned(engine,actor):
    row=next((r for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,[]) if r.get('block')=='tribulation_vessel'),None)
    if row is None:return None
    from .body_modes_scene_resources import effective_cl,available
    level=effective_cl(engine,actor,'tianxia.path.qi_cultivation',int(row['cl']))
    features=[n for n,l in zip(NAMES,LEVELS) if n in row['features'] and available(engine,actor,F+n,l,requires_conscious=False,path_id='tianxia.path.qi_cultivation',compiled_level=int(row['cl']))]
    if level==row['cl'] and features==row['features']:return row
    pb=int(row['pb']) if level==row['cl'] else min(int(row['pb']),2+(max(1,level)-1)//4)
    return {**row,'cl':level,'pb':pb,'save_dc':int(row['save_dc'])-int(row['pb'])+pb,'features':features}


@hook('body_mode_profiles')
def availability_profile(bundle):
    row=next((r for r in bundle.get('typed_passives',[]) if r.get('block')=='tribulation_vessel'),None)
    if row:return [{'source':P,'name':'Tribulation Vessel availability','path_id':'tianxia.path.qi_cultivation','availability_only':1,'feature_levels':{F+n:l for n,l in zip(NAMES,LEVELS) if n in row['features']}}]


def state(engine,actor):
    row=next((c for c in actor.conditions.values() if c.condition_id==LEDGER),None)
    return json.loads(row.data['ledger']) if row else {'charges':[],'history':[],'events':[],'sequence':0}


def store(engine,actor,data,*,expired=False):
    # Suppression limits future collection; it does not erase survived Charges.
    # Only printed spending, Long Rest and Walking's explicit ending cap expire
    # them. Keep represented capacity large enough for already-held state.
    if CHARGES in actor.resources:
        count=len(data['charges']);cap=max(count,maximum(owned(engine,actor))+sum(c.get('overflow',0) for c in data['charges']))
        current=actor.resources[CHARGES]
        if current>count:
            if expired:
                actor.resources[CHARGES]=count
                engine._append_event('RESOURCE_EXPIRED',F+NAMES[0],actor_id=actor.entity_id,payload={'resource_id':CHARGES,'before':current,'after':count})
            else:engine._spend_resource(actor,CHARGES,current-count,F+NAMES[0])
        engine._set_resource_maximum(actor,CHARGES,cap,F+NAMES[0])
        if actor.resources[CHARGES]<count:engine._gain_resource(actor,CHARGES,count-actor.resources[CHARGES],F+NAMES[0])
    content={'ledger':json.dumps(data,sort_keys=True),'label':str(len(data['charges']))+' Calamity Charges: '+', '.join(c['type'] for c in data['charges'])}
    existing=next((c for c in actor.conditions.values() if c.condition_id==LEDGER),None)
    if existing:engine._update_condition_data(actor,existing,content,F+NAMES[0])
    else:engine._apply_condition(actor,LEDGER,F+NAMES[0],actor.entity_id,expires_on='UNTIL_REMOVED',data=content)


def stamp(engine):
    from .body_modes_scene_resources import turn_key
    return turn_key(engine)
def maximum(row):
    # None means the creature does not currently own the Path row at its
    # compiled level (for example under cultivation suppression). Capacity then
    # contributes zero; already-held Charges are kept by store()'s max(count,...).
    return 0 if row is None else int(row['pb'])+(3 if NAMES[3] in row['features'] else 0)
def walking(data):return bool(data.get('walking'))


def walking_remaining(engine,clock):
    from fractions import Fraction
    if 'deadline_num' in clock:
        from ..combat_world_facts import clock as world_clock
        return Fraction(clock['deadline_num'],clock['deadline_den'])-world_clock(engine)
    return Fraction(clock.get('remaining_num',int(clock['remaining'])*6),clock.get('remaining_den',1))


def retain_walking_clock(engine,clock):
    from ..combat_world_facts import clock as world_clock
    left=walking_remaining(engine,clock)
    deadline=world_clock(engine)+left
    clock.update(deadline_num=deadline.numerator,deadline_den=deadline.denominator,
                 remaining_num=left.numerator,remaining_den=left.denominator,
                 remaining=max(0,-(-left.numerator//(left.denominator*6))))
    return left


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source!=P:return None
    if kind in ('source_access','calamity_profile'):
        return {'value_type':'document','maximum_seconds':2592000,'authority':'table_owner',
                'description':'Restricted scripture access' if kind=='source_access' else 'Named real calamity, source authority and uncompromised consequences'}


@hook('journey_source_sheet')
def source_sheet(sheet,session,actor_id):
    data=session.state['actors'][actor_id].get('source_states',{}).get(P)
    if not data or 'attainment' not in data:return None
    paths=sheet.setdefault('path_and_subpath',{})
    cl=int(sheet['identity']['cultivation_level'])
    paths['path_feature_record_ids']=list(dict.fromkeys([*paths.get('path_feature_record_ids',[]),*[F+n for n,l in zip(NAMES,LEVELS) if l<=min(cl,data['attainment'])]]))
    paths['subpath_record_id']=P;paths['subpath_record_ids']=[P]
    sheet['tribulation_vessel_profiles']=[deepcopy(p) for p in data.get('profiles',[]) if p['expires_at']>session.clock() and p.get('journey_id')==session.state['journey_id']]
    for p in sheet['tribulation_vessel_profiles']:p['valid_seconds']=int(p['expires_at']-session.clock())
    return sheet


@hook('journey_acquisition')
def acquire(session,actor_id,source,payload,sheet):
    if source!=P:return None
    from ..fact_consent_admission import read
    require(set(payload)<={'access_scope','hazard_scopes'} and 'access_scope' in payload,'Choose the restricted scripture admission.')
    access=read(session,P,actor_id,'source_access',payload['access_scope'],actor_id)
    require(access and access['value'].get('route')=='restricted_scripture' and access['value'].get('source_rule'),'Restricted Scripture requires explicit table-owner source access.')
    cl=int(sheet['identity']['cultivation_level']);paths=sheet.get('path_and_subpath',{})
    attainment=max((int(p.get('attainment',0)) for p in paths.get('paths',[]) if p.get('path_id')=='tianxia.path.qi_cultivation'),default=0)
    cl=min(cl,attainment)
    require(cl>=3 and any(p.get('path_id')=='tianxia.path.qi_cultivation' and int(p.get('attainment',0))>=3 for p in paths.get('paths',[])),'Tribulation Vessel requires Qi Cultivation attainment 3.')
    require(not any('calamity_devouring_tribulation_vessel' in x for x in paths.get('path_feature_record_ids',[])),'A replacement progression cannot coexist with Tribulation Vessel.')
    subpaths=[paths.get('subpath_record_id'),*paths.get('subpath_record_ids',[])]
    require(all(not item or item==P or not item.startswith('tianxia.subpath.qi.') for item in subpaths),'Acquire only one Qi subpath progression.')
    require(not any(mid.startswith('tianxia.subpath.qi.') and not mid.startswith(F) for mid in paths.get('path_feature_record_ids',[])),'Another Qi subpath or replacement progression is already acquired.')
    profiles=[]
    for scope in payload.get('hazard_scopes',[]):
        record=read(session,P,actor_id,'calamity_profile',scope,actor_id)
        require(record,'The calamity profile is missing, private, or expired.')
        profile=deepcopy(record['value']);validate_profile(profile)
        point=profile['position']
        require(point['x']<session.grid.width and point['y']<session.grid.height,'Place the actual calamity inside this scene map.')
        profile.update(receipt_id=record['receipt_id'],expires_at=record['expires_at'],journey_id=session.state['journey_id'])
        profiles.append(profile)
    data=session.state['actors'][actor_id].setdefault('source_states',{}).setdefault(P,{})
    data.update(attainment=cl,access=access['receipt_id'],profiles=profiles)
    result=source_sheet(sheet,session,actor_id)
    session.emit('TRIBULATION_SCRIPTURE_ACQUIRED',actor_id,source=P,access_receipt=access['receipt_id'],attainment=cl)
    return {'sheet':result,'acquisition_id':access['receipt_id']}


def validate_profile(p):
    fields={'name','source_rule','type','source_cl','damage_type','dice','dc','save','status','category','position','legendary','formal_tribulation','cost_qi','genuine_threat'}
    require(fields<=set(p)<=fields|{'resolution','formal_charge_grant','conditions','forced_movement_ft','forced_direction','persistent_scar','save_categories'},'Supply the complete calamity profile, including source, consequences, authority and position.')
    require(isinstance(p.get('save_categories',[]),list) and all(type(tag) is str and tag in ('possession','soul_displacement') for tag in p.get('save_categories',[])) and len(p.get('save_categories',[]))==len(set(p.get('save_categories',[]))), 'Use explicit Source Rule saving-throw categories: possession or soul displacement.')
    require(p.get('resolution','save') in ('save','cultivation_check'),'Use the actual source’s saving throw or Cultivation Check procedure.')
    require(p.get('formal_charge_grant',2) in (2,3) and (p.get('formal_charge_grant',2)!=3 or p['formal_tribulation']==1),'Only a formal tribulation may receive an explicit three-Charge GM grant.')
    require(isinstance(p.get('conditions',[]),list) and set(p.get('conditions',[]))<={'charmed','frightened','grappled','poisoned','prone','restrained','stunned'},'Choose represented harmful native conditions.')
    require(type(p.get('forced_movement_ft',0)) is int and 0<=p.get('forced_movement_ft',0)<=100,'Use a bounded native forced movement distance.')
    if p.get('persistent_scar'):
        scar=p['persistent_scar']
        require(p['formal_tribulation']==1 and isinstance(scar,dict) and set(scar)=={'name','source_rule'} and all(type(v) is str and v.strip() for v in scar.values()),'A persistent named Scar requires its formal breakthrough Source Rule and name.')
    if p.get('forced_movement_ft'):
        direction=p.get('forced_direction',{})
        require({'dx','dy'}<=set(direction)<={'dx','dy','dz'} and all(type(v) is int and v in (-1,0,1) for v in direction.values()) and any(direction.values()),'Supply the calamity’s actual map displacement direction.')
    require(all(type(p[k]) is str and p[k].strip() for k in ('name','source_rule')),'Name the actual calamity and its controlling rule.')
    require(p['type'] in TYPES and p['damage_type'] in NATIVE_DAMAGE,'Choose a represented Calamity and damage type.')
    require(p['save'] in ('dex','con','str','int','wis','cha') and type(p['dc']) is int and 1<=p['dc']<=50,'Supply the real save and DC.')
    require(type(p['source_cl']) is int and p['source_cl']>=1 and all(type(p[k]) is int and p[k] in (0,1) for k in ('legendary','formal_tribulation','genuine_threat')),'Supply explicit source authority.')
    require(p['status'] in ('stable','growing','collapsing','about to discharge') and p['category'] in ('hazard','hostile field','tribulation residue','damaged Formation','unstable artifact','environmental catastrophe'),'Choose an active Calamity Sense category and state.')
    require(set(p['dice'])=={'count','sides'} and type(p['dice']['count']) is int and 1<=p['dice']['count']<=20 and p['dice']['sides'] in (4,6,8,10,12),'Supply positive genuine damage consequences.')
    require(type(p['cost_qi']) is int and p['cost_qi']>=0 and isinstance(p['position'],dict),'Supply the full normal cost and map position.')
    require({'x','y'}<=set(p['position'])<={'x','y','z'} and all(type(v) is int and v>=0 for v in p['position'].values()),'Use native nonnegative whole map coordinates for the real calamity.')


@hook('compile_passives')
def compile_vessel(rows,info):
    mids=set(info['owned_ids']);held=[n for n in NAMES if F+n in mids]
    if not held:return rows
    require(not any('calamity_devouring_tribulation_vessel.feature.' in x for x in mids),'Parent and replacement progression cannot coexist.')
    cl=int(info['numbers']['cl'])
    # The passive row claims Gather Calamity (Calamity Sense's whole trigger is
    # delivered by this plug-in). Calamity Furnace is claimed by no inert
    # marker: its compiled native Reaction row is re-sealed below into the
    # Furnace Response policy row, which the reaction plan then offers.
    return [*rows,{'block':'tribulation_vessel',**{k:int(info['numbers'].get(k,0)) for k in ('cl','pb','key_mod','save_dc')},'features':held,'choice_owner':1,'feature_id':F+NAMES[0],'trigger_owner':'tribulation_vessel'}]


@hook('compile_action')
def remove_placeholder(action,info):
    if not action.parameters.get('vessel_operation') and (action.parameters.get('typed') or {}).get('source') in {F+n for n in NAMES}:
        return action.model_copy(update={'parameters':{**action.parameters,'typed':{**action.parameters['typed'],'effects':[],'riders':[]}}})


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition
    mids=set(info['owned_ids']);out=[]
    if F+NAMES[0] in mids:
        for row in info['passives']:
            if row.get('block')=='tribulation_vessel':row['proficient_saves']=list(info['save_proficiencies'])
    def add(name,n,economy,effects,cost=0,area=None,profile=None):
        typed={'source':F+n,'manual_inline_choice':True,'numbers':dict(info['numbers']),'effects':effects,'riders':[],'duration':{'kind':'instant'}}
        if area:typed['area']=area
        params={'typed':typed,'vessel_operation':n}
        if profile:params['calamity_profile']=profile
        out.append(ActionDefinition(source_definition_id='action:typed.'+info['short']+'.vessel.'+n+'.'+str(len(out)),display_name=name,owner_id=info['actor_id'],economy=economy,resolution_kind='TYPED',target_kind='SELF' if not area else 'CELL',range_ft=0,costs=((QI,cost),) if cost else (),parameters=params))
    if F+NAMES[0] not in mids:return None
    add('Calamity Sense',NAMES[0],'NONE',[{'type':'vessel_sense'}])
    add('Classify Stored Calamity',NAMES[0],'NONE',[{'type':'vessel_classify'}])
    out[-1]=out[-1].model_copy(update={'parameters':{**out[-1].parameters,'vessel_classify':True}})
    if F+NAMES[2] in mids:add('Tribulation Release',NAMES[2],'ACTION',[{'type':'vessel_release'}],3,area={'shape':'sphere','size_ft':30,'explicit_harmful_recipients':'every_creature'})
    if F+NAMES[3] in mids:
        add('Furnace Response',NAMES[3],'REACTION',[{'type':'vessel_reaction_marker'}])
        out[-1]=out[-1].model_copy(update={'parameters':{**out[-1].parameters,'vessel_trigger_only':True}})
        add('Tribulation Scar',NAMES[3],'NONE',[{'type':'vessel_scar'}])
        out[-1]=out[-1].model_copy(update={'parameters':{**out[-1].parameters,'vessel_scar':True}})
    if F+NAMES[4] in mids:add('Walking Tribulation',NAMES[4],'BONUS_ACTION',[{'type':'vessel_walk'}],8)
    for profile in info['owner_sheet'].get('tribulation_vessel_profiles',[]):
        add('Face Calamity: '+profile['name'],NAMES[0],'ACTION',[{'type':'vessel_exposure','applies_to':'self','profile':profile}],profile['cost_qi'],profile=profile)
    return out


@hook('compile_reaction')
def furnace_policy(row,info):
    """Reseal the character's one compiled native Calamity Furnace Reaction row
    into the Furnace Response policy row the family's reaction windows gate on
    (combat/typed_reactions.can_use_reaction) and the existing Auto / Ask me /
    off plan offers. Keeping the row the printer already produced means exactly
    one implementation: no hook, marker or duplicate reaction row is added."""
    if info['mechanic_id']!=F+NAMES[3]:return None
    return {'feature_id':F+NAMES[3],'block':'tribulation_vessel_response','name':'Furnace Response','kind':'damaged','choice_owner':1,
            'when':'when you fail a saving throw, take damage, become Grappled, Prone or Restrained, or would be forcibly moved (2 Calamity Charges, Reaction)'}


@hook('candidate_allowed')
def allowed(engine,actor,candidate,action):
    if action is None:return None
    op=action.parameters.get('vessel_operation')
    if not op:return None
    if action.parameters.get('vessel_trigger_only'):return False
    row=owned(engine,actor)
    if not row or op not in row['features'] or row['cl']<LEVELS[NAMES.index(op)]:return False
    d=state(engine,actor)
    if action.parameters.get('vessel_classify') and not any(not c.get('damage_types') for c in d['charges']):return False
    if action.parameters.get('vessel_scar') and not d.get('scar'):return False
    if op==NAMES[2]:
        if not any(c.get('damage_types') for c in d['charges']) or actor.resources.get(QI,0)<(0 if walking(d) and d.get('free_release')!=stamp(engine) else 3):return False
        # Ordinary origins are self or the native Domain Armament; the endpoint
        # selected here is only a free Walking origin within thirty feet.
        if candidate.destination:
            from ..gate2_runtime_models import Position
            origin=candidate.metadata.get('effect_origin')
            center=Position.model_validate(origin['position']) if isinstance(origin,dict) else actor.position
            if candidate.destination!=center:return False
    if op==NAMES[4] and (walking(d) or d.get('scene_used') or not d['history']):return False
    p=action.parameters.get('calamity_profile')
    if p:
        if (engine.state.round_number-1)*6>=p.get('valid_seconds',2592000):return False
        from ..gate2_runtime_models import Position
        if engine.grid.distance_ft(actor.position,Position.model_validate(p['position']))>5:return False
    return None


def choose(ctx,actor,key,options,labels,prompt,*,minimum=1,maximum=1,decline=False,automatic=None):
    from .needle import ask,checkpoint_id
    return ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'vessel',key,actor.entity_id),actor,'choice:needle.vessel.'+key,options,labels=labels,prompt=prompt,minimum=minimum,maximum=maximum,allow_decline=decline,default='decline' if decline else options[0],automatic_options=options if automatic is None else automatic,feature_id=ctx.source,name=ctx.action.display_name)


def context(engine,actor,source=None):
    from ..typed_executor import Context
    intent=getattr(engine,'_active_intent',None)
    if intent is None:return None
    action=None
    if source and source.startswith(F):
        choices=[a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id and (a.parameters.get('typed') or {}).get('source')==source and not a.parameters.get('calamity_profile') and not a.parameters.get('vessel_scar')]
        action=next((a for a in choices if a.parameters.get('vessel_trigger_only')),choices[0] if choices else None)
    if action is None:action=engine.action_catalog.get(getattr(engine,'_active_action_source_id',''))
    if action is None:
        action=next((a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id and a.parameters.get('vessel_operation')==NAMES[0] and not a.parameters.get('calamity_profile')),None)
    if action is None:return None
    typed={**(action.parameters.get('typed') or {}),'source':source or (action.parameters.get('typed') or {}).get('source',F+NAMES[0]),'numbers':owned(engine,actor) or {}}
    if source==F+NAMES[4]:
        action=action.model_copy(update={'owner_id':actor.entity_id,'range_ft':15,'target_kind':'HOSTILE_ENTITY'})
    return Context(engine,actor,action,intent,typed,[actor],actor,{})


def collect(ctx,target,receipt,profile=None,*,great=False,damage_types=()):
    row=owned(ctx.engine,target)
    if not row or NAMES[0] not in row['features']:return
    if not receipt.startswith('below_half:') and not genuine(ctx,target):return
    d=state(ctx.engine,target)
    if receipt in d['events']:return
    r=ctx.engine.state.match_id+':'+str(ctx.engine.state.round_number)
    if d.get('events_round')!=r:
        d['events']=[];d['events_round']=r
    prior=d.get('gain_round')
    limit=2 if walking(d) else 1
    blocked=prior==r and int(d.get('gains',0))>=limit
    if profile:kind=profile['type']
    else:
        answer=choose(ctx,target,'calamity_type_'+receipt,list(TYPES),{x:x for x in TYPES},f'{target.display_name}: choose the closest Calamity Type represented by the resolved danger.',automatic=['General'])
        if not answer:return
        kind=answer[0]
    associated=[profile['damage_type']] if profile else sorted({str(k).lower() for k in damage_types if str(k).lower() in NATIVE_DAMAGE})
    association=None
    if not associated:
        from ..fact_consent_admission import admit_choice
        association=admit_choice(ctx,target,F+NAMES[0],'calamity_damage_type',receipt,list(NATIVE_DAMAGE),labels={k:k.capitalize() for k in NATIVE_DAMAGE},prompt='Declare one damage type actually associated with the resolved calamity, or leave its damage association unknown.',expires_on='END_OF_CURRENT_TURN',automatic_options=[])
        associated=[association['value']] if association else []
    d.setdefault('survived_damage_types',{}).setdefault(kind,[])
    d['survived_damage_types'][kind]=sorted(set([*d['survived_damage_types'][kind],*associated]))
    d['history']=sorted(set([*d['history'],kind]))
    if profile and profile.get('formal_tribulation') and profile.get('persistent_scar'):
        named={**profile['persistent_scar'],'type':kind,'source_cl':profile['source_cl'],'damage_types':associated,'authority':'table_owner','source_receipt':profile['receipt_id'],'survived_event':receipt}
        if not any(s['source_receipt']==profile['receipt_id'] for s in d.get('named_scars',[])):
            d.setdefault('named_scars',[]).append(named)
    if blocked:
        d['events'].append(receipt);store(ctx.engine,target,d);return
    source_cl=profile['source_cl'] if profile else int(ctx.numbers.get('cl',0))
    count=3 if profile and profile.get('formal_tribulation') and profile.get('formal_charge_grant')==3 else 2 if great or source_cl>=row['cl']+3 or profile and (profile.get('legendary') or profile.get('formal_tribulation')) else 1
    count=min(count,max(0,maximum(row)-sum(not c.get('overflow') for c in d['charges'])))
    if not count:
        d['events'].append(receipt);store(ctx.engine,target,d);return
    for _ in range(count):
        d['sequence']+=1;d['charges'].append({'id':str(d['sequence']),'type':kind,'source_cl':source_cl,'damage_types':associated,'association_receipt':association['receipt_id'] if association else profile['receipt_id'] if profile else receipt,'event':receipt,'overflow':0})
    d['events'].append(receipt)
    d['history']=sorted(set([*d['history'],kind]));d['gains']=int(d.get('gains',0))+1 if prior==r else 1;d['gain_round']=r
    store(ctx.engine,target,d)


def event_reduced_above_half_to_zero(subject, packets):
    """Read ordered damage receipts for one complete, already-survived event.

    Split damage shares the event's starting HP; its final component need not
    itself start above half. Callers fence source/intent/recipient and survival.
    """
    return bool(packets and packets[0].payload.get('hp_before',0)>subject.maximum_hp//2
                and any(e.payload.get('remaining_hp',1)==0 for e in packets))


@effect('vessel_exposure',harmful=False)
def exposure(ctx,effect):
    from ..typed_executor import run_effects
    p=effect['profile'];start=len(ctx.engine.events);buffer_before=ctx.actor.temporary_hp
    ctx=replace(ctx,typed={**ctx.typed,'numbers':{**ctx.numbers,'save_dc':p['dc']}})
    damage={'type':'damage','applies_to':'self','dice':p['dice'],'damage_types':[p['damage_type']]}
    consequences=[{'type':'condition','applies_to':'self','condition':name,'until_escape':name in ('grappled','restrained'),'expires_on':'START_OF_SOURCE_NEXT_TURN'} for name in p.get('conditions',[])]
    if p.get('forced_movement_ft'):consequences.append({'type':'vessel_hazard_movement','distance_ft':p['forced_movement_ft'],'direction':p['forced_direction']})
    if p.get('resolution')=='cultivation_check':
        reason='CHECK:'+ctx.source
        row=owned(ctx.engine,ctx.actor)
        with ctx.engine.d20_scope({'kind':'check','check_kind':'cultivation','actor_id':ctx.actor.entity_id,'source_id':ctx.source,'source_actor_id':ctx.actor.entity_id,'reason':reason,'dc':p['dc']}):
            roll=ctx.engine.roll_check(modifier=int(row['pb'])+int(row['key_mod']),actor_id=ctx.actor.entity_id,reason=reason,ability='',skill=None,hazards=('environmental',))
        ctx.engine._record_roll(roll)
        if roll.total<p['dc']:run_effects(ctx,[damage,*consequences])
        else:run_effects(replace(ctx,damage_divisor=2),[damage])
    else:
        run_effects(ctx,[{'type':'save','applies_to':'self','ability':p['save'],'save_categories':p.get('save_categories',[]),'on_fail':[damage,*consequences],'on_success':[{'type':'half_damage','applies_to':'self','damage_types':[p['damage_type']]}]}])
    packets=[e for e in ctx.engine.events[start:] if e.event_type=='DAMAGE_COMMITTED' and ctx.actor.entity_id in e.target_ids and (e.payload.get('hp_damage',0)>0 or p['cost_qi']>0 and e.payload.get('temporary_hp_absorbed',0)>0)]
    from .life_state import is_deceased
    resolved_save=any(e.event_type=='SAVE_ROLLED' and ctx.actor.entity_id in (e.actor_id,*e.target_ids) for e in ctx.engine.events[start:])
    # Passing a real harmful save still qualifies. A free, fully buffered
    # exposure cannot use its own Charge to replenish the entire paid price.
    full_buffer_loop=p['cost_qi']==0 and not consequences and buffer_before>=p['dice']['count']*p['dice']['sides']
    if p['genuine_threat'] and (packets or resolved_save) and not full_buffer_loop and not is_deceased(ctx.actor):
        collect(ctx,ctx.actor,'exposure:'+ctx.intent.intent_id,p,great=event_reduced_above_half_to_zero(ctx.actor,packets))


@hook('save_final')
def save_calamity(ctx,subject,ability,named,failed):
    from ..effect_harm import classify_effect
    from ..area_recipient_rules import is_martial
    supernatural=bool(ctx.typed.get('sphere') and not is_martial(ctx.typed) or str(ctx.typed.get('source','')).startswith(('tianxia.path.qi_cultivation.','tianxia.subpath.qi.')))
    harmful=classify_effect(ctx.save_effect or {},saving_throw=True) is True
    if owned(ctx.engine,subject) and relation(ctx.engine,subject,ctx.actor)==ENEMY and (named or supernatural and harmful):
        d=state(ctx.engine,subject)
        d['qualified_save_intents']=[ctx.intent.intent_id]
        store(ctx.engine,subject,d)


@hook('resolution_final')
def settled_calamity(engine,actor,action,candidate,intent):
    from ..typed_executor import Context
    from .ability_source import numbers_of
    from .life_state import is_deceased
    if action.parameters.get('calamity_profile'):return
    typed=action.parameters.get('typed') or {'source':action.source_definition_id,'numbers':numbers_of(engine,actor)}
    ctx=Context(engine,actor,action,intent,typed,[],None,{})
    events=[e for e in engine.events if e.trigger_or_intent_id==intent.intent_id and e.actor_id==actor.entity_id and e.source_definition_id==action.source_definition_id]
    for target in engine.state.actors.values():
        if not owned(engine,target) or is_deceased(target):continue
        d=state(engine,target)
        if intent.intent_id in d.get('completed_attack_intents',[]) or intent.intent_id in d.get('completed_zone_intents',[]):continue
        packets=[e for e in events if e.event_type=='DAMAGE_COMMITTED' and target.entity_id in e.target_ids and int(e.payload.get('hp_damage',0))+int(e.payload.get('temporary_hp_absorbed',0))>0]
        conditions=[e for e in events if e.event_type=='CONDITION_APPLIED' and target.entity_id in e.target_ids and str(e.payload.get('condition_id','')).split('.')[-1] in ('charmed','frightened','grappled','poisoned','prone','restrained','stunned')]
        # Movement receipts name the moved creature as actor, unlike damage
        # receipts. Read the completed route, not an attempted/blocked push or
        # each forced step, and retain the action's one-event collection fence.
        moved=any(e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==target.entity_id
                  and e.trigger_or_intent_id==intent.intent_id
                  and e.source_definition_id==action.source_definition_id
                  and e.payload.get('forced') and len(e.payload.get('path',[]))>1
                  and any(point!=e.payload['path'][0] for point in e.payload['path'][1:])
                  for e in engine.events)
        if packets or conditions or moved or intent.intent_id in d.get('qualified_save_intents',[]):
            great=event_reduced_above_half_to_zero(target,packets)
            collect(ctx,target,'intent:'+intent.intent_id,great=great,damage_types=[e.payload.get('damage_type') for e in packets])


def observe_calamities(engine,actor,source):
    """Commit broad perceived facts from actual source profiles, without an Action."""
    row=owned(engine,actor)
    if not row or NAMES[0] not in row['features']:return
    from ..gate2_runtime_models import Position
    from ..senses import perceives_cell
    from ..combat_world_facts import clock as world_clock
    d=state(engine,actor)
    for action in engine.action_catalog.values():
        p=action.parameters.get('calamity_profile')
        if not p or p.get('expires_at',2592000)<=world_clock(engine):continue
        pos=Position.model_validate(p['position'])
        if engine.grid.distance_ft(actor.position,pos)<=60 and perceives_cell(engine,actor,pos) and p['receipt_id'] not in d.get('sensed',[]):
            d.setdefault('sensed',[]).append(p['receipt_id'])
            text=f"{p['name']}: {p['type']}, {p['status']}, Source CL {p['source_cl']}; {'surviving it can grant a Calamity Charge' if p['genuine_threat'] else 'this is not a qualifying Calamity Charge source'}."
            d.setdefault('sense_readings',{})[p['receipt_id']]={'kind':'declaration','viewer_id':actor.entity_id,'authority_actor_id':actor.entity_id,'source_id':source,'details':{'text':text}}
            store(engine,actor,d)
            engine._append_event('PASSIVE_TRIGGERED',F+NAMES[0],actor_id=actor.entity_id,payload={'text':actor.display_name+' receives a private Calamity Sense reading.'})


@effect('vessel_sense',harmful=False)
def sense(ctx,effect):observe_calamities(ctx.engine,ctx.actor,ctx.source)


@hook('match_start',priority=1000)
def observe_on_entry(engine):
    for actor in engine.state.actors.values():observe_calamities(engine,actor,F+NAMES[0])


# Benefit options are source data. Every option remains a controller decision.
NORMAL={'damage':'Add 1d8 associated damage to one damage roll','temp':'Gain Temporary Hit Points equal to twice Proficiency Bonus','move':'Move 10 feet without provoking Opportunity Attacks','force':'Add 10 feet to one forced movement','armament':'Move your Domain Armament 20 feet','check':'Add Proficiency Bonus to one Cultivation Check in this activation'}
TEMPER={'Flame':{'fire':'Add 1d8 Fire damage to one damaged target','fire_resist':'Resistance to Fire until your next turn starts'},'Frost':{'slow':'Reduce one damaged target’s Speed by 15 feet until your next turn starts','cold_resist':'Resistance to Cold until your next turn starts'},'Lightning':{'reactions':'One damaged target cannot take Reactions until its next turn starts','move15':'Move 15 feet without provoking Opportunity Attacks'},'Storm':{'storm_move':'Push or pull one affected creature 15 feet','fly':'Fly Speed 30 feet until this turn ends'},'Force':{'ac':'Gain +2 AC until your next turn starts','penetrate':'Ignore Resistance to Force for one damage roll'},'Gravity':{'root':'Prevent forced movement and Prone until your next turn starts','force15':'Add 15 feet to one forced movement'},'Blood':{'blood_temp':'Gain Temporary Hit Points equal to three times Proficiency Bonus','blood_heal':'Reduce one damaged target’s first healing by twice Proficiency Bonus before your next turn starts'},'Shadow':{'obscured':'Become Lightly Obscured until your next turn starts','see_shadow':'Invisible cannot conceal one damaged target from you until your next turn starts'},'Spirit':{'spirit_guard':'Advantage against Charmed, Frightened, possession and soul displacement until your next turn starts','concentration':'One damaged target has Disadvantage on its next Concentration save before your next turn starts'},'General':{'temp':'Gain Temporary Hit Points equal to twice Proficiency Bonus','move':'Move 10 feet without provoking Opportunity Attacks','force_damage':'Add 1d8 Force damage','force':'Add 10 feet to forced movement'}}


def rule_condition(ctx,subject,key,rule,expiry='START_OF_SOURCE_NEXT_TURN',source=None):
    until=(f'until {ctx.actor.display_name}’s next turn starts' if expiry=='START_OF_SOURCE_NEXT_TURN'
           else 'until this turn ends' if expiry=='END_OF_CURRENT_TURN' else 'until removed')
    descriptions={
        'fire_resist':'Resistance to Fire damage',
        'cold_resist':'Resistance to Cold damage',
        'flight':'Fly Speed 30 feet',
        'root':'Cannot be forcibly moved or knocked Prone',
        'obscured':'Lightly Obscured',
        'spirit_guard':'Advantage on saves against Charmed, Frightened, possession, and soul displacement',
        'healing':f'The next healing received is reduced by {rule.get("vessel_heal_minus",0)} Hit Points',
        'concentration':'Disadvantage on the next Concentration saving throw',
        'seen':f'Invisible cannot conceal this creature from {ctx.actor.display_name}',
        'no_heal':'Cannot regain Hit Points',
        'reveal':'Cannot benefit from Invisible or ordinary concealment',
        'escape_advantage':'Advantage on escape checks and saving throws against the binding',
    }
    label=descriptions[key]+' '+until
    ctx.engine._apply_condition(subject,'condition:typed.concentration_mode' if key=='concentration' else 'condition:typed.vessel_'+key,source or ctx.source,ctx.actor.entity_id,expires_on=expiry,data={'rule':rule,'label':label,'description':label,'vessel_required_cl':LEVELS[NAMES.index((source or ctx.source)[len(F):])] if (source or ctx.source) in {F+n for n in NAMES} else LEVELS[NAMES.index(ctx.typed['source'][len(F):])] if ctx.typed.get('source') in {F+n for n in NAMES} else 0})


def movement(ctx,feet):
    from .granted_movement import choices,move
    rows=choices(ctx.engine,ctx.actor,feet)
    ids=[str(i) for i in range(len(rows))]
    answer=choose(ctx,ctx.actor,'move_'+str(feet),ids,{str(i):f'Move to ({c.destination.x}, {c.destination.y}) without provoking' for i,c in enumerate(rows)},f'{ctx.actor.display_name}: move up to {feet} feet without provoking, or stay.',minimum=0,decline=True) if rows else []
    if answer:move(ctx.engine,ctx.actor,rows[int(answer[0])],ctx.intent,feet,list(ctx.engine.state.actors),name='Spend Calamity')


def benefit(ctx,key,kind,target=None,*,feature=None):
    from ..typed_executor import run_effects
    me=ctx.actor;pb=int(owned(ctx.engine,me)['pb'])
    grant=ctx.with_source(feature or F+NAMES[1])
    sub=replace(grant,target=target,targets=[target] if target else [me])
    if key in ('temp','blood_temp'):ctx.engine._grant_temp_hp(me,pb*(3 if key=='blood_temp' else 2),ctx.source,me.entity_id)
    elif key in ('move','move15'):movement(ctx,15 if key=='move15' else 10)
    elif key in ('fire_resist','cold_resist'):rule_condition(grant,me,key,{'damage_resistances':['FIRE' if key=='fire_resist' else 'COLD']})
    elif key=='ac':run_effects(replace(grant,target=me,targets=[me]),[{'type':'ac_bonus','applies_to':'self','flat':2,'expires_on':'START_OF_SELF_NEXT_TURN'}])
    elif key=='fly':rule_condition(grant,me,'flight',{'fly_speed_ft':30},'END_OF_CURRENT_TURN')
    elif key=='root':rule_condition(grant,me,'root',{'vessel_root':1})
    elif key=='obscured':rule_condition(grant,me,'obscured',{'lightly_obscured':True})
    elif key=='spirit_guard':rule_condition(grant,me,key,{'vessel_spirit_guard':1})
    elif key in ('damage','fire','force_damage') and target:
        kinds=['fire'] if key=='fire' else ['force'] if key=='force_damage' else state(ctx.engine,ctx.actor).get('pending',{}).get('damage_types',DAMAGE[kind])
        run_effects(sub,[{'type':'extra_damage','applies_to':'target','dice':{'count':1,'sides':8},'damage_types':kinds}])
    elif key=='slow' and target:run_effects(sub,[{'type':'speed','applies_to':'target','flat':-15,'expires_on':'START_OF_SOURCE_NEXT_TURN'}])
    elif key=='reactions' and target:run_effects(sub,[{'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}])
    elif key=='storm_move' and target:
        from .general_combat_riders import directed_forced_movement
        directed_forced_movement(sub,{'type':'forced_movement','distance_ft':15,'relative_directions':['away','toward']})
    elif key=='blood_heal' and target:rule_condition(grant,target,'healing',{'vessel_heal_minus':pb*2},source=F+NAMES[1])
    elif key=='concentration' and target:rule_condition(grant,target,'concentration',{'concentration_mode':'DISADVANTAGE','next':True})
    elif key=='see_shadow' and target:rule_condition(grant,target,'seen',{'vessel_seen_by':me.entity_id})
    elif key=='armament':
        from .qi_path import armament_condition,armament_point,armament_control_range,move_armament
        from ..gate2_runtime_models import Position
        if not armament_condition(me):return
        old=armament_point(me)
        occupied={cell for other in ctx.engine.state.actors.values() if other.active for cell in ctx.engine._actor_cells(other)}
        points=[Position(x=x,y=y) for x in range(ctx.engine.grid.width) for y in range(ctx.engine.grid.height) if ctx.engine.grid.distance_ft(old,(x,y))<=20 and ctx.engine.grid.distance_ft(me.position,(x,y))<=armament_control_range(ctx.engine,me) and (x,y)!=old and ctx.engine.grid.placement_legal((x,y),occupied_cells=occupied) and ctx.engine.grid.line_of_sight(Position(x=old[0],y=old[1]),Position(x=x,y=y))]
        ids=[str(i) for i in range(len(points))]
        answer=choose(ctx,me,'armament',ids,{str(i):f'Move Domain Armament to ({p.x}, {p.y})' for i,p in enumerate(points)},'Move your Domain Armament up to 20 feet.',minimum=0,decline=True)
        if answer:move_armament(ctx.engine,me,points[int(answer[0])],ctx.source,distance_ft=20,require_clear_route=True)


@hook('before_target_reactions')
def spend(ctx):
    row=owned(ctx.engine,ctx.actor)
    if not row or NAMES[0] not in row['features'] or ctx.action.parameters.get('calamity_profile') or ctx.action.parameters.get('vessel_operation')==NAMES[0]:return
    d=state(ctx.engine,ctx.actor)
    if not d['charges'] or d.get('spent_turn')==stamp(ctx.engine):return
    # Native Qi costs and explicit Cultivation Attack metadata are authority;
    # damage type, technique name or narration never creates that category.
    from .qi_path import is_qi_powered_activation
    if not is_qi_powered_activation(ctx.action) and not any(pool==QI and cost>0 for pool,cost in ctx.action.costs) and not cultivation_attack(ctx.typed.get('effects',[])) and not str(ctx.typed.get('source','')).startswith(('tianxia.path.qi_cultivation.','tianxia.subpath.qi.')):return
    ids=[c['id'] for c in d['charges']]
    selected=choose(ctx,ctx.actor,'spend',ids,{c['id']:f"Spend one {c['type']} Charge" for c in d['charges']},'Spend Calamity: one Charge, once per turn. It is spent even on a miss or successful save.',minimum=0,decline=True)
    if not selected:return
    charge=next(c for c in d['charges'] if c['id']==selected[0])
    normals={k:v for k,v in ({**NORMAL,**TEMPER[charge['type']]} if walking(d) else NORMAL).items() if k!='damage' or charge.get('damage_types')}
    normal=choose(ctx,ctx.actor,'normal',list(normals),normals,'Choose the first of two different normal or typed Calamity benefits.' if walking(d) else 'Choose the normal Spend Calamity benefit. Classify an unknown damage association before choosing damage.')[0]
    benefits=[normal]
    if walking(d):
        opts={**NORMAL,**TEMPER[charge['type']]};opts.pop(normal,None)
        if not charge.get('damage_types'):opts.pop('damage',None)
        benefits+=choose(ctx,ctx.actor,'walking_benefit',list(opts),opts,'Walking Tribulation: choose a different second normal or typed benefit.')
    elif NAMES[1] in row['features'] and row['cl']>=6:
        opts=TEMPER[charge['type']]
        benefits+=choose(ctx,ctx.actor,'tempered',list(opts),opts,f"Calamity Tempering: choose the additional {charge['type']} benefit.")
    d['charges']=[c for c in d['charges'] if c['id']!=charge['id']];d['spent_turn']=stamp(ctx.engine)
    from ..paid_relocation import capture,preserve_pending
    preserve_pending(ctx.engine,'_vessel_spend_owners')
    owners=dict(getattr(ctx.engine,'_vessel_spend_owners',{}) or {});owners[ctx.actor.entity_id]=capture(ctx.engine);ctx.engine._vessel_spend_owners=owners
    d['pending']={'intent':ctx.intent.intent_id,'action':ctx.action.source_definition_id,'feature':ctx.typed.get('source'),'kind':charge['type'],'damage_types':charge.get('damage_types',DAMAGE[charge['type']]),'benefits':benefits,'done':[]}
    store(ctx.engine,ctx.actor,d)
    immediate={'temp','blood_temp','move','move15','fire_resist','cold_resist','ac','fly','root','obscured','spirit_guard','armament'}
    for key in benefits:
        if key in immediate:benefit(ctx,key,charge['type'])


@hook('damage_dealt')
def spent_damage(ctx,target,amount):
    if not owned(ctx.engine,ctx.actor) or amount<=0:return
    d=state(ctx.engine,ctx.actor);p=d.get('pending',{})
    if not pending_matches(ctx,p):return
    eligible={'fire','slow','reactions','blood_heal','concentration','see_shadow'}
    keys=[x for x in p['benefits'] if x in eligible and x not in p['done']]
    if not keys:return
    selected=choose(ctx,ctx.actor,'damaged_benefits_'+target.entity_id,keys,{key:(NORMAL.get(key) or TEMPER[p['kind']].get(key) or key) for key in keys},f'Apply spent Calamity benefits to {target.display_name}, or retain them for another damage roll in this activation.',minimum=0,maximum=len(keys),decline=True)
    if not selected:return
    p['done']+=selected;store(ctx.engine,ctx.actor,d) # fence recursive extra damage
    for key in selected:benefit(ctx,key,p['kind'],target)


@hook('effect_resolution_scope')
def spent_affected(ctx,effect):
    """Storm Tempering follows actual effects, including zero-damage packets.

    The existing scope runs after native eligibility and prevention. Consume
    only settled mutation receipts from this packet, never a nominal target
    roster or a save whose successful branch does nothing. Nested packets are
    fenced by the same pending benefit before its own movement is delivered.
    """
    if not owned(ctx.engine,ctx.actor):return
    p=state(ctx.engine,ctx.actor).get('pending',{})
    if not pending_matches(ctx,p) or 'storm_move' not in p.get('benefits',[]) or 'storm_move' in p.get('done',[]):return
    @contextmanager
    def scope():
        first=len(ctx.engine.events)
        yield
        d=state(ctx.engine,ctx.actor);pending=d.get('pending',{})
        if not pending_matches(ctx,pending) or 'storm_move' in pending.get('done',[]):return
        affected=set()
        for event in ctx.engine.events[first:]:
            if event.source_definition_id not in (ctx.source,ctx.damage_source):continue
            if event.event_type in ('DAMAGE_COMMITTED','CONDITION_APPLIED','CONDITION_UPDATED','CONDITION_REMOVED',
                                    'MODIFIER_APPLIED','MODIFIER_REMOVED','HEALING_APPLIED','TEMP_HP_GRANTED'):
                affected.update(event.target_ids)
            elif event.event_type in ('RESOURCE_GAINED','RESOURCE_SPENT','RESOURCE_MAXIMUM_CHANGED'):
                affected.add(event.actor_id)
            elif event.event_type=='MOVEMENT_COMMITTED' and len(event.payload.get('path',[]))>1:
                affected.add(event.actor_id)
        targets=[a for a in ctx.engine.state.actors.values() if a.entity_id in affected and a.active]
        if not targets:return
        from ..target_knowledge import knowledge
        known=[a.entity_id for a in targets
               if (observed:=knowledge(ctx.engine,ctx.actor,a)) is not None and observed.mode=='DIRECT']
        selected=choose(ctx,ctx.actor,'storm_affected_'+str(first),[a.entity_id for a in targets],
                        {a.entity_id:f'Push or pull {a.display_name} 15 feet' for a in targets},
                        f'Calamity Tempering after {ctx.action.display_name}: push or pull one affected creature 15 feet, or retain the benefit for another effect in this activation.',
                        minimum=0,decline=True,automatic=known)
        if not selected:return
        pending['done'].append('storm_move');store(ctx.engine,ctx.actor,d)
        benefit(ctx,'storm_move',pending['kind'],ctx.engine.state.actors[selected[0]])
    return scope()


@hook('forced_movement_bonus')
def spent_forced(ctx,subject,effect):
    if not owned(ctx.engine,ctx.actor):return
    d=state(ctx.engine,ctx.actor);p=d.get('pending',{})
    if not pending_matches(ctx,p) or p.get('force_target') not in (None,subject.entity_id):return
    # Pure query: one chosen movement is sealed by the first native delivery.
    return sum(15 if x=='force15' else 10 for x in p.get('benefits',[]) if x in ('force','force15') and x not in p.get('done',[])) or None


@hook('d20_bonus')
def cultivation_bonus(engine,roll,intent):
    actor=engine.state.actors.get(roll.actor_id)
    if not actor or not owned(engine,actor) or intent is None:return
    rc=engine.d20_context(roll)
    if not rc or rc.get('kind')!='check' or rc.get('check_kind')!='cultivation':return
    d=state(engine,actor);p=d.get('pending',{})
    if p.get('intent')==intent.intent_id and rc.get('source_id') in (p.get('action'),p.get('feature')) and 'check' in p.get('benefits',[]) and 'check' not in p['done']:
        ctx=context(engine,actor,p.get('feature'))
        if not ctx or not pending_matches(ctx,p):return
        selected=choose(ctx,actor,'cultivation_check_'+roll.roll_id,['bonus'],{'bonus':'Add your Proficiency Bonus to this Cultivation Check'},'Spend Calamity: apply the chosen bonus to this check, or retain it for another check in this activation.',minimum=0,decline=True)
        if selected:
            p['done'].append('check');store(engine,actor,d)
            return {'source_id':F+NAMES[0],'bonus':int(owned(engine,actor)['pb']),'user_id':actor.entity_id}
    recorded=d.get('scar_check')
    if recorded:
        ctx=context(engine,actor,F+NAMES[3])
        from ..fact_consent_admission import admit_choice
        fact=admit_choice(ctx,actor,F+NAMES[3],'similar_effect',str(rc.get('source_id')),['similar'],labels={'similar':'This Cultivation Check resists or overcomes a similar effect'},prompt='Scar of Authority: does this check resist or overcome an effect similar to '+recorded['name']+'?',expires_on='END_OF_CURRENT_TURN',automatic_options=['similar'] if rc.get('source_id')==recorded['technique'] else [])
        if fact:
            d.pop('scar_check');store(engine,actor,d)
            return {'source_id':F+NAMES[3],'bonus':min(5,recorded['source_cl']-int(owned(engine,actor)['cl'])),'user_id':actor.entity_id}


@hook('resistance_ignored')
def spent_penetration(engine,kind,typed,source_actor_id,target):
    actor=engine.state.actors.get(source_actor_id)
    if not actor or not owned(engine,actor):return
    p=state(engine,actor).get('pending',{})
    active=getattr(engine,'_active_intent',None)
    if kind.lower()=='force' and p.get('penetrate_current') and active is not None and p.get('intent')==active.intent_id:
        from ..paid_relocation import capture
        original=(getattr(engine,'_vessel_spend_owners',{}) or {}).get(actor.entity_id)
        current=capture(engine)
        if original is not None and current is not None and original==current:return True
    scar=state(engine,actor).get('scar_release')
    if scar and (typed or {}).get('source')==F+NAMES[2] and kind.lower() in state(engine,actor).get('scar_release_damage',[]):return True


def rider(ctx,kind,target):
    from ..typed_executor import run_effects
    sub=replace(ctx,target=target,targets=[target]);until='START_OF_SOURCE_NEXT_TURN'
    if kind=='General':
        opts={'push':'Push 10 feet','pull':'Pull 10 feet','prone':'Knock Prone','reactions':'No Reactions until your next turn starts'}
        selected=choose(ctx,ctx.actor,'general_rider_'+target.entity_id,list(opts),opts,f'Choose a General Calamity rider for {target.display_name}.')[0]
        if selected in ('push','pull'):
            from .general_combat_riders import directed_forced_movement
            directed_forced_movement(sub,{'distance_ft':10,'relative_directions':['away' if selected=='push' else 'toward']})
        elif selected=='prone':run_effects(sub,[{'type':'condition','condition':'prone','applies_to':'target'}])
        else:run_effects(sub,[{'type':'reaction_denied','applies_to':'target','expires_on':until}])
    elif kind=='Flame':rule_condition(ctx,target,'no_heal',{'healing_denied':True})
    elif kind=='Frost':run_effects(sub,[{'type':'speed','flat':-15,'applies_to':'target','expires_on':until}])
    elif kind=='Lightning':run_effects(sub,[{'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}])
    elif kind=='Storm':benefit(ctx,'storm_move',kind,target,feature=ctx.typed.get('source'))
    elif kind=='Force':run_effects(sub,[{'type':'condition','condition':'prone','applies_to':'target'}])
    elif kind=='Gravity':run_effects(sub,[{'type':'speed','becomes':0,'applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}])
    elif kind=='Blood':rule_condition(ctx,target,'healing',{'vessel_heal_minus':3*int(ctx.numbers['pb'])})
    elif kind=='Shadow':rule_condition(ctx,target,'reveal',{'vessel_reveal':1})
    elif kind=='Spirit':benefit(ctx,'concentration',kind,target,feature=ctx.typed.get('source'))


@effect('vessel_release')
def release(ctx,effect):
    from ..typed_executor import run_effects
    d=state(ctx.engine,ctx.actor);row=owned(ctx.engine,ctx.actor)
    ids=[c['id'] for c in d['charges']]
    require(ids,'Tribulation Release requires genuine Calamity Charges.')
    selected=choose(ctx,ctx.actor,'release_charges',ids,{c['id']:f"{c['type']} Charge" for c in d['charges']},f"Tribulation Release: costs 3 Qi (0 Qi once per turn during Walking Tribulation); spend 1 to {row['pb']} Charges.",maximum=min(row['pb'],len(ids)),automatic=[c['id'] for c in sorted(d['charges'],key=lambda c:not bool(c.get('damage_types')))])
    charges=[c for c in d['charges'] if c['id'] in selected]
    if not any(c.get('damage_types') for c in charges):
        classify_charge(ctx,{'charge_ids':selected})
        d=state(ctx.engine,ctx.actor);charges=[c for c in d['charges'] if c['id'] in selected]
    kinds=sorted({c['type'] for c in charges});damage=sorted({k for c in charges for k in c.get('damage_types',[])})
    require(damage,'Identify an actual damage type associated with one selected Charge before activating Tribulation Release.')
    damage_types=choose(ctx,ctx.actor,'release_damage',damage,{k:k.capitalize() for k in damage},'Choose one represented damage type, or divide the damage between two represented types.',maximum=min(2,len(damage)))
    ability=choose(ctx,ctx.actor,'release_save',['dex','con'],{'dex':'Dexterity saving throw','con':'Constitution saving throw'},'Choose the Tribulation Release saving throw.')[0]
    if walking(d) and d.get('free_release')!=stamp(ctx.engine):d['free_release']=stamp(ctx.engine)
    d['charges']=[c for c in d['charges'] if c['id'] not in selected]
    store(ctx.engine,ctx.actor,d)
    # Choose creatures from the already legal native area; never widen it.
    from ..target_knowledge import located as can_perceive
    ids=[t.entity_id for t in ctx.targets]
    selected_targets=choose(ctx,ctx.actor,'release_targets',ids,{t.entity_id:t.display_name if can_perceive(ctx.engine,ctx.actor,t) else 'Unseen creature in the area' for t in ctx.targets},'Choose creatures affected by the 30-foot Tribulation Release.',minimum=0,maximum=len(ids),automatic=[t.entity_id for t in ctx.targets if relation(ctx.engine,t,ctx.actor)==ENEMY and can_perceive(ctx.engine,ctx.actor,t)]) if ids else []
    for target in [t for t in ctx.targets if t.entity_id in selected_targets]:
        sub=replace(ctx,target=target,targets=[target])
        payload={'type':'vessel_release_damage','count':2+2*len(charges),'damage_types':damage_types,'kinds':kinds}
        run_effects(sub,[{'type':'save','ability':ability,'on_fail':[{**payload,'failed':1}],'on_success':[{**payload,'failed':0}]}])


@effect('vessel_release_damage')
def release_damage(ctx,effect):
    from ..typed_executor import run_effects
    failed=effect['failed'];d=state(ctx.engine,ctx.actor)
    if not failed and walking(d) and not d.get('twice'):
        answer=choose(ctx,ctx.actor,'strikes_twice_'+ctx.target.entity_id,['repeat'],{'repeat':'Force a second saving throw; the new result replaces the success'},f'Heaven Strikes Twice: force {ctx.target.display_name} to repeat the successful save?',minimum=0,decline=True)
        if answer:
            d['twice']=1;store(ctx.engine,ctx.actor,d)
            # The same declared ability is retained; the packet contains the
            # selected activation save, not a luck reroll or mutable global.
            ability=(ctx.origin_save or {}).get('ability','dex')
            run_effects(ctx,[{'type':'save','ability':ability,'on_fail':[{**effect,'failed':1}],'on_success':[{**effect,'failed':0}]}]);return
    from ..gate2_runtime_models import DiceSpec
    cache=ctx.damage_cache
    if 'vessel_release_total' not in cache:
        roll=ctx.engine.roller.roll(DiceSpec(count=effect['count'],sides=8),actor_id=ctx.actor.entity_id,reason='Tribulation Release damage')
        ctx.engine._record_roll(roll);cache['vessel_release_total']=int(roll.total)
        if len(effect['damage_types'])==2:
            amounts=[str(i) for i in range(1,int(roll.total))]
            answer=choose(ctx,ctx.actor,'release_split',amounts,{i:f"{i} {effect['damage_types'][0]} damage; {int(roll.total)-int(i)} {effect['damage_types'][1]} damage" for i in amounts},'Divide the rolled Tribulation Release damage between the two represented types.')[0]
            cache['vessel_release_split']=int(answer)
    seal_penetration(ctx,'vessel_release_total',effect['damage_types'])
    total=cache['vessel_release_total'];split=cache.get('vessel_release_split')
    parts=[(effect['damage_types'][0],total)] if split is None else list(zip(effect['damage_types'],[split,total-split]))
    if 'vessel_release_bonuses' not in cache:
        cache['vessel_release_bonuses']=roll_spent_damage(ctx)
    for kind,value in cache['vessel_release_bonuses']:
        found=next((i for i,(k,v) in enumerate(parts) if k==kind),None)
        if found is None:parts.append((kind,value))
        else:parts[found]=(kind,parts[found][1]+value)
    if not failed:
        half=sum(value for kind,value in parts)//2
        parts=[(kind,value//2 if i<len(parts)-1 else half-sum(v//2 for k,v in parts[:-1])) for i,(kind,value) in enumerate(parts)]
    # Keep dynamic rows alive: the native shared-roll cache keys ordinary rows
    # by object identity. Recycled temporary dict ids must never reuse another
    # component's (amount,type), especially a zero first half of a split.
    signature=(bool(failed),tuple(parts))
    rows=cache.setdefault('vessel_release_rows',{}).setdefault(signature,[{'type':'damage','applies_to':'target','flat':amount,'damage_types':[kind],'resolved_damage_type':kind} for kind,amount in parts])
    run_effects(ctx,rows)
    kinds=effect['kinds']
    if not failed:
        kinds=choose(ctx,ctx.actor,'successful_rider_'+ctx.target.entity_id,kinds,{k:k+' rider' for k in kinds},f'{ctx.target.display_name} succeeded: choose at most one rider.',minimum=0,decline=True)
    for kind in kinds:rider(ctx,kind,ctx.target)


@effect('vessel_walk',harmful=False)
def transform(ctx,effect):
    d=state(ctx.engine,ctx.actor)
    require(not d.get('scene_used') and d['history'],'Walking Tribulation requires a previously survived calamity and is once per scene.')
    choices=[]
    for i in range(3):choices+=choose(ctx,ctx.actor,'overflow_'+str(i),d['history'],{k:k for k in d['history']},'Choose the type of one overflow Charge from calamities you have survived.')
    for kind in choices:
        d['sequence']+=1;d['charges'].append({'id':str(d['sequence']),'type':kind,'source_cl':owned(ctx.engine,ctx.actor)['cl'],'overflow':1,'damage_types':d.get('survived_damage_types',{}).get(kind,[]),'event':ctx.intent.intent_id})
    d.update(walking={'remaining':10},scene_used=1,twice=0)
    retain_walking_clock(ctx.engine,d['walking'])
    store(ctx.engine,ctx.actor,d)


@hook('damage_defenses')
def defenses(engine,target,kind,typed,source_actor_id):
    if not owned(engine,target) or NAMES[4] not in owned(engine,target)['features'] or not walking(state(engine,target)):return
    if kind.upper() in ('ACID','COLD','FIRE','LIGHTNING','THUNDER'):return [{'kind':'resistance','damage_types':[kind]}]
    source=engine.state.actors.get(source_actor_id)
    source_id=(typed or {}).get('source','')
    action=next((a for a in engine.action_catalog.values() if (a.parameters.get('typed') or {}).get('source')==source_id),None)
    from .damage_delivery import hazard
    environmental=bool(hazard(engine) or action and action.parameters.get('calamity_profile'))
    # Sphere identity is sealed by the compiler, including legacy TAL_* ids;
    # the label or the physical damage type is not a source classification.
    from .ability_source import is_path_or_subpath_feature
    cultivation=bool((typed or {}).get('sphere') or action and (action.parameters.get('typed') or {}).get('sphere') or is_path_or_subpath_feature(source_id) or cultivation_attack((typed or {}).get('effects',[])))
    if kind.upper() in ('BLUDGEONING','PIERCING','SLASHING') and (environmental or cultivation):return [{'kind':'resistance','damage_types':[kind]}]


@hook('turn_start_choice')
def start(engine,actor):
    observe_calamities(engine,actor,F+NAMES[0])
    for owner in engine.state.actors.values():
        if not owned(engine,owner):continue
        d=state(engine,owner)
        if walking(d):
            if retain_walking_clock(engine,d['walking'])<=0:end_walk(engine,owner,d)
            else:store(engine,owner,d)
            d=state(engine,owner)
        if walking(d) and relation(engine,actor,owner)==ENEMY and engine._distance_actor_to_actor(owner,actor)<=15:aura(engine,owner,actor)
    if not owned(engine,actor):return
    ctx=context(engine,actor)
    if ctx and 0<actor.current_hp*2<actor.maximum_hp:
        from ..fact_consent_admission import admit_choice
        from .ability_source import numbers_of
        from ..target_knowledge import located
        from ..typed_executor import condition_rules
        threats=[t for t in engine.state.actors.values() if t.active and relation(engine,t,actor)==ENEMY]
        if threats:
            known=[t.entity_id for t in threats if located(engine,actor,t) and t.current_hp>0 and not any(r.get('no_actions') for r in condition_rules(t)) and any(e.event_type=='DAMAGE_COMMITTED' and e.actor_id==t.entity_id and actor.entity_id in e.target_ids and e.payload.get('hp_damage',0)>0 for e in engine.events)]
            record=admit_choice(ctx,actor,F+NAMES[0],'hostile_danger_remains',stamp(engine),[t.entity_id for t in threats],labels={t.entity_id:t.display_name if located(engine,actor,t) else 'Unseen potential danger' for t in threats},prompt='Below half your Hit Points: identify a genuine hostile danger that still remains, or decline.',expires_on='END_OF_CURRENT_TURN',automatic_options=known)
            if record:
                threat=engine.state.actors[record['value']]
                collect(replace(ctx,typed={**ctx.typed,'numbers':numbers_of(engine,threat)}),actor,'below_half:'+stamp(engine),damage_types=[e.payload.get('damage_type') for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==threat.entity_id and actor.entity_id in e.target_ids])


@hook('movement_step')
@hook('forced_movement_step')
def aura_entry(engine,actor,previous,nxt,intent):
    observe_calamities(engine,actor,F+NAMES[0])
    for owner in engine.state.actors.values():
        if owner is actor or relation(engine,owner,actor)!=ENEMY or not owned(engine,owner):continue
        if walking(state(engine,owner)) and engine.grid.distance_ft(previous,owner.position)>15 and engine.grid.distance_ft(nxt,owner.position)<=15:aura(engine,owner,actor)


def aura(engine,owner,target):
    from ..typed_executor import run_effects
    d=state(engine,owner);key='aura:'+stamp(engine)+':'+target.entity_id
    if key in d.get('aura_events',[]) or not d['charges']:return
    ctx=context(engine,owner,F+NAMES[4])
    if not ctx:return
    kinds=sorted({c['type'] for c in d['charges'] if c.get('damage_types')})
    if not kinds:
        classify_charge(ctx,{})
        d=state(engine,owner);kinds=sorted({c['type'] for c in d['charges'] if c.get('damage_types')})
        if not kinds:return
    kind=choose(ctx,owner,key,kinds,{k:k for k in kinds},f'Calamity Aura: choose a represented type against {target.display_name}.')[0]
    represented=sorted({k for c in d['charges'] if c['type']==kind for k in c.get('damage_types',DAMAGE[kind])})
    damage=choose(ctx,owner,key+':damage',represented,{k:k.capitalize() for k in represented},'Choose Calamity Aura damage type.')[0]
    d.setdefault('aura_events',[]).append(key);store(engine,owner,d)
    run_effects(replace(ctx,target=target,targets=[target]),[{'type':'save','ability':'dex','on_fail':[{'type':'damage','applies_to':'target','dice':{'count':3,'sides':8},'damage_types':[damage]},{'type':'vessel_aura_rider','kind':kind}],'on_success':[{'type':'half_damage','applies_to':'target','damage_types':[damage]}]}])


@effect('vessel_aura_rider')
def aura_rider(ctx,effect):rider(ctx,effect['kind'],ctx.target)


def end_walk(engine,actor,d):
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import run_effects
    extra=max(0,len(d['charges'])-3)
    d.pop('walking',None)
    # The transformation's defenses stop first. The printed damage precedes
    # overflow expiration; unrelated legal reactions may still spend charges.
    store(engine,actor,d)
    if extra:
        roll=engine.roller.roll(DiceSpec(count=extra,sides=8),actor_id=actor.entity_id,reason='Vessel Breaks Before the Calamity');engine._record_roll(roll)
        # This is an ordinary committed damage packet; the source-qualified
        # defense/reduction hooks expressly exclude this own feature backlash.
        engine._commit_damage(actor,int(roll.total),'FORCE',F+'vessel_breaks',actor.entity_id,getattr(engine,'_active_intent',None),reaction_depth=0)
    d=state(engine,actor)
    d['charges']=[c for c in d['charges'] if not c.get('overflow')][:maximum(owned(engine,actor))]
    store(engine,actor,d,expired=True)


def furnace_ready(engine,actor):
    row=owned(engine,actor)
    from ..typed_reactions import can_use_reaction
    policy=next((r for r in getattr(engine,'typed_reaction_rows',{}).get(actor.entity_id,[]) if r.get('block')=='tribulation_vessel_response'),None)
    if not row or NAMES[3] not in row['features'] or row['cl']<14 or policy is None or not can_use_reaction(engine,actor,None,policy):return False
    d=state(engine,actor)
    return d.get('furnace_round')!=engine.state.match_id+':'+str(engine.state.round_number) and len(d['charges'])>=(1 if walking(d) else 2)


def pay_furnace(engine,actor,*,reaction=True):
    from ..typed_reactions import spend_reaction,publish_reaction_used
    d=state(engine,actor);cost=1 if walking(d) else 2
    ctx=context(engine,actor,F+NAMES[3]);selected=[]
    for index in range(cost):
        remaining=[c for c in d['charges'] if c['id'] not in selected]
        answer=choose(ctx,actor,'furnace_charge_'+str(index),[c['id'] for c in remaining],{c['id']:('Overflow ' if c.get('overflow') else 'Normal ')+c['type']+' Charge' for c in remaining},f'Furnace Response: choose Charge {index+1} of {cost} to pay its cost.',automatic=[c['id'] for c in sorted(remaining,key=lambda c:not c.get('overflow'))])
        selected+=answer
    d['charges']=[c for c in d['charges'] if c['id'] not in selected];d['furnace_round']=engine.state.match_id+':'+str(engine.state.round_number)
    store(engine,actor,d)
    if reaction:
        row={'feature_id':F+NAMES[3],'name':'Furnace Response'}
        spend_reaction(engine,actor,row);publish_reaction_used(engine,actor,row)
    # This is a real source-qualified Qi feature activation, including off-turn
    # Furnace responses. The optional normal Charge is distinct from its cost.
    action=next((a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id and a.parameters.get('vessel_trigger_only')),None)
    if action is not None:
        from ..typed_executor import Context
        intent=getattr(engine,'_active_intent',None)
        if intent is not None:spend(Context(engine,actor,action,intent,action.parameters['typed'],[actor],actor,{}))


def scar(engine,actor,source_id,source_actor_id,damage_type=None):
    from .ability_source import numbers_of
    ctx=context(engine,actor,F+NAMES[3])
    if not ctx:return
    source=engine.state.actors.get(source_actor_id)
    action=engine.action_catalog.get(source_id)
    p=action.parameters.get('calamity_profile') if action else None
    if p:kind=p['type'];cl=p['source_cl'];name=p['name']
    else:
        answer=choose(ctx,actor,'scar_type',list(TYPES),{k:k for k in TYPES},'Scar of Authority: choose the triggering effect’s closest Calamity Type.')
        if not answer:return
        kind=answer[0];cl=int(numbers_of(engine,source).get('cl',0)) if source else 0;name=action.display_name if action else 'Observed effect'
    d=state(engine,actor);d['scar']={'type':kind,'source_cl':cl,'technique':technique_id(action) if action else source_id or '', 'name':name,'damage_types':[p['damage_type']] if p else [str(damage_type).lower()] if damage_type else []};store(engine,actor,d)



def furnace_activation(subject_index):
    def decorate(function):
        from functools import wraps
        @wraps(function)
        def run(*args,**kwargs):
            first=args[0];engine=getattr(first,'engine',first);subject=args[subject_index]
            if not furnace_ready(engine,subject):return function(*args,**kwargs)
            from ..paid_relocation import activation
            with activation(engine,subject,F+NAMES[3]):return function(*args,**kwargs)
        return run
    return decorate


@hook('source_damage_reduction')
@furnace_activation(1)
def furnace_damage(engine,target,amount,kind,source_id,source_actor_id):
    if source_id==F+'vessel_breaks' or amount<=0 or not furnace_ready(engine,target):return None
    ctx=context(engine,target,F+NAMES[3])
    if not ctx:return None
    answer=choose(ctx,target,'consume_damage',['consume'],{'consume':'Spend '+str(1 if walking(state(engine,target)) else 2)+' Charges and your Reaction: reduce this damage by 4d8 + Qi key modifier'},f'Furnace Response: Consume the Damage affecting {target.display_name}?',minimum=0,decline=True)
    if not answer:return None
    pay_furnace(engine,target)
    from ..gate2_runtime_models import DiceSpec
    roll=engine.roller.roll(DiceSpec(count=4,sides=8,modifier=int(owned(engine,target)['key_mod'])),actor_id=target.entity_id,reason='Furnace Response: Consume the Damage');engine._record_roll(roll)
    reduced=max(0,int(roll.total))
    if reduced>=amount:scar(engine,target,source_id,source_actor_id,kind)
    return reduced


@hook('forced_movement_restriction')
@furnace_activation(1)
def root(engine_ctx,subject,effect,maximum_ft):
    ctx=engine_ctx
    if any(c.condition_id=='condition:typed.vessel_root' for c in subject.conditions.values()):return 0
    if owned(ctx.engine,subject) and state(ctx.engine,subject).get('root_effect')=={'intent':ctx.intent.intent_id,'source':ctx.source,'actor':ctx.actor.entity_id}:
        if maximum_ft>0:root_reward(ctx,subject)
        return 0
    if maximum_ft<=0 or not furnace_ready(ctx.engine,subject):return
    answer=choose(ctx,subject,'root_against_heaven',['root'],{'root':'Spend Charges and your Reaction: prevent this forced movement and its Prone'},f'Furnace Response: Root Against Heaven for {subject.display_name}?',minimum=0,decline=True)
    if not answer:return
    pay_furnace(ctx.engine,subject)
    d=state(ctx.engine,subject);d['root_effect']={'intent':ctx.intent.intent_id,'source':ctx.source,'actor':ctx.actor.entity_id};store(ctx.engine,subject,d)
    current_prone={e.payload.get('instance_id') for e in ctx.engine.events if e.event_type=='CONDITION_APPLIED' and e.trigger_or_intent_id==ctx.intent.intent_id and e.source_definition_id==ctx.source and subject.entity_id in e.target_ids and e.payload.get('condition_id')=='condition:typed.prone'}
    for iid in current_prone:
        if iid in subject.conditions:remove_instance(ctx.engine,subject,iid,F+NAMES[3])
    root_reward(ctx,subject)
    return 0


@hook('condition_attempt')
def prevent_prone(ctx,subject,effect):
    if str(effect.get('condition','')).lower()!='prone' or not owned(ctx.engine,subject):return
    if any(c.condition_id=='condition:typed.vessel_root' for c in subject.conditions.values()) or state(ctx.engine,subject).get('root_effect')=={'intent':ctx.intent.intent_id,'source':ctx.source,'actor':ctx.actor.entity_id}:return False


@hook('condition_applied')
@furnace_activation(2)
def burn_binding(ctx,name,subject):
    if name not in ('grappled','restrained') or not furnace_ready(ctx.engine,subject):return
    from ..ability_checks import ability_modifier,skill_bonus
    from .escape_options import options,attempt
    conditions=[c for c in subject.conditions.values() if c.condition_id=='condition:typed.'+name and c.source_definition_id==ctx.source and c.source_actor_id==ctx.actor.entity_id]
    if not conditions:return
    existing=next((c.data.get('repeat_save') for c in conditions if c.data.get('repeat_save')),None)
    explicit=[(key,record) for key,record in options(subject) if set(record.data.get('guards',[]))&{c.instance_id for c in conditions}]
    ordinary=next((c for c in conditions if c.data.get('escape_dc')),None)
    opts={'repeat':'Repeat the original saving throw with Advantage'} if existing else {}
    from .escape_options import attempt_description
    opts.update({'escape:'+key:attempt_description(record.data,'Reaction with Advantage') for key,record in explicit})
    if ordinary:opts.update({'str':'Strength (Athletics) escape with Advantage','dex':'Dexterity (Acrobatics) escape with Advantage'})
    if not opts:opts={'str':'Strength check with Advantage','dex':'Dexterity check with Advantage','cultivation':'Cultivation Check with Advantage'}
    answer=choose(ctx,subject,'burn_binding',list(opts),opts,f'Furnace Response: spend Charges and your Reaction to escape {name} with Advantage?',minimum=0,decline=True)
    if not answer:return
    pay_furnace(ctx.engine,subject);selected=answer[0];row=owned(ctx.engine,subject)
    if selected.startswith('escape:'):
        chosen=next(pair for pair in explicit if 'escape:'+pair[0]==selected)
        # The existing escape-option consumer owns its exact ability/skill,
        # DC, end-on-success and dependent-hold procedure.
        rule_condition(replace(ctx,actor=subject),subject,'escape_advantage',{'check_mode':{'ALL':'ADVANTAGE'},'save_mode':{a:'ADVANTAGE' for a in ('STR','DEX','CON','INT','WIS','CHA')}},'END_OF_CURRENT_TURN')
        try:success=attempt(replace(ctx,actor=subject),subject,subject,*chosen)
        finally:
            for c in list(subject.conditions.values()):
                if c.condition_id=='condition:typed.vessel_escape_advantage':remove_instance(ctx.engine,subject,c.instance_id,F+NAMES[3])
    elif selected=='repeat':
        dc=int(existing['dc']);ability=str(existing['ability']).upper()
        roll=ctx.engine._roll_save(subject,ability,dc,F+NAMES[3],extra_mode='ADVANTAGE')
        success=roll is not None and roll.total>=dc
    else:
        dc=int(ordinary.data['escape_dc'] if ordinary else ctx.numbers.get('save_dc') or 10)
        ability=selected.upper() if selected!='cultivation' else ''
        bonus=int(row['pb'])+int(row['key_mod']) if selected=='cultivation' else ability_modifier(subject,ability,numbers=row)
        skill=('Athletics' if selected=='str' else 'Acrobatics') if ordinary else None
        if skill:bonus=skill_bonus(ctx.engine,subject,skill,bonus)
        reason='CHECK:'+F+NAMES[3]
        with ctx.engine.d20_scope({'kind':'check','check_kind':'cultivation' if selected=='cultivation' else 'check','actor_id':subject.entity_id,'source_id':F+NAMES[3],'source_actor_id':ctx.actor.entity_id,'target_id':ctx.actor.entity_id,'reason':reason,'dc':dc}):
            roll=ctx.engine.roll_check(modifier=bonus,actor_id=subject.entity_id,reason=reason,ability=ability,skill=skill,modes=('ADVANTAGE',),against_creature=ctx.actor,hazards=(name,))
        ctx.engine._record_roll(roll);success=roll.total>=dc
    if success:
        ended=[c for c in conditions if c.instance_id in subject.conditions]
        for c in ended:remove_instance(ctx.engine,subject,c.instance_id,F+NAMES[3])
        from .hold_escapes import escaped,how_for
        escaped(ctx.engine,subject,conditions,how_for(selected,subject),by=subject,source=F+NAMES[3],way='save' if existing else 'check')
        scar(ctx.engine,subject,ctx.action.source_definition_id,ctx.actor.entity_id)


def furnace_holders(engine):
    from .d20_rewrite import Holder
    for actor in engine.state.actors.values():
        if furnace_ready(engine,actor):yield Holder(actor,F+NAMES[3],{},F+NAMES[3],owned(engine,actor))


def reverse_after(engine,holder,rc,roll,bonus):
    if rc.dc is not None and int(roll.total)>=rc.dc:scar(engine,holder.actor,rc.source_id,getattr(rc.source_actor,'entity_id',None))


def reverse_guard(engine,holder,rc):
    if not furnace_ready(engine,holder.actor):return False
    if str(rc.ability).upper() in owned(engine,holder.actor).get('proficient_saves',[]):return False
    # The native save collector records accepted PB contributions explicitly;
    # a numeric modifier never establishes proficiency provenance.
    return not (engine.d20_context(rc.roll) or {}).get('proficiency_bonus_added')


def register_furnace():
    from .d20_rewrite import Rule,register
    register(Rule('vessel_reverse_save','Furnace Response: Reverse the Save',finder=furnace_holders,feature=F+NAMES[3],reaction=True,when='failed',costs_for=lambda e,h,r:((('calamity_charge',1 if walking(state(e,h.actor)) else 2),),),on_use=lambda e,h,r:pay_furnace(e,h.actor,reaction=False),additive_save_bonus=lambda e,h,r:int(h.numbers['pb']),proficiency_save_bonus=True,exclusive_proficiency_save_bonus=True,after_bonus=reverse_after,guard=reverse_guard,ai=lambda e,h,r:r.dc is not None and r.total+int(h.numbers['pb'])>=r.dc))
register_furnace()


@hook('save')
def spirit_saves(ctx,subject,ability,named):
    tags={str(tag).lower().removeprefix('category:') for tag in named or ()}
    if any(c.condition_id=='condition:typed.vessel_spirit_guard' for c in subject.conditions.values()) and tags&{'charmed','frightened','possessed','possession','soul_displaced','soul_displacement'}:return {'bonus':0,'modes':['ADVANTAGE']}


@hook('flight')
def flight(engine,actor):
    if any(c.condition_id=='condition:typed.vessel_flight' for c in actor.conditions.values()):return {'fly_speed_ft':30}


@hook('healing_pending')
def healing(engine,subject,amount,healer,source,kind):
    if kind!='hp':return None
    rows=[c for c in subject.conditions.values() if (c.data.get('rule') or {}).get('vessel_heal_minus') and amount>0]
    groups={}
    for c in rows:
        action=engine.action_catalog.get(c.source_definition_id)
        identity=(action.parameters.get('typed') or {}).get('source') if action else c.source_definition_id
        groups[identity]=max(groups.get(identity,0),int(c.data['rule']['vessel_heal_minus']))
        remove_instance(engine,subject,c.instance_id,c.source_definition_id)
    return min(amount,sum(groups.values())) if rows else None



@hook('masked_conditions')
def reveal(engine,attacker,target):
    out={}
    for who,viewer in ((attacker,target),(target,attacker)):
        if any((c.data.get('rule') or {}).get('vessel_reveal') or (c.data.get('rule') or {}).get('vessel_seen_by')==viewer.entity_id for c in who.conditions.values()):
            global_reveal=any((c.data.get('rule') or {}).get('vessel_reveal') for c in who.conditions.values())
            out[who.entity_id]={iid for iid,c in who.conditions.items() if c.condition_id in (('condition:typed.invisible','condition:typed.hidden') if global_reveal else ('condition:typed.invisible',))}
    return out or None


@hook('journey_encounter_settled')
@hook('journey_damage_settled')
def export(session,actor_id,engine,actor):
    if owned(engine,actor):
        d=state(engine,actor)
        if walking(d):retain_walking_clock(engine,d['walking'])
        session.state['actors'][actor_id].setdefault('source_states',{}).setdefault(P,{})['ledger']=d


@hook('journey_initialize')
def initialize(session,actor_id):
    # Registry already persists source_states, including genuine history, scene
    # allowance and last collection. Starting a journey never fabricates charges.
    return None


@hook('journey_rest')
def rest(session,actor_id):
    data=session.state['actors'][actor_id].get('source_states',{}).get(P)
    if not data:return
    d=data.get('ledger',{})
    for key in ('scar','scar_release','scar_release_damage','scar_check','recognize','walking','pending'):d.pop(key,None)
    d['charges']=[];data['ledger']=d;data.pop('continuing',None)
    if CHARGES in session.state['actors'][actor_id]['resources']:session.state['actors'][actor_id]['resources'][CHARGES]=0
    snapshot=session.state['actors'][actor_id].get('encounter_snapshot',{})
    for iid,raw in list(snapshot.get('conditions',{}).items()):
        c=json.loads(raw)
        if c['condition_id']==LEDGER:
            c['data']['ledger']=json.dumps(d,sort_keys=True);snapshot['conditions'][iid]=json.dumps(c,sort_keys=True)


@hook('effect_origins')
def origins(engine,actor,action):
    if action.parameters.get('vessel_operation')!=NAMES[2] or not owned(engine,actor):return None
    from .qi_path import armament_condition,armament_point
    from ..gate2_runtime_models import Position
    if walking(state(engine,actor)):
        return [{'id':f'vessel:{x}:{y}:{z}','label':f'Tribulation Release from ({x}, {y}), {z*engine.grid.square_size_ft} feet high','position':{'x':x,'y':y,'z':z}}
            for x in range(engine.grid.width) for y in range(engine.grid.height)
            for z in range(max(0,actor.position.z-30//engine.grid.square_size_ft),actor.position.z+30//engine.grid.square_size_ft+1)
            if engine.grid.distance_ft(actor.position,Position(x=x,y=y,z=z))<=30
            and engine.grid.placement_legal(Position(x=x,y=y,z=z),occupied_cells=set())]
    if armament_condition(actor):
        x,y=armament_point(actor)
        return [{'id':'vessel:armament','label':'Tribulation Release from your Domain Armament','position':{'x':x,'y':y}}]


@hook('post_hit_damage')
def native_damage(engine,attacker,target,settled_hit,intent):
    intent=intent or getattr(engine,'_active_intent',None)
    if intent is None:return
    from .life_state import is_deceased
    from .ability_source import numbers_of
    if not owned(engine,target) or is_deceased(target):return
    packets=[e for e in reversed(engine.events) if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==settled_hit.attack.source_id and target.entity_id in e.target_ids]
    if not packets or int(packets[0].payload.get('hp_damage',0))+int(packets[0].payload.get('temporary_hp_absorbed',0))<=0:return
    ctx=context(engine,attacker)
    if not ctx:return
    ctx=replace(ctx,typed={**ctx.typed,'numbers':numbers_of(engine,attacker)})
    great=target.current_hp==0 and int(packets[0].payload.get('hp_before',0))>target.maximum_hp//2
    collect(ctx,target,'attack:'+settled_hit.attack.roll_id,great=great,damage_types=[settled_hit.damage_type])
    d=state(engine,target);d['completed_attack_intents']=[intent.intent_id];store(engine,target,d)


@effect('vessel_scar',harmful=False)
def use_scar(ctx,effect):
    d=state(ctx.engine,ctx.actor);recorded=d.get('scar')
    require(recorded,'You have no Tribulation Scar before your next long rest.')
    opts={'type':'Treat one held Charge as the Scar’s recorded type','check':'Add recorded Source CL difference, up to +5, to one Cultivation Check against a similar effect','release':'One Tribulation Release ignores ordinary Resistance to the recorded damage type','recognize':'Recognize this same named technique automatically when perceived again'}
    if not d['charges']:opts.pop('type')
    mode=choose(ctx,ctx.actor,'scar_mode',list(opts),opts,'Consume your one Tribulation Scar: '+recorded['name']+'.')[0]
    if mode=='type':
        ids=[c['id'] for c in d['charges']]
        selected=choose(ctx,ctx.actor,'scar_charge',ids,{c['id']:c['type']+' Charge' for c in d['charges']},'Choose one Charge to treat as '+recorded['type']+'.')[0]
        charge=next(c for c in d['charges'] if c['id']==selected)
        charge['type']=recorded['type'];charge['damage_types']=recorded.get('damage_types',[])
        charge['association_receipt']=recorded['technique']
    elif mode=='check':d['scar_check']=recorded
    elif mode=='release':
        d['scar_release']=recorded['type'];d['scar_release_damage']=recorded.get('damage_types',[])
        if not d['scar_release_damage']:
            from ..fact_consent_admission import admit_choice
            association=admit_choice(ctx,ctx.actor,F+NAMES[3],'scar_damage_type',recorded['technique'],list(NATIVE_DAMAGE),labels={k:k.capitalize() for k in NATIVE_DAMAGE},prompt='Declare the damage type recorded by this Scar, or retain the Scar.',expires_on='END_OF_CURRENT_TURN',automatic_options=[])
            if not association:return
            d['scar_release_damage']=[association['value']]
    else:d['recognize']=recorded
    d.pop('scar');store(ctx.engine,ctx.actor,d)


@hook('before_target_reactions')
def recognition(ctx):
    from ..target_knowledge import can_see
    for owner in ctx.engine.state.actors.values():
        if not owned(ctx.engine,owner):continue
        d=state(ctx.engine,owner);recorded=d.get('recognize')
        if recorded and recorded['technique']==technique_id(ctx.action) and can_see(ctx.engine,owner,ctx.actor):
            ctx.engine._append_event('PASSIVE_TRIGGERED',F+NAMES[3],actor_id=owner.entity_id,payload={'text':owner.display_name+' recognizes '+recorded['name']+' from the Tribulation Scar.'})


@hook('condition_attempt')
@furnace_activation(1)
def root_prone(ctx,subject,effect):
    if str(effect.get('condition','')).lower()!='prone' or not furnace_ready(ctx.engine,subject):return
    answer=choose(ctx,subject,'root_prone',['root'],{'root':'Spend Charges and your Reaction to prevent being knocked Prone by this effect'},f'Furnace Response: Root Against Heaven for {subject.display_name}?',minimum=0,decline=True)
    if answer:
        pay_furnace(ctx.engine,subject)
        d=state(ctx.engine,subject);d['root_effect']={'intent':ctx.intent.intent_id,'source':ctx.source,'actor':ctx.actor.entity_id};store(ctx.engine,subject,d)
        return False


@hook('technique_used')
def spent_cleanup(ctx):
    if not owned(ctx.engine,ctx.actor):return
    d=state(ctx.engine,ctx.actor)
    if ctx.typed.get('source')==F+NAMES[2]:d.pop('scar_release',None);d.pop('scar_release_damage',None)
    # Retained benefits outlive this use. Every reader goes through pending_matches(),
    # which keys them to the intent, so a later movement in the same activation can still
    # spend what was declined here and no other intent can read them. Only the per-roll
    # Force flag closes at the end of the use.
    p=d.get('pending')
    if p and p.get('intent')==ctx.intent.intent_id:p.pop('penetrate_current',None)
    store(ctx.engine,ctx.actor,d)


def journey_store_ledger(actor,d):
    if CHARGES in actor.get('resources',{}):actor['resources'][CHARGES]=len(d.get('charges',[]))
    actor.setdefault('source_states',{}).setdefault(P,{})['ledger']=deepcopy(d)
    for iid,raw in list(actor.get('encounter_snapshot',{}).get('conditions',{}).items()):
        c=json.loads(raw)
        if c['condition_id']==LEDGER:
            c['data']['ledger']=json.dumps(d,sort_keys=True)
            actor['encounter_snapshot']['conditions'][iid]=json.dumps(c,sort_keys=True)


@hook('journey_scene_end')
def clear_scene_snapshot(session,old,new):
    for actor in session.state['actors'].values():
        data=actor.get('source_states',{}).get(P)
        if data:
            d=data.get('ledger',{});d.pop('scene_used',None);journey_store_ledger(actor,d)


@hook('journey_elapsed')
def elapsed(session,actor_id,previous,duration,moving):
    actor=session.state['actors'][actor_id];data=actor.get('source_states',{}).get(P)
    if not data:return
    d=data.get('ledger',{})
    from fractions import Fraction
    for item in data.get('continuing',[]):
        left=Fraction(item['num'],item['den'])-duration
        item.update(num=left.numerator,den=left.denominator)
    data['continuing']=[item for item in data.get('continuing',[]) if item['num']>0]
    for action in list(actor['bundle']['action_catalog']):
        p=action['parameters'].get('calamity_profile')
        if p and p['expires_at']<=session.clock():
            actor['bundle']['action_catalog'].remove(action)
            ids=actor['bundle']['actor_template']['action_ids']
            if action['source_definition_id'] in ids:ids.remove(action['source_definition_id'])
    if not walking(d):return
    remaining=int(d['walking'].get('seconds',d['walking']['remaining']*6))
    # The journey clock can contain rational subsecond travel. Store remaining
    # integer numerator/denominator so short steps never extend the minute.
    from fractions import Fraction
    remaining=(Fraction(d['walking']['deadline_num'],d['walking']['deadline_den'])-session.clock() if 'deadline_num' in d['walking'] else Fraction(d['walking'].get('remaining_num',remaining),d['walking'].get('remaining_den',1))-duration)
    if remaining>0:
        d['walking'].update(remaining_num=remaining.numerator,remaining_den=remaining.denominator,remaining=-(-remaining.numerator//(remaining.denominator*6)))
    else:
        extra=max(0,len(d['charges'])-3)
        d.pop('walking',None)
        if extra:
            from ..gate2_rolls import DeterministicRollAuthority
            from ..gate2_runtime_models import DiceSpec
            roller=DeterministicRollAuthority(session.state['journey_id']+':vessel:'+str(len(session.state['events'])))
            roll=roller.roll(DiceSpec(count=extra,sides=8),actor_id=actor_id,reason='Vessel Breaks Before the Calamity')
            journey_store_ledger(actor,d)
            session.emit('CALAMITY_BACKLASH_ROLLED',actor_id,roll=roll.model_dump(mode='json'),damage_type='FORCE')
            session.apply_damage(actor_id,int(roll.total),'FORCE',F+'vessel_breaks',actor_id)
            d=deepcopy(data.get('ledger',d))
        marker=next(r for r in actor['bundle']['typed_passives'] if r.get('block')=='tribulation_vessel')
        d['charges']=[c for c in d['charges'] if not c.get('overflow')][:maximum(marker)]
    journey_store_ledger(actor,d)


@hook('technique_cost_discount')
def walking_release_cost(engine,actor,source_id,cost_totals):
    action=engine.action_catalog.get(source_id)
    if not action or action.parameters.get('vessel_operation')!=NAMES[2] or not owned(engine,actor):return None
    d=state(engine,actor)
    if walking(d) and d.get('free_release')!=stamp(engine):return {QI:3}


@hook('obscurement_ignored')
def shadow_concealment(engine,zone,viewer,seen):
    from .darkness_scope import scope
    if scope(engine,zone)=='ordinary' and any(c.condition_id=='condition:typed.vessel_reveal' for c in seen.conditions.values()):return True


@hook('ability_check_hazard_mode')
def light_obscurement(engine,actor,ability,skill,against_creature,hazards):
    if (against_creature is not None and str(skill).lower()=='perception'
            and set(hazards)&{'visual_concealment','sight','visual'}
            and any(c.condition_id=='condition:typed.vessel_obscured' for c in against_creature.conditions.values())):return 'DISADVANTAGE'


@hook('forced_movement_distance')
def spend_one_movement(ctx,subject,effect,maximum_ft):
    if not owned(ctx.engine,ctx.actor):return
    d=state(ctx.engine,ctx.actor);p=d.get('pending',{})
    if not pending_matches(ctx,p):return
    keys=[key for key in p.get('benefits',[]) if key in ('force','force15') and key not in p.get('done',[])]
    if not keys:return
    selected=choose(ctx,ctx.actor,'forced_benefits_'+subject.entity_id,keys,{key:'Increase this forced movement by '+str(15 if key=='force15' else 10)+' feet' for key in keys},f'Apply Calamity movement benefits to {subject.display_name}, or retain them for another forced movement in this activation.',minimum=0,maximum=len(keys),decline=True)
    p['done']+=selected;store(ctx.engine,ctx.actor,d)
    return maximum_ft-sum(15 if key=='force15' else 10 for key in keys if key not in selected)


@hook('teleport_settled')
def aura_teleport(ctx,subject,previous,destination,unwilling):
    aura_entry(ctx.engine,subject,previous,destination,ctx.intent)


def cultivation_attack(rows):
    """Actual typed attack category; never infer it from names or damage."""
    if not isinstance(rows,list):return False
    for row in rows:
        if not isinstance(row,dict):continue
        if row.get('type')=='attack' and str(row.get('attack_kind','')).startswith('cultivation'):return True
        if any(cultivation_attack(row.get(key,[])) for key in ('effects','on_hit','on_fail','on_success')):return True
    return False


def genuine(ctx,target):
    """Admit subjective real-danger judgments; verify native price separately.

    Hostile damage is ordinary authority only within the shared Source CL band.
    Self-created, controlled and cooperative sources need the actual subject's
    scoped declaration; allegiance never fabricates willingness or danger.
    """
    source=ctx.actor
    if ctx.action.parameters.get('calamity_profile'):return bool(ctx.action.parameters['calamity_profile']['genuine_threat'])
    from .body_modes_scene_resources import qualified_source
    declaration=qualified_source(ctx.engine,target,source) or {}
    if declaration.get('staged')==1:return False
    controlled=source.summon is not None and source.owner_id in {target.entity_id,target.owner_id}
    if relation(ctx.engine,source,target)==ENEMY and not controlled and declaration.get('hostile')!=0:
        cl=int(ctx.numbers.get('cl',0));own=int(owned(ctx.engine,target)['cl'])
        return not cl or cl>=own-5
    from ..fact_consent_admission import admit_choice
    # Reject a free self-Release whose one spent Charge can refund its entire
    # native price. Actual HP loss, lasting harm, or another paid Charge remains
    # a genuine uncompensated price, subject to the owner's explicit admission.
    paid=[e for e in ctx.engine.events if e.trigger_or_intent_id==ctx.intent.intent_id and e.event_type=='RESOURCE_SPENT' and e.actor_id==source.entity_id]
    qi=sum(int(e.payload.get('amount',0)) for e in paid if e.payload.get('resource_id')==QI)
    charges=sum(int(e.payload.get('amount',0)) for e in paid if e.payload.get('resource_id')==CHARGES)
    actual=[e for e in ctx.engine.events if e.trigger_or_intent_id==ctx.intent.intent_id]
    known=source is target and any(e.event_type=='DAMAGE_COMMITTED' and target.entity_id in e.target_ids and e.payload.get('hp_damage',0)>0 for e in actual)
    lasting=any(e.event_type=='CONDITION_APPLIED' and target.entity_id in e.target_ids and str(e.payload.get('condition_id','')).split('.')[-1] in ('charmed','frightened','grappled','poisoned','prone','restrained','stunned') and e.payload.get('instance_id') in target.conditions for e in actual)
    if source is target and ctx.typed.get('source')==F+NAMES[2] and charges and qi==0 and not (known or lasting or charges>1):return False
    record=admit_choice(ctx,target,F+NAMES[0],'real_danger',ctx.intent.intent_id,['genuine'],labels={'genuine':'The danger is genuine; all normal costs and consequences are paid, and the event cannot refund its full cost through a closed loop'},prompt='Gather Calamity: does this self-created or cooperative source meet the Real Danger requirements?',expires_on='END_OF_CURRENT_TURN',automatic_options=['genuine'] if known and not charges else [])
    return record is not None


@effect('vessel_hazard_movement')
def hazard_movement(ctx,effect):
    from . import run_strict
    from ..movement_paths import resolve
    from ..gate2_runtime_models import Position
    feet=int(effect['distance_ft'])
    caps=[value for value in run_strict('forced_movement_restriction',ctx,ctx.actor,effect,feet) if type(value) is int and 0<=value<=feet]
    if caps:feet=min(feet,*caps)
    if not feet:return
    direction=effect['direction'];old=ctx.actor.position
    path=[old,*[Position(x=old.x+direction['dx']*i,y=old.y+direction['dy']*i,z=old.z+direction.get('dz',0)*i) for i in range(1,feet//ctx.engine.grid.square_size_ft+1) if old.z+direction.get('dz',0)*i>=0]]
    resolve(ctx.engine,ctx.actor,path,ctx.source,kind='forced',feet=feet,intent=ctx.intent,source_actor_id=ctx.actor.entity_id,ctx=ctx)


@effect('vessel_classify',harmful=False)
def classify_charge(ctx,effect):
    from ..fact_consent_admission import admit_choice
    d=state(ctx.engine,ctx.actor);unknown=[c for c in d['charges'] if not c.get('damage_types') and c['id'] in effect.get('charge_ids',[v['id'] for v in d['charges']])]
    if not unknown:return
    selected=choose(ctx,ctx.actor,'classify_charge',[c['id'] for c in unknown],{c['id']:c['type']+' Charge with unknown damage association' for c in unknown},'Choose a stored Charge whose actual associated damage type you can identify.')[0]
    charge=next(c for c in unknown if c['id']==selected)
    record=admit_choice(ctx,ctx.actor,F+NAMES[0],'calamity_damage_type',charge['event'],list(NATIVE_DAMAGE),labels={k:k.capitalize() for k in NATIVE_DAMAGE},prompt='Declare the actual damage type associated with this survived calamity, or leave it unknown.',expires_on='END_OF_CURRENT_TURN',automatic_options=[])
    if record:
        charge['damage_types']=[record['value']];charge['association_receipt']=record['receipt_id']
        d.setdefault('survived_damage_types',{}).setdefault(charge['type'],[])
        d['survived_damage_types'][charge['type']]=sorted(set([*d['survived_damage_types'][charge['type']],record['value']]))
        store(ctx.engine,ctx.actor,d)


@hook('nominal_slot_boundary')
def omitted_clock(engine,actor,checkpoint):
    if checkpoint!='START_OF_TURN' or not owned(engine,actor):return
    d=state(engine,actor)
    if not walking(d):return
    if retain_walking_clock(engine,d['walking'])<=0:
        d['backlash_due']=max(0,len(d['charges'])-3)
        d.pop('walking',None)
        if not d['backlash_due']:
            d.pop('backlash_due')
            d['charges']=[c for c in d['charges'] if not c.get('overflow')][:maximum(owned(engine,actor))]
    # Omitted slots are expiry-only: no die, damage or decision is offered here.
    store(engine,actor,d,expired=True)


@hook('state_event')
def settle_omitted_backlash(engine,event):
    if event.event_type!='TURN_STARTED':return
    from ..gate2_runtime_models import DiceSpec
    for actor in engine.state.actors.values():
        if not owned(engine,actor):continue
        d=state(engine,actor);extra=int(d.pop('backlash_due',0))
        if not extra:continue
        store(engine,actor,d)
        roll=engine.roller.roll(DiceSpec(count=extra,sides=8),actor_id=actor.entity_id,reason='Vessel Breaks Before the Calamity')
        engine._record_roll(roll)
        engine._commit_damage(actor,int(roll.total),'FORCE',F+'vessel_breaks',actor.entity_id,getattr(engine,'_active_intent',None),reaction_depth=0)
        d=state(engine,actor);d['charges']=[c for c in d['charges'] if not c.get('overflow')][:maximum(owned(engine,actor))]
        store(engine,actor,d,expired=True)


def technique_id(action):
    """Named Source Rule identity independent of the creature using it."""
    profile=action.parameters.get('calamity_profile')
    if profile:
        from ..fact_consent_admission import digest
        return 'calamity:'+digest({'name':profile['name'],'source_rule':profile['source_rule']})
    return (action.parameters.get('typed') or {}).get('source') or action.source_definition_id


def vessel_numbers(info):
    """Project this family's existing explicit Qi profile; no new Path schema."""
    numbers=deepcopy(info['numbers'])
    sheet=info['owner_sheet']
    profile=next((p for p in (sheet.get('path_and_subpath') or {}).get('paths',[]) if p.get('path_id')=='tianxia.path.qi_cultivation'),None)
    if profile is None:return numbers
    if 'effective_cl' in profile:
        numbers['cl']=min(int(numbers['cl']),int(profile.get('attainment',numbers['cl'])),int(profile['effective_cl']))
        require(numbers['cl']>=0,'Effective Qi CL must be a nonnegative suppressed attainment.')
        numbers['pb']=int(profile.get('proficiency_bonus') or 2+max(0,numbers['cl']-1)//4)
    elif 'attainment' in profile:numbers['cl']=min(numbers['cl'],int(profile['attainment']))
    if profile.get('key_ability'):
        key=str(profile['key_ability']).upper()[:3]
        abilities=(sheet.get('ability_scores_and_statistics') or {}).get('abilities',[])
        numbers['key_mod']=next((int(a['modifier']) for a in abilities if a.get('ability')==key),int(numbers['key_mod']))
    if 'effective_cl' in profile or profile.get('key_ability'):
        numbers['attack_bonus']=int(profile.get('technique_attack_bonus') or numbers['pb']+numbers['key_mod'])
        numbers['save_dc']=int(profile.get('technique_save_dc') or 8+numbers['attack_bonus'])
    return numbers


@hook('compile_bundle')
def seal_qi_profile(bundle,info):
    markers=[r for r in bundle.get('typed_passives',[]) if r.get('block')=='tribulation_vessel']
    if not markers:return None
    out=deepcopy(bundle);numbers=vessel_numbers(info)
    for row in out['typed_passives']:
        if row.get('block')=='tribulation_vessel':
            row.update({k:int(numbers[k]) for k in ('cl','pb','key_mod','save_dc')})
            row['features']=[n for n,l in zip(NAMES,LEVELS) if n in row['features'] and l<=numbers['cl']]
    marker=next(r for r in out['typed_passives'] if r.get('block')=='tribulation_vessel')
    for pool in out['actor_template']['resources']:
        if pool['resource_id']==CHARGES:pool.update(initial=0,maximum=maximum(marker))
    for action in out['action_catalog']:
        op=action['parameters'].get('vessel_operation')
        if op:
            typed=action['parameters']['typed'];typed['numbers']=deepcopy(numbers);typed['min_cl']=LEVELS[NAMES.index(op)]
    return out


@hook('match_initialize')
def maintain_profile(engine):
    changed=False
    for actor in engine.state.actors.values():
        row=owned(engine,actor)
        if row and walking(state(engine,actor)) and NAMES[4] not in row['features']:
            end_walk(engine,actor,state(engine,actor));changed=True
        elif row and any(c.condition_id==LEDGER for c in actor.conditions.values()):
            store(engine,actor,state(engine,actor));changed=True
    return True if changed else None


def root_reward(ctx,subject):
    signature={'intent':ctx.intent.intent_id,'source':ctx.source,'actor':ctx.actor.entity_id}
    d=state(ctx.engine,subject)
    if d.get('root_scar_effect')==signature:return
    d['root_scar_effect']=signature;store(ctx.engine,subject,d)
    scar(ctx.engine,subject,ctx.action.source_definition_id,ctx.actor.entity_id)


@hook('journey_snapshot_actor')
def suspend_family_clocks(actor,session,actor_id,engine):
    def family(source):
        action=engine.action_catalog.get(source)
        return source.startswith(F) or bool(action and (action.parameters.get('typed') or {}).get('source','').startswith(F))
    conditions={k:c for k,c in actor.conditions.items() if c.condition_id!=LEDGER and (c.condition_id.startswith('condition:typed.vessel_') or family(c.source_definition_id)) and c.expires_on not in (None,'UNTIL_REMOVED')}
    modifiers={k:m for k,m in actor.modifiers.items() if family(m.source_definition_id)}
    existing=session.state['actors'][actor_id].get('source_states',{}).get(P)
    if existing is not None:existing['continuing']=[]
    if not conditions and not modifiers:return None
    clone=actor.model_copy(deep=True)
    data=session.state['actors'][actor_id].setdefault('source_states',{}).setdefault(P,{})
    def requirement(obj):
        if getattr(obj,'data',{}).get('vessel_required_cl'):return int(obj.data['vessel_required_cl'])
        source=obj.source_definition_id;action=engine.action_catalog.get(source)
        feature=source if source in {F+n for n in NAMES} else (action.parameters.get('typed') or {}).get('source') if action else None
        return LEVELS[NAMES.index(feature[len(F):])] if feature in {F+n for n in NAMES} else 0
    data['continuing']=[{'kind':kind,'json':obj.model_dump_json(),'num':6,'den':1,'required_cl':requirement(obj)} for kind,values in [('condition',conditions),('modifier',modifiers)] for obj in values.values()]
    for key in conditions:clone.conditions.pop(key)
    for key in modifiers:clone.modifiers.pop(key)
    return clone


@hook('journey_combat_bundle')
def continue_family_bundle(bundle,session,actor_id):
    data=session.state['actors'][actor_id].get('source_states',{}).get(P,{})
    if not data:return None
    out=deepcopy(bundle);out['tribulation_vessel_continuing']=deepcopy(data.get('continuing',[]))
    marker=next((r for r in out.get('typed_passives',[]) if r.get('block')=='tribulation_vessel'),None)
    if marker:
        overflow=sum(c.get('overflow',0) for c in data.get('ledger',{}).get('charges',[]))
        for pool in out['actor_template']['resources']:
            if pool['resource_id']==CHARGES:pool['maximum']=max(len(data.get('ledger',{}).get('charges',[])),maximum(marker)+overflow)
    return out


@hook('match_initialize')
def restore_family_clocks(engine):
    changed=False
    from ..gate2_runtime_models import ConditionInstance,ModifierInstance
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:continue
        for item in bundle.get('tribulation_vessel_continuing',[]):
            if item['num']<=0:continue
            raw=json.loads(item['json']);source_actor=engine.state.actors.get(raw.get('source_actor_id'))
            source_row=owned(engine,source_actor) if source_actor is not None else None
            if item.get('required_cl',0) and (not source_row or source_row['cl']<item['required_cl']):continue
            if item['kind']=='condition':
                c=ConditionInstance.model_validate_json(item['json'])
                engine._apply_condition(actor,c.condition_id,c.source_definition_id,c.source_actor_id,expires_on=c.expires_on,data=c.data)
            else:
                m=ModifierInstance.model_validate_json(item['json'])
                engine._add_modifier(actor,m.source_definition_id,m.target_field,m.operation,m.value,m.applies_to,expires_on=m.expires_on,source_actor_id=m.source_actor_id,application_id=m.application_id)
            changed=True
    return True if changed else None


def seal_penetration(ctx,key,kinds):
    if not owned(ctx.engine,ctx.actor):return
    d=state(ctx.engine,ctx.actor);p=d.get('pending',{})
    if not pending_matches(ctx,p) or 'penetrate' not in p.get('benefits',[]):return
    p['penetrate_current']=0
    if 'penetrate_roll' not in p and 'force' in [str(k).lower() for k in kinds]:
        answer=choose(ctx,ctx.actor,'penetrate_'+str(key),['ignore'],{'ignore':'Ignore ordinary Resistance to Force for this damage roll'},'Calamity Tempering: use the Force benefit for this one damage roll, or retain it.',minimum=0,decline=True)
        if answer:p['penetrate_roll']=str(key)
    p['penetrate_current']=int(p.get('penetrate_roll')==str(key));store(ctx.engine,ctx.actor,d)


@hook('damage_roll_resolved')
def penetrate_one_roll(ctx,effect,cache_key):
    cached=ctx.damage_cache.get(cache_key)
    if isinstance(cached,tuple) and len(cached)==2:seal_penetration(ctx,str(cache_key),[cached[1]])


def roll_spent_damage(ctx,matching=None):
    """Commit added dice before a source roll is halved or defended."""
    if not owned(ctx.engine,ctx.actor):return []
    d=state(ctx.engine,ctx.actor);p=d.get('pending',{})
    if not pending_matches(ctx,p):return []
    result=[]
    from ..gate2_runtime_models import DiceSpec
    for key in p.get('benefits',[]):
        if key not in ('damage','force_damage') or key in p.get('done',[]):continue
        kinds=['force'] if key=='force_damage' else p.get('damage_types',[])
        if matching is not None:kinds=[k for k in kinds if k.lower()==matching.lower()]
        if not kinds:continue
        answer=choose(ctx,ctx.actor,'roll_bonus_'+key,kinds,{k:'Add 1d8 '+k.capitalize()+' to this damage roll before a save halves it' for k in kinds},'Spend Calamity: use the added damage on this roll, or retain it for a later roll.',minimum=0,decline=True)
        if not answer:continue
        p['done'].append(key);store(ctx.engine,ctx.actor,d)
        roll=ctx.engine.roller.roll(DiceSpec(count=1,sides=8),actor_id=ctx.actor.entity_id,reason='DAMAGE:'+ctx.source,critical=ctx.critical_hit)
        ctx.engine._record_roll(roll);result.append((answer[0],int(roll.total)))
    return result


@hook('damage_roll_bonus')
def matching_spent_damage(ctx,effect,kinds):
    matching=getattr(ctx.engine,'_typed_pending_damage_type',None)
    if not matching:return
    return sum(value for kind,value in roll_spent_damage(ctx,matching)) or None


@hook('journey_damage_actor')
def journey_damage_actor(actor,session,actor_id,engine):
    data=session.state['actors'][actor_id].get('source_states',{}).get(P,{})
    row=owned(engine,actor)
    if row and CHARGES in actor.resource_maximums:
        actor.resource_maximums[CHARGES]=maximum(row)+sum(c.get('overflow',0) for c in data.get('ledger',{}).get('charges',[]))
    # Restoring these records is local to a native elapsed-event clone. The
    # terminal encounter and source snapshots stay immutable until settlement.
    from ..gate2_runtime_models import ConditionInstance,ModifierInstance
    for item in data.get('continuing',[]):
        if item['num']<=0:continue
        if item['kind']=='condition':
            c=ConditionInstance.model_validate_json(item['json']);actor.conditions[c.instance_id]=c
        else:
            m=ModifierInstance.model_validate_json(item['json']);actor.modifiers[m.modifier_id]=m
    return actor


@hook('compile_action')
def native_bonus_packets(action,info):
    """Use existing optional shared-roll slots for differently typed dice."""
    if F+NAMES[0] not in info['owned_ids'] or action.parameters.get('vessel_operation'):return None
    typed=action.parameters.get('typed') or {}
    from .qi_path import is_qi_powered_activation
    if not typed or not (is_qi_powered_activation(action) or any(pool==QI and amount for pool,amount in action.costs) or cultivation_attack(typed.get('effects',[])) or str(typed.get('source','')).startswith(('tianxia.path.qi_cultivation.','tianxia.subpath.qi.'))):return None
    out=deepcopy(typed);out['effects']=bonus_effects(typed.get('effects',[]),'effects')
    return action.model_copy(update={'parameters':{**action.parameters,'typed':out}})


@hook('effect_allowed')
def admit_bonus_packet(ctx,effect):
    key=effect.get('vessel_spent_bonus')
    if not key:return None
    if not owned(ctx.engine,ctx.actor):return False
    d=state(ctx.engine,ctx.actor);pending=d.get('pending',{})
    if not pending_matches(ctx,pending) or key not in pending.get('benefits',[]):return False
    from ..effect_eligibility import damage_bonus_slot
    slot=damage_bonus_slot(ctx,effect);cache='vessel_bonus_packet:'+key
    selected=ctx.damage_cache.get(cache)
    if selected:return selected['slot']==slot
    if key in pending.get('done',[]):return False
    kinds=['force'] if key=='force_damage' else pending.get('damage_types',[])
    if not kinds:return False
    answer=choose(ctx,ctx.actor,'packet_bonus_'+key+'_'+str(slot),kinds,{kind:'Add 1d8 '+kind.capitalize()+' damage to this roll' for kind in kinds},'Spend Calamity: add the associated damage before save-for-half and defenses, or retain it.',minimum=0,decline=True)
    if not answer:return False
    ctx.damage_cache[cache]={'slot':slot,'type':answer[0]}
    pending['done'].append(key);store(ctx.engine,ctx.actor,d)
    return True


from contextvars import ContextVar
from contextlib import contextmanager
_BONUS_PACKET=ContextVar('tribulation_vessel_bonus_packet',default=None)


@hook('effect_resolution_scope')
def bonus_packet_scope(ctx,effect):
    if not effect.get('vessel_spent_bonus'):return None
    @contextmanager
    def scope():
        token=_BONUS_PACKET.set((ctx.actor.entity_id,effect['vessel_spent_bonus']))
        try:yield
        finally:_BONUS_PACKET.reset(token)
    return scope()


@hook('damage_type_override')
def bonus_packet_type(ctx,kinds,targets):
    scope=_BONUS_PACKET.get()
    if not scope or scope[0]!=ctx.actor.entity_id:return None
    return (ctx.damage_cache.get('vessel_bonus_packet:'+scope[1]) or {}).get('type')


@effect('vessel_reaction_marker',harmful=False)
def reaction_marker(ctx,effect):
    # Only the real native trigger/consent/cost handlers execute this feature.
    return None


@hook('journey_time_boundaries')
def next_source_boundary(session,previous,after):
    duration=after-previous
    from fractions import Fraction
    deadlines=[]
    for actor in session.state['actors'].values():
        data=actor.get('source_states',{}).get(P,{})
        d=data.get('ledger',{})
        if walking(d):
            clock=d['walking'];deadlines.append(Fraction(clock['deadline_num'],clock['deadline_den'])-previous if 'deadline_num' in clock else Fraction(clock.get('remaining_num',int(clock['remaining'])*6),clock.get('remaining_den',1)))
        deadlines.extend(Fraction(item['num'],item['den']) for item in data.get('continuing',[]))
        deadlines.extend(Fraction(p['expires_at'])-previous for p in data.get('profiles',[]) if p.get('journey_id')==session.state['journey_id'])
    next_=min((n for n in deadlines if 0<n<=duration),default=None)
    return [previous+next_] if next_ is not None else None


def journey_sense(session,actor_id):
    from ..gate2_runtime_models import Position,ConditionInstance
    actor=session.state['actors'][actor_id]
    marker=next((r for r in actor['bundle'].get('typed_passives',[]) if r.get('block')=='tribulation_vessel'),None)
    from .body_modes_scene_resources import journey_available
    if not marker or NAMES[0] not in marker['features'] or not journey_available(session,actor_id,F+NAMES[0],3,requires_conscious=False,path_id='tianxia.path.qi_cultivation',compiled_level=marker['cl']):return
    # These profiles author exposed world hazards. Retained blindness and actual
    # scene geometry still prevent visual perception; no name infers a hazard.
    conditions=[ConditionInstance.model_validate_json(raw) for raw in actor.get('encounter_snapshot',{}).get('conditions',{}).values()]
    if any(c.condition_id in ('blinded','condition:typed.blinded') for c in conditions):return
    data=actor.get('source_states',{}).get(P,{})
    d=data.get('ledger',{'charges':[],'history':[],'events':[],'sequence':0})
    for p in data.get('profiles',[]):
        if p.get('journey_id')!=session.state['journey_id']:continue
        point=Position.model_validate(p['position']);position=Position.model_validate(actor['position'])
        if p['expires_at']<=session.clock() or session.grid.distance_ft(position,point)>60 or not session.grid.line_of_sight(position,point):continue
        if p['receipt_id'] in d.get('journey_sensed',[]):continue
        d.setdefault('journey_sensed',[]).append(p['receipt_id'])
        session.emit('CALAMITY_SENSE',actor_id,readers=[actor_id],name=p['name'],calamity_type=p['type'],stability=p['status'],source_cl=p['source_cl'],qualifies=p['genuine_threat'],
                     text=f"{p['name']}: {p['type']}, {p['status']}, Source CL {p['source_cl']}; surviving it {'can' if p['genuine_threat'] else 'cannot'} grant a Calamity Charge.")
    journey_store_ledger(actor,d)


@hook('journey_acquired')
def acquired_sense(session,actor_id,source,acquisition_id):
    if source==P:journey_sense(session,actor_id)


@hook('journey_state_changed')
def changed_sense(session,actor_id):journey_sense(session,actor_id)


@hook('journey_options')
def sense_option(session,actor_id):
    actor=session.state['actors'][actor_id]
    marker=next((r for r in actor['bundle'].get('typed_passives',[]) if r.get('block')=='tribulation_vessel' and NAMES[0] in r['features']),None)
    from .body_modes_scene_resources import journey_available
    if marker and journey_available(session,actor_id,F+NAMES[0],3,requires_conscious=False,path_id='tianxia.path.qi_cultivation',compiled_level=marker['cl']):return [{'id':'vessel:calamity_sense','kind':'vessel_sense','label':'Calamity Sense: perceive exposed active calamities within 60 feet','payload':{},'auto_select':0}]


@hook('journey_command')
def sense_command(session,actor_id,kind,payload):
    if kind!='vessel_sense':return None
    require(payload=={} and sense_option(session,actor_id),'This creature has no Calamity Sense.')
    journey_sense(session,actor_id);return True


@hook('object_displacement_distance')
def spent_object_movement(ctx,obj,effect,maximum_ft):
    if not owned(ctx.engine,ctx.actor):return None
    d=state(ctx.engine,ctx.actor);p=d.get('pending',{})
    if not pending_matches(ctx,p):return None
    keys=[key for key in p.get('benefits',[]) if key in ('force','force15') and key not in p.get('done',[])]
    if not keys:return None
    from ..object_rules import label
    selected=choose(ctx,ctx.actor,'object_benefits_'+obj.object_id,keys,{key:'Increase this push, pull or lift by '+str(15 if key=='force15' else 10)+' feet' for key in keys},'Spend Calamity: increase this physical movement of '+label(obj)+', or retain the benefit.',minimum=0,maximum=len(keys),decline=True)
    p['done']+=selected;store(ctx.engine,ctx.actor,d)
    return maximum_ft+sum(15 if key=='force15' else 10 for key in selected)


def bonus_effects(rows,path):
    def bonuses(stage):
        return [{'type':'damage','applies_to':'target','dice':{'count':1,'sides':8},'damage_types':list(NATIVE_DAMAGE),
                 'vessel_spent_bonus':key,'damage_bonus_packet':True,'damage_bonus_group':F+key,
                 'damage_bonus_stage':stage} for key in ('damage','force_damage')]
    def rewrite(rows,path):
        out=[]
        for i,raw in enumerate(rows):
            row=deepcopy(raw);stage=path+':'+str(i)
            for key in ('effects','on_hit','on_fail','on_success'):
                if isinstance(row.get(key),list):row[key]=rewrite(row[key],stage+':'+key)
            if row.get('type')=='attack':row.setdefault('on_hit',[]).extend(bonuses(stage+':attack'))
            out.append(row)
            if row.get('type')=='damage':out.extend(bonuses(stage))
        return out
    return rewrite(rows,path)


def pending_matches(ctx,pending):
    if pending.get('intent')!=ctx.intent.intent_id:return False
    from ..paid_relocation import capture
    original=(getattr(ctx.engine,'_vessel_spend_owners',{}) or {}).get(ctx.actor.entity_id)
    current=capture(ctx.engine)
    if original is not None and current is not None:return original==current
    return pending.get('action')==ctx.action.source_definition_id or pending.get('feature')==ctx.typed.get('source')


@hook('activation_accounting')
def activation_accounting(engine):
    if any(owned(engine,a) and NAMES[0] in owned(engine,a)['features'] for a in engine.state.actors.values()):return True


@hook('accepted_reaction')
def reaction_spending(engine,actor,row):
    if not owned(engine,actor) or row.get('feature_id')==F+NAMES[3]:return
    intent=getattr(engine,'_active_intent',None)
    if intent is None:return
    from ..typed_reactions import triggered_context,cost_dict
    ctx=triggered_context(engine,actor,None,row,intent)
    costs=[cost_dict(c) for c in row.get('costs',[])]
    if row.get('resource_id') and row.get('cost'):costs.append({'resource_id':row['resource_id'],'amount':row['cost']})
    ctx.action=ctx.action.model_copy(update={'costs':tuple((c['resource_id'],int(c['amount'])) for c in costs if c.get('amount'))})
    spend(ctx)


@hook('reaction_effects')
def reaction_bonus_packets(effects,ctx):
    if not owned(ctx.engine,ctx.actor):return None
    pending=state(ctx.engine,ctx.actor).get('pending',{})
    if pending_matches(ctx,pending):return bonus_effects(effects,'reaction')



@hook('zone_trigger_resolved')
def survived_zone(ctx,zone,subject,moment,events):
    if ctx.intent is None or not owned(ctx.engine,subject):return
    from .life_state import is_deceased
    if is_deceased(subject):return
    events=tuple(e for e in events if e.source_definition_id==ctx.damage_source)
    packets=[e for e in events if e.event_type=='DAMAGE_COMMITTED' and subject.entity_id in e.target_ids and int(e.payload.get('hp_damage',0))+int(e.payload.get('temporary_hp_absorbed',0))>0]
    saves=[e for e in events if e.event_type=='SAVE_ROLLED' and subject.entity_id in (e.actor_id,*e.target_ids)]
    conditions=[e for e in events if e.event_type=='CONDITION_APPLIED' and subject.entity_id in e.target_ids and str(e.payload.get('condition_id','')).split('.')[-1] in ('charmed','frightened','grappled','poisoned','prone','restrained','stunned')]
    if not (packets or saves or conditions):return
    great=event_reduced_above_half_to_zero(subject,packets)
    receipt='zone:'+zone.zone_id+':'+ctx.intent.intent_id+':'+moment+':'+str(ctx.engine.state.round_number)
    collect(ctx,subject,receipt,great=great,damage_types=[e.payload.get('damage_type') for e in packets])
    d=state(ctx.engine,subject);d['completed_zone_intents']=[ctx.intent.intent_id];store(ctx.engine,subject,d)


@hook('fall_landed')
def survived_fall(engine,subject,fall,intent):
    if intent is None or not owned(engine,subject):return
    from .life_state import is_deceased
    if is_deceased(subject):return
    from ..falling import SOURCE
    packets=[e for e in engine.events if e.trigger_or_intent_id==intent.intent_id and e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id==SOURCE and subject.entity_id in e.target_ids and int(e.payload.get('hp_damage',0))>0]
    if not packets:return
    ctx=context(engine,subject)
    if ctx:
        ctx=replace(ctx,typed={**ctx.typed,'numbers':{}})
        collect(ctx,subject,'fall:'+intent.intent_id+':'+str(len(packets)),great=any(e.payload.get('hp_before',0)>subject.maximum_hp//2 and e.payload.get('remaining_hp',1)==0 for e in packets),damage_types=['bludgeoning'])


@hook('damage_dealt')
def survived_periodic_damage(ctx,subject,amount):
    # Continuing native conditions have their own source attribution and native
    # periodic intent; they are not a new activation of the owner's action.
    if amount<=0 or ctx.intent is None or not str(ctx.intent.intent_id).startswith(('periodic-damage:','rider-trigger:')) or not owned(ctx.engine,subject):return
    from .life_state import is_deceased
    if is_deceased(subject):return
    packets=ctx.damage_packets
    collect(ctx,subject,'periodic:'+ctx.intent.intent_id,great=any(p.get('hp_before',0)>subject.maximum_hp//2 and p.get('remaining_hp',1)==0 for p in packets),damage_types=[p.get('damage_type') for p in packets])


@hook('observer_information')
def calamity_information(engine,viewer):
    if not owned(engine,viewer):return []
    # The common observer contract projects only this seat's committed memory.
    # Learning these broad facts never grants a target, hidden trigger or square.
    return list(state(engine,viewer).get('sense_readings',{}).values())


@hook('match_start',priority=-170)
def reconcile_shared_availability(engine):
    maintain_profile(engine)
    from .body_modes_scene_resources import available
    for target in engine.state.actors.values():
        for c in list(target.conditions.values()):
            minimum=int(c.data.get('vessel_required_cl',0))
            source=engine.state.actors.get(c.source_actor_id)
            row=owned(engine,source) if source is not None else None
            if minimum and row and not available(engine,source,c.source_definition_id,minimum,requires_conscious=False,path_id='tianxia.path.qi_cultivation',compiled_level=row['cl']):
                remove_instance(engine,target,c.instance_id,c.source_definition_id)
        for key,m in list(target.modifiers.items()):
            if m.source_definition_id!=F+NAMES[1]:continue
            source=engine.state.actors.get(m.source_actor_id)
            row=owned(engine,source) if source is not None else None
            if row and not available(engine,source,F+NAMES[1],6,requires_conscious=False,path_id='tianxia.path.qi_cultivation',compiled_level=row['cl']):
                engine._remove_modifier_instance(target,key,m.source_definition_id)


@hook('resolution_numbers')
def live_vessel_numbers(ctx,numbers):
    source=ctx.typed.get('source','')
    if source not in {F+n for n in NAMES} or ctx.action.parameters.get('calamity_profile'):return None
    row=owned(ctx.engine,ctx.actor)
    if not row:return None
    # Runtime suppression uses the same owned source profile as eligibility;
    # the compiled chassis and already-paid resource maxima remain unchanged.
    return {**numbers,**{k:int(row[k]) for k in ('cl','pb','key_mod','save_dc')}}
