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
P='tianxia.subpath.qi.tribulation_vessel'
F=P+'.feature.'
NAMES=('gather_calamity','calamity_tempering','tribulation_release','calamity_furnace','walking_tribulation')
LEVELS=(3,6,10,14,18)
LEDGER='condition:typed.tribulation_vessel'
QI='resource:core.qi'
TYPES=('Flame','Frost','Lightning','Storm','Force','Gravity','Blood','Shadow','Spirit','General')
DAMAGE={'Flame':['fire'],'Frost':['cold'],'Lightning':['lightning'],'Storm':['thunder','lightning'],'Force':['force'],'Gravity':['force','bludgeoning'],'Blood':['necrotic'],'Shadow':['necrotic','psychic'],'Spirit':['psychic','radiant'],'General':['force']}


def owned(engine,actor):
    return next((r for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,[]) if r.get('block')=='tribulation_vessel'),None)


def state(engine,actor):
    row=next((c for c in actor.conditions.values() if c.condition_id==LEDGER),None)
    return json.loads(row.data['ledger']) if row else {'charges':[],'history':[],'events':[],'sequence':0}


def store(engine,actor,data):
    for c in list(actor.conditions.values()):
        if c.condition_id==LEDGER:remove_instance(engine,actor,c.instance_id,F+'gather_calamity')
    engine._apply_condition(actor,LEDGER,F+'gather_calamity',actor.entity_id,expires_on='UNTIL_REMOVED',data={'ledger':json.dumps(data,sort_keys=True),'label':'Preserved Calamity Charges'})


def stamp(engine):return str(engine.state.round_number)+':'+str(engine.state.current_actor_id)
def maximum(row):return int(row['pb'])+(3 if row['cl']>=14 else 0)
def walking(data):return bool(data.get('walking'))


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source!=P:return None
    if kind in ('source_access','calamity_profile'):
        return {'value_type':'document','maximum_seconds':2592000,'authority':'table_owner',
                'description':'Restricted scripture access' if kind=='source_access' else 'Named real calamity, source authority and uncompromised consequences'}


@hook('journey_source_sheet')
def source_sheet(sheet,session,actor_id):
    data=session.state['actors'][actor_id].get('source_states',{}).get(P)
    if not data:return None
    paths=sheet.setdefault('path_and_subpath',{})
    cl=int(sheet['identity']['cultivation_level'])
    paths['path_feature_record_ids']=list(dict.fromkeys([*paths.get('path_feature_record_ids',[]),*[F+n for n,l in zip(NAMES,LEVELS) if l<=min(cl,data['attainment'])]]))
    paths['subpath_record_id']=P;paths['subpath_record_ids']=[P]
    sheet['tribulation_vessel_profiles']=deepcopy(data.get('profiles',[]))
    return sheet


@hook('journey_acquisition')
def acquire(session,actor_id,source,payload,sheet):
    if source!=P:return None
    from ..fact_consent_admission import read
    require(set(payload)<={'access_scope','hazard_scopes'} and 'access_scope' in payload,'Choose the restricted scripture admission.')
    access=read(session,P,actor_id,'source_access',payload['access_scope'],actor_id)
    require(access and access['value'].get('route')=='restricted_scripture' and access['value'].get('source_rule'),'Restricted Scripture requires explicit table-owner source access.')
    cl=int(sheet['identity']['cultivation_level']);paths=sheet.get('path_and_subpath',{})
    require(cl>=3 and any(p.get('path_id')=='tianxia.path.qi_cultivation' and int(p.get('attainment',0))>=3 for p in paths.get('paths',[])),'Tribulation Vessel requires Qi Cultivation attainment 3.')
    require(not any('calamity_devouring_tribulation_vessel' in x for x in paths.get('path_feature_record_ids',[])),'A replacement progression cannot coexist with Tribulation Vessel.')
    require(not paths.get('subpath_record_id') or paths['subpath_record_id']==P,'Acquire only one Qi subpath progression.')
    profiles=[]
    for scope in payload.get('hazard_scopes',[]):
        record=read(session,P,actor_id,'calamity_profile',scope,actor_id)
        require(record,'The calamity profile is missing, private, or expired.')
        profile=deepcopy(record['value']);validate_profile(profile)
        profile.update(receipt_id=record['receipt_id'],expires_at=record['expires_at'])
        profiles.append(profile)
    data=session.state['actors'][actor_id].setdefault('source_states',{}).setdefault(P,{})
    data.update(attainment=cl,access=access['receipt_id'],profiles=profiles)
    result=source_sheet(sheet,session,actor_id)
    session.emit('TRIBULATION_SCRIPTURE_ACQUIRED',actor_id,source=P,access_receipt=access['receipt_id'],attainment=cl)
    return {'sheet':result,'acquisition_id':access['receipt_id']}


def validate_profile(p):
    require(set(p)=={'name','source_rule','type','source_cl','damage_type','dice','dc','save','status','category','position','legendary','formal_tribulation','cost_qi'},'Supply the complete calamity profile, including source, consequences, authority and position.')
    require(all(type(p[k]) is str and p[k].strip() for k in ('name','source_rule')),'Name the actual calamity and its controlling rule.')
    require(p['type'] in TYPES and p['damage_type'] in DAMAGE[p['type']],'Choose a represented Calamity and damage type.')
    require(p['save'] in ('dex','con','str','wis','cha') and type(p['dc']) is int and 1<=p['dc']<=50,'Supply the real save and DC.')
    require(type(p['source_cl']) is int and p['source_cl']>=1 and all(type(p[k]) is int and p[k] in (0,1) for k in ('legendary','formal_tribulation')),'Supply explicit source authority.')
    require(p['status'] in ('stable','growing','collapsing','about to discharge') and p['category'] in ('hazard','hostile field','tribulation residue','damaged Formation','unstable artifact','environmental catastrophe'),'Choose an active Calamity Sense category and state.')
    require(set(p['dice'])=={'count','sides'} and type(p['dice']['count']) is int and 1<=p['dice']['count']<=20 and p['dice']['sides'] in (4,6,8,10,12),'Supply positive genuine damage consequences.')
    require(type(p['cost_qi']) is int and p['cost_qi']>=0 and isinstance(p['position'],dict),'Supply the full normal cost and map position.')


@hook('compile_passives')
def compile_vessel(rows,info):
    mids=set(info['owned_ids']);held=[n for n in NAMES if F+n in mids]
    if not held:return rows
    require(not any('calamity_devouring_tribulation_vessel.feature.' in x for x in mids),'Parent and replacement progression cannot coexist.')
    cl=int(info['numbers']['cl'])
    return [*rows,{'block':'tribulation_vessel',**{k:int(info['numbers'].get(k,0)) for k in ('cl','pb','key_mod','save_dc')},'features':held}]


@hook('compile_action')
def remove_placeholder(action,info):
    if (action.parameters.get('typed') or {}).get('source') in {F+n for n in NAMES}:
        return action.model_copy(update={'parameters':{**action.parameters,'typed':{**action.parameters['typed'],'effects':[]}}})


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition
    mids=set(info['owned_ids']);out=[]
    def add(name,n,economy,effects,cost=0,area=None,profile=None):
        typed={'source':F+n,'numbers':dict(info['numbers']),'effects':effects,'riders':[],'duration':{'kind':'instant'}}
        if area:typed['area']=area
        params={'typed':typed,'vessel_operation':n}
        if profile:params['calamity_profile']=profile
        out.append(ActionDefinition(source_definition_id='action:typed.'+info['short']+'.vessel.'+n+'.'+str(len(out)),display_name=name,owner_id=info['actor_id'],economy=economy,resolution_kind='TYPED',target_kind='SELF' if not area else 'CELL',range_ft=0 if not area else 30,costs=((QI,cost),) if cost else (),parameters=params))
    if F+NAMES[0] not in mids:return None
    add('Calamity Sense',NAMES[0],'NONE',[{'type':'vessel_sense'}])
    if F+NAMES[2] in mids:add('Tribulation Release',NAMES[2],'ACTION',[{'type':'vessel_release'}],area={'shape':'sphere','size_ft':30})
    if F+NAMES[4] in mids:add('Walking Tribulation',NAMES[4],'BONUS_ACTION',[{'type':'vessel_walk'}],8)
    for profile in info['owner_sheet'].get('tribulation_vessel_profiles',[]):
        add('Face Calamity: '+profile['name'],NAMES[0],'ACTION',[{'type':'vessel_exposure','profile':profile}],profile['cost_qi'],profile=profile)
    return out


@hook('candidate_allowed')
def allowed(engine,actor,candidate,action):
    op=action.parameters.get('vessel_operation')
    if not op:return None
    row=owned(engine,actor)
    if not row or NAMES.index(op)>0 and row['cl']<LEVELS[NAMES.index(op)]:return False
    d=state(engine,actor)
    if op==NAMES[2]:
        if not d['charges'] or actor.resources.get(QI,0)<(0 if walking(d) and d.get('free_release')!=stamp(engine) else 3):return False
        # Ordinary origins are self or the native Domain Armament; the endpoint
        # selected here is only a free Walking origin within thirty feet.
        if candidate.destination and not walking(d):return candidate.destination==actor.position
    if op==NAMES[4] and (walking(d) or d.get('scene_used')):return False
    p=action.parameters.get('calamity_profile')
    if p:
        from ..gate2_runtime_models import Position
        if engine.grid.distance_ft(actor.position,Position.model_validate(p['position']))>5:return False
    return None


def choose(ctx,actor,key,options,labels,prompt,*,minimum=1,maximum=1,decline=False,automatic=None):
    from .needle import ask,checkpoint_id
    return ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'vessel',key,actor.entity_id),actor,'choice:vessel.'+key,options,labels=labels,prompt=prompt,minimum=minimum,maximum=maximum,allow_decline=decline,default='decline' if decline else options[0],automatic_options=options if automatic is None else automatic,feature_id=ctx.source,name=ctx.action.display_name)


def context(engine,actor,source=None):
    from ..typed_executor import Context
    intent=getattr(engine,'_active_intent',None)
    if intent is None:return None
    action=engine.action_catalog.get(intent.source_definition_id)
    if action is None:return None
    typed={'source':source or F+NAMES[0],'numbers':owned(engine,actor) or {}}
    return Context(engine,actor,action,intent,typed,[actor],actor,{})


def collect(ctx,target,receipt,profile=None,*,great=False):
    row=owned(ctx.engine,target)
    if not row:return
    d=state(ctx.engine,target)
    if receipt in d['events']:return
    r=str(ctx.engine.state.round_number)
    prior=d.get('gain_round')
    limit=2 if walking(d) else 1
    if prior==r and int(d.get('gains',0))>=limit:return
    if profile:kind=profile['type']
    else:
        answer=choose(ctx,target,'calamity_type_'+receipt,list(TYPES),{x:x for x in TYPES},f'{target.display_name}: choose the closest Calamity Type represented by the resolved danger.')
        if not answer:return
        kind=answer[0]
    count=3 if profile and profile.get('formal_tribulation') else 2 if great or profile and (profile.get('legendary') or profile['source_cl']>=row['cl']+3) else 1
    source_cl=profile['source_cl'] if profile else int(ctx.numbers.get('cl',row['cl']))
    count=min(count,max(0,maximum(row)-sum(not c.get('overflow') for c in d['charges'])))
    if not count:return
    for _ in range(count):
        d['sequence']+=1;d['charges'].append({'id':str(d['sequence']),'type':kind,'source_cl':source_cl,'event':receipt,'overflow':0})
    d['events'].append(receipt)
    d['history']=sorted(set([*d['history'],kind]));d['gains']=int(d.get('gains',0))+1 if prior==r else 1;d['gain_round']=r
    store(ctx.engine,target,d)


@effect('vessel_exposure')
def exposure(ctx,effect):
    from ..typed_executor import run_effects
    p=effect['profile'];start=len(ctx.engine.events)
    run_effects(ctx,[{'type':'save','ability':p['save'],'on_fail':[{'type':'damage','applies_to':'self','dice':p['dice'],'damage_types':[p['damage_type']]}],'on_success':[{'type':'half_damage','applies_to':'self','damage_types':[p['damage_type']]}]}])
    packets=[e for e in ctx.engine.events[start:] if e.event_type=='DAMAGE_COMMITTED' and ctx.actor.entity_id in e.target_ids and e.payload.get('hp_damage',0)>0]
    if packets and ctx.actor.life_state!='DEAD':collect(ctx,ctx.actor,'exposure:'+ctx.intent.intent_id,p)


@hook('technique_used')
def settled_calamity(ctx):
    if ctx.action.parameters.get('calamity_profile'):return
    events=ctx.engine.events[ctx.technique_event_start or 0:]
    for target in ctx.engine.state.actors.values():
        if not owned(ctx.engine,target) or target.team_id==ctx.actor.team_id:continue
        packets=[e for e in events if e.event_type=='DAMAGE_COMMITTED' and target.entity_id in e.target_ids and int(e.payload.get('hp_damage',0))>0]
        conditions=[e for e in events if e.event_type=='CONDITION_APPLIED' and target.entity_id in e.target_ids and str(e.payload.get('condition_id','')).split('.')[-1] in ('charmed','frightened','grappled','poisoned','prone','restrained','stunned')]
        if packets or conditions:collect(ctx,target,'intent:'+ctx.intent.intent_id)


@hook('save_final')
def save_calamity(ctx,subject,ability,named,failed):
    if owned(ctx.engine,subject) and subject.team_id!=ctx.actor.team_id and ctx.source!=F+NAMES[2]:
        # Harmful supernatural saves qualify on success too; actual block_save
        # supplies this checkpoint, rather than a claimed trigger receipt.
        collect(ctx,subject,'save:'+str(getattr(ctx.save_result,'roll_id',ctx.intent.intent_id)))


@effect('vessel_sense',harmful=False)
def sense(ctx,effect):
    from ..gate2_runtime_models import Position
    for action in ctx.engine.action_catalog.values():
        p=action.parameters.get('calamity_profile')
        if not p:continue
        pos=Position.model_validate(p['position'])
        if ctx.engine.grid.distance_ft(ctx.actor.position,pos)<=60 and ctx.engine.grid.line_of_sight(ctx.actor.position,pos):
            ctx.engine._append_event('PASSIVE_TRIGGERED',F+NAMES[0],actor_id=ctx.actor.entity_id,payload={'text':f"{p['name']}: {p['type']}, {p['status']}, Source CL {p['source_cl']}; surviving its genuine danger can grant a Calamity Charge."})
