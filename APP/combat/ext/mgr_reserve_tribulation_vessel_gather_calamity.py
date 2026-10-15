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
        if candidate.destination and not walking(d) and not candidate.metadata.get('effect_origin'):return candidate.destination==actor.position
    if op==NAMES[4] and (walking(d) or d.get('scene_used') or not d['history']):return False
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
    ctx=replace(ctx,typed={**ctx.typed,'numbers':{**ctx.numbers,'save_dc':p['dc']}})
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

# Benefit options are source data. Every option remains a controller decision.
NORMAL={'damage':'Add 1d8 associated damage to one damage roll','temp':'Gain Temporary Hit Points equal to twice Proficiency Bonus','move':'Move 10 feet without provoking Opportunity Attacks','force':'Add 10 feet to one forced movement','armament':'Move your Domain Armament 20 feet','check':'Add Proficiency Bonus to one Cultivation Check in this activation'}
TEMPER={'Flame':{'fire':'Add 1d8 Fire damage to one damaged target','fire_resist':'Resistance to Fire until your next turn starts'},'Frost':{'slow':'Reduce one damaged target’s Speed by 15 feet until your next turn starts','cold_resist':'Resistance to Cold until your next turn starts'},'Lightning':{'reactions':'One damaged target cannot take Reactions until its next turn starts','move15':'Move 15 feet without provoking Opportunity Attacks'},'Storm':{'storm_move':'Push or pull one affected creature 15 feet','fly':'Fly Speed 30 feet until this turn ends'},'Force':{'ac':'Gain +2 AC until your next turn starts','penetrate':'Ignore Resistance to Force for one damage roll'},'Gravity':{'root':'Prevent forced movement and Prone until your next turn starts','force15':'Add 15 feet to one forced movement'},'Blood':{'blood_temp':'Gain Temporary Hit Points equal to three times Proficiency Bonus','blood_heal':'Reduce one damaged target’s first healing by twice Proficiency Bonus before your next turn starts'},'Shadow':{'obscured':'Become Lightly Obscured until your next turn starts','see_shadow':'Invisible cannot conceal one damaged target from you until your next turn starts'},'Spirit':{'spirit_guard':'Advantage against Charmed, Frightened, possession and soul displacement until your next turn starts','concentration':'One damaged target has Disadvantage on its next Concentration save before your next turn starts'},'General':{'temp':'Gain Temporary Hit Points equal to twice Proficiency Bonus','move':'Move 10 feet without provoking Opportunity Attacks','force_damage':'Add 1d8 Force damage','force':'Add 10 feet to forced movement'}}


def rule_condition(ctx,subject,key,rule,expiry='START_OF_SOURCE_NEXT_TURN'):
    ctx.engine._apply_condition(subject,'condition:typed.vessel_'+key,ctx.source,ctx.actor.entity_id,expires_on=expiry,data={'rule':rule,'label':key.replace('_',' ').capitalize()})


def movement(ctx,feet):
    from .granted_movement import choices,move
    rows=choices(ctx.engine,ctx.actor,feet)
    ids=[str(i) for i in range(len(rows))]
    answer=choose(ctx,ctx.actor,'move_'+str(feet),ids,{str(i):f'Move to ({c.destination.x}, {c.destination.y}) without provoking' for i,c in enumerate(rows)},f'{ctx.actor.display_name}: move up to {feet} feet without provoking, or stay.',minimum=0,decline=True) if rows else []
    if answer:move(ctx.engine,ctx.actor,rows[int(answer[0])],ctx.intent,feet,list(ctx.engine.state.actors),name='Spend Calamity')


def benefit(ctx,key,kind,target=None):
    from ..typed_executor import run_effects
    me=ctx.actor;pb=int(owned(ctx.engine,me)['pb'])
    sub=replace(ctx,target=target,targets=[target] if target else [me])
    if key in ('temp','blood_temp'):ctx.engine._grant_temp_hp(me,pb*(3 if key=='blood_temp' else 2),ctx.source,me.entity_id)
    elif key in ('move','move15'):movement(ctx,15 if key=='move15' else 10)
    elif key in ('fire_resist','cold_resist'):rule_condition(ctx,me,key,{'damage_resistances':['FIRE' if key=='fire_resist' else 'COLD']})
    elif key=='ac':run_effects(replace(ctx,target=me,targets=[me]),[{'type':'ac_bonus','applies_to':'self','flat':2,'expires_on':'START_OF_SELF_NEXT_TURN'}])
    elif key=='fly':rule_condition(ctx,me,'flight',{'fly_speed_ft':30},'END_OF_CURRENT_TURN')
    elif key=='root':rule_condition(ctx,me,'root',{'vessel_root':1})
    elif key=='obscured':rule_condition(ctx,me,'obscured',{'lightly_obscured':True})
    elif key=='spirit_guard':rule_condition(ctx,me,key,{'vessel_spirit_guard':1})
    elif key in ('damage','fire','force_damage') and target:
        kinds=['fire'] if key=='fire' else ['force'] if key=='force_damage' else DAMAGE[kind]
        run_effects(sub,[{'type':'extra_damage','applies_to':'target','dice':{'count':1,'sides':8},'damage_types':kinds}])
    elif key=='slow' and target:run_effects(sub,[{'type':'speed','applies_to':'target','flat':-15,'expires_on':'START_OF_SOURCE_NEXT_TURN'}])
    elif key=='reactions' and target:run_effects(sub,[{'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}])
    elif key=='storm_move' and target:
        from .general_combat_riders import directed_forced_movement
        directed_forced_movement(sub,{'type':'forced_movement','distance_ft':15,'relative_directions':['away','toward']})
    elif key=='blood_heal' and target:rule_condition(ctx,target,'healing',{'vessel_heal_minus':pb*2})
    elif key=='concentration' and target:rule_condition(ctx,target,'concentration',{'concentration_mode':'DISADVANTAGE','vessel_once_concentration':1})
    elif key=='see_shadow' and target:rule_condition(ctx,target,'seen',{'vessel_seen_by':me.entity_id})
    elif key=='armament':
        from .qi_path import armament_condition,armament_point,armament_control_range,move_armament
        from ..gate2_runtime_models import Position
        if not armament_condition(me):return
        old=armament_point(me)
        points=[Position(x=x,y=y) for x in range(ctx.engine.grid.width) for y in range(ctx.engine.grid.height) if ctx.engine.grid.distance_ft(old,(x,y))<=20 and ctx.engine.grid.distance_ft(me.position,(x,y))<=armament_control_range(ctx.engine,me) and ctx.engine.grid.placement_legal((x,y),occupied_cells=set())]
        ids=[str(i) for i in range(len(points))]
        answer=choose(ctx,me,'armament',ids,{str(i):f'Move Domain Armament to ({p.x}, {p.y})' for i,p in enumerate(points)},'Move your Domain Armament up to 20 feet.',minimum=0,decline=True)
        if answer:move_armament(ctx.engine,me,points[int(answer[0])],ctx.source,distance_ft=20,require_clear_route=True)


@hook('before_target_reactions')
def spend(ctx):
    row=owned(ctx.engine,ctx.actor)
    if not row or ctx.action.parameters.get('calamity_profile') or ctx.action.parameters.get('vessel_operation')==NAMES[0]:return
    d=state(ctx.engine,ctx.actor)
    if not d['charges'] or d.get('spent_turn')==stamp(ctx.engine):return
    # Native Qi costs and explicit Cultivation Attack metadata are authority;
    # damage type, technique name or narration never creates that category.
    if not any(pool==QI and cost>0 for pool,cost in ctx.action.costs) and not ctx.typed.get('cultivation_attack') and ctx.source!=F+NAMES[2]:return
    ids=[c['id'] for c in d['charges']]
    selected=choose(ctx,ctx.actor,'spend',ids,{c['id']:f"Spend one {c['type']} Charge" for c in d['charges']},'Spend Calamity: one Charge, once per turn. It is spent even on a miss or successful save.',minimum=0,decline=True)
    if not selected:return
    charge=next(c for c in d['charges'] if c['id']==selected[0]);normal=choose(ctx,ctx.actor,'normal',list(NORMAL),NORMAL,'Choose the normal Spend Calamity benefit.')[0]
    benefits=[normal]
    if walking(d):
        opts={**NORMAL,**TEMPER[charge['type']]};opts.pop(normal,None)
        benefits+=choose(ctx,ctx.actor,'walking_benefit',list(opts),opts,'Walking Tribulation: choose a different second normal or typed benefit.')
    elif row['cl']>=6:
        opts=TEMPER[charge['type']]
        benefits+=choose(ctx,ctx.actor,'tempered',list(opts),opts,f"Calamity Tempering: choose the additional {charge['type']} benefit.")
    d['charges']=[c for c in d['charges'] if c['id']!=charge['id']];d['spent_turn']=stamp(ctx.engine)
    d['pending']={'intent':ctx.intent.intent_id,'kind':charge['type'],'benefits':benefits,'done':[]}
    store(ctx.engine,ctx.actor,d)
    immediate={'temp','blood_temp','move','move15','fire_resist','cold_resist','ac','fly','root','obscured','spirit_guard','armament'}
    for key in benefits:
        if key in immediate:benefit(ctx,key,charge['type'])


@hook('damage_dealt')
def spent_damage(ctx,target,amount):
    if not owned(ctx.engine,ctx.actor) or amount<=0:return
    d=state(ctx.engine,ctx.actor);p=d.get('pending',{})
    if p.get('intent')!=ctx.intent.intent_id:return
    eligible={'damage','fire','force_damage','slow','reactions','storm_move','blood_heal','concentration','see_shadow'}
    keys=[x for x in p['benefits'] if x in eligible and x not in p['done']]
    if not keys:return
    p['done']+=keys;store(ctx.engine,ctx.actor,d) # fence recursive extra damage
    for key in keys:benefit(ctx,key,p['kind'],target)


@hook('forced_movement_bonus')
def spent_forced(ctx,subject,effect):
    if not owned(ctx.engine,ctx.actor):return
    d=state(ctx.engine,ctx.actor);p=d.get('pending',{})
    if p.get('intent')!=ctx.intent.intent_id:return
    # Pure query: one chosen movement is sealed by the first native delivery.
    return sum(15 if x=='force15' else 10 for x in p.get('benefits',[]) if x in ('force','force15')) or None


@hook('check_bonus')
def spent_check(ctx,actor):
    if not owned(ctx.engine,actor):return
    d=state(ctx.engine,actor);p=d.get('pending',{})
    if p.get('intent')==ctx.intent.intent_id and 'check' in p.get('benefits',[]) and 'check' not in p['done']:
        p['done'].append('check');store(ctx.engine,actor,d);return int(owned(ctx.engine,actor)['pb'])


@hook('resistance_ignored')
def spent_penetration(engine,kind,typed,source_actor_id,target):
    actor=engine.state.actors.get(source_actor_id)
    if not actor or not owned(engine,actor):return
    p=state(engine,actor).get('pending',{})
    if kind.lower()=='force' and 'penetrate' in p.get('benefits',[]):return True
    scar=state(engine,actor).get('scar_release')
    if scar and kind.lower() in DAMAGE[scar]:return True


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
    elif kind=='Storm':benefit(ctx,'storm_move',kind,target)
    elif kind=='Force':run_effects(sub,[{'type':'condition','condition':'prone','applies_to':'target'}])
    elif kind=='Gravity':run_effects(sub,[{'type':'speed','becomes':0,'applies_to':'target','expires_on':until}])
    elif kind=='Blood':rule_condition(ctx,target,'healing',{'vessel_heal_minus':3*int(ctx.numbers['pb'])})
    elif kind=='Shadow':rule_condition(ctx,target,'reveal',{'vessel_reveal':1})
    elif kind=='Spirit':benefit(ctx,'concentration',kind,target)


@effect('vessel_release')
def release(ctx,effect):
    from ..typed_executor import run_effects
    d=state(ctx.engine,ctx.actor);row=owned(ctx.engine,ctx.actor)
    ids=[c['id'] for c in d['charges']]
    require(ids,'Tribulation Release requires genuine Calamity Charges.')
    selected=choose(ctx,ctx.actor,'release_charges',ids,{c['id']:f"{c['type']} Charge" for c in d['charges']},f"Tribulation Release: spend 1 to {row['pb']} Charges.",maximum=min(row['pb'],len(ids)))
    charges=[c for c in d['charges'] if c['id'] in selected]
    kinds=sorted({c['type'] for c in charges});damage=sorted({k for t in kinds for k in DAMAGE[t]})
    damage_types=choose(ctx,ctx.actor,'release_damage',damage,{k:k.capitalize() for k in damage},'Choose one represented damage type, or divide the damage between two represented types.',maximum=min(2,len(damage)) if len(kinds)>1 else 1)
    ability=choose(ctx,ctx.actor,'release_save',['dex','con'],{'dex':'Dexterity saving throw','con':'Constitution saving throw'},'Choose the Tribulation Release saving throw.')[0]
    if not (walking(d) and d.get('free_release')!=stamp(ctx.engine)):
        require(ctx.actor.resources.get(QI,0)>=3,'Tribulation Release costs 3 Qi.')
        ctx.engine._spend_resource(ctx.actor,QI,3,ctx.source)
    else:d['free_release']=stamp(ctx.engine)
    d['charges']=[c for c in d['charges'] if c['id'] not in selected]
    store(ctx.engine,ctx.actor,d)
    # Choose creatures from the already legal native area; never widen it.
    ids=[t.entity_id for t in ctx.targets]
    selected_targets=choose(ctx,ctx.actor,'release_targets',ids,{t.entity_id:t.display_name for t in ctx.targets},'Choose creatures affected by the 30-foot Tribulation Release.',minimum=0,maximum=len(ids),automatic=[t.entity_id for t in ctx.targets if t.team_id!=ctx.actor.team_id]) if ids else []
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
    run_effects(replace(ctx,damage_divisor=1 if failed else 2),[{'type':'damage','applies_to':'target','dice':{'count':effect['count'],'sides':8},'damage_types':effect['damage_types'],'damage_bonus_group':'vessel_release'}])
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
        d['sequence']+=1;d['charges'].append({'id':str(d['sequence']),'type':kind,'source_cl':owned(ctx.engine,ctx.actor)['cl'],'overflow':1,'event':ctx.intent.intent_id})
    d.update(walking={'remaining':10},scene_used=1,twice=0)
    store(ctx.engine,ctx.actor,d)


@hook('damage_defenses')
def defenses(engine,target,kind,typed,source_actor_id):
    if not owned(engine,target) or not walking(state(engine,target)):return
    if kind.upper() in ('ACID','COLD','FIRE','LIGHTNING','THUNDER'):return [{'kind':'resistance','damage_types':[kind]}]
    source=engine.state.actors.get(source_actor_id)
    source_id=(typed or {}).get('source','')
    action=next((a for a in engine.action_catalog.values() if (a.parameters.get('typed') or {}).get('source')==source_id),None)
    environmental=bool(action and action.parameters.get('calamity_profile'))
    cultivation=bool(source_id.startswith(('tianxia.path.','tianxia.subpath.','tianxia.sphere.')))
    if kind.upper() in ('BLUDGEONING','PIERCING','SLASHING') and (environmental or cultivation):return [{'kind':'resistance','damage_types':[kind]}]


@hook('turn_start_choice')
def start(engine,actor):
    for owner in engine.state.actors.values():
        if not owned(engine,owner):continue
        d=state(engine,owner)
        if walking(d) and actor.team_id!=owner.team_id and engine._distance_actor_to_actor(owner,actor)<=15:aura(engine,owner,actor)
    if not owned(engine,actor):return
    ctx=context(engine,actor)
    if ctx and 0<actor.current_hp*2<actor.maximum_hp and any(t.active and t.team_id!=actor.team_id for t in engine.state.actors.values()):collect(ctx,actor,'below_half:'+stamp(engine))
    d=state(engine,actor)
    if walking(d):
        d['walking']['remaining']-=1
        if d['walking']['remaining']<=0:end_walk(engine,actor,d)
        else:store(engine,actor,d)


@hook('movement_step')
def aura_entry(engine,actor,previous,nxt,intent):
    for owner in engine.state.actors.values():
        if owner is actor or owner.team_id==actor.team_id or not owned(engine,owner):continue
        if walking(state(engine,owner)) and engine.grid.distance_ft(previous,owner.position)>15 and engine.grid.distance_ft(nxt,owner.position)<=15:aura(engine,owner,actor)


def aura(engine,owner,target):
    from ..typed_executor import run_effects
    d=state(engine,owner);key='aura:'+stamp(engine)+':'+target.entity_id
    if key in d.get('aura_events',[]) or not d['charges']:return
    ctx=context(engine,owner,F+NAMES[4])
    if not ctx:return
    kinds=sorted({c['type'] for c in d['charges']})
    kind=choose(ctx,owner,key,kinds,{k:k for k in kinds},f'Calamity Aura: choose a represented type against {target.display_name}.')[0]
    damage=choose(ctx,owner,key+':damage',DAMAGE[kind],{k:k.capitalize() for k in DAMAGE[kind]},'Choose Calamity Aura damage type.')[0]
    d.setdefault('aura_events',[]).append(key);store(engine,owner,d)
    run_effects(replace(ctx,target=target,targets=[target]),[{'type':'save','ability':'dex','on_fail':[{'type':'damage','applies_to':'target','dice':{'count':3,'sides':8},'damage_types':[damage]},{'type':'vessel_aura_rider','kind':kind}],'on_success':[{'type':'half_damage','applies_to':'target','damage_types':[damage]}]}])


@effect('vessel_aura_rider')
def aura_rider(ctx,effect):rider(ctx,effect['kind'],ctx.target)


def end_walk(engine,actor,d):
    from ..gate2_runtime_models import DiceSpec
    from ..typed_executor import run_effects
    extra=max(0,len(d['charges'])-3)
    d.pop('walking',None)
    d['charges']=[c for c in d['charges'] if not c.get('overflow')][:maximum(owned(engine,actor))]
    store(engine,actor,d)
    if extra:
        roll=engine.roller.roll(DiceSpec(count=extra,sides=8),actor_id=actor.entity_id,reason='Vessel Breaks Before the Calamity');engine._record_roll(roll)
        # This is an ordinary committed damage packet; the source-qualified
        # defense/reduction hooks expressly exclude this own feature backlash.
        engine._commit_damage(actor,int(roll.total),'FORCE',F+'vessel_breaks',actor.entity_id,getattr(engine,'_active_intent',None),reaction_depth=0)


def furnace_ready(engine,actor):
    row=owned(engine,actor)
    if not row or row['cl']<14 or not actor.reaction_available:return False
    d=state(engine,actor)
    return d.get('furnace_round')!=engine.state.round_number and len(d['charges'])>=(1 if walking(d) else 2)


def pay_furnace(engine,actor,*,reaction=True):
    from ..typed_reactions import spend_reaction,publish_reaction_used
    d=state(engine,actor);cost=1 if walking(d) else 2
    del d['charges'][:cost];d['furnace_round']=engine.state.round_number
    store(engine,actor,d)
    if reaction:
        row={'feature_id':F+NAMES[3],'name':'Furnace Response'}
        spend_reaction(engine,actor,row);publish_reaction_used(engine,actor,row)


def scar(engine,actor,source_id,source_actor_id):
    ctx=context(engine,actor,F+NAMES[3])
    if not ctx:return
    source=engine.state.actors.get(source_actor_id)
    action=engine.action_catalog.get(source_id)
    p=action.parameters.get('calamity_profile') if action else None
    if p:kind=p['type'];cl=p['source_cl'];name=p['name']
    else:
        answer=choose(ctx,actor,'scar_type',list(TYPES),{k:k for k in TYPES},'Scar of Authority: choose the triggering effect’s closest Calamity Type.')
        if not answer:return
        kind=answer[0];cl=int((getattr(engine,'typed_actor_numbers',{}).get(source_actor_id,{}) or {}).get('cl') or owned(engine,actor)['cl']);name=action.display_name if action else 'Observed effect'
    d=state(engine,actor);d['scar']={'type':kind,'source_cl':cl,'technique':source_id or '', 'name':name};store(engine,actor,d)


@hook('source_damage_reduction')
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
    if reduced>=amount:scar(engine,target,source_id,source_actor_id)
    return reduced


@hook('forced_movement_restriction')
def root(engine_ctx,subject,effect,maximum_ft):
    ctx=engine_ctx
    if any(c.condition_id=='condition:typed.vessel_root' for c in subject.conditions.values()):return 0
    if maximum_ft<=0 or not furnace_ready(ctx.engine,subject):return
    answer=choose(ctx,subject,'root_against_heaven',['root'],{'root':'Spend Charges and your Reaction: prevent this forced movement and its Prone'},f'Furnace Response: Root Against Heaven for {subject.display_name}?',minimum=0,decline=True)
    if not answer:return
    pay_furnace(ctx.engine,subject)
    d=state(ctx.engine,subject);d['root_intent']=ctx.intent.intent_id;store(ctx.engine,subject,d)
    scar(ctx.engine,subject,ctx.action.source_definition_id,ctx.actor.entity_id)
    return 0


@hook('condition_attempt')
def prevent_prone(ctx,subject,effect):
    if str(effect.get('condition','')).lower()!='prone' or not owned(ctx.engine,subject):return
    if any(c.condition_id=='condition:typed.vessel_root' for c in subject.conditions.values()) or state(ctx.engine,subject).get('root_intent')==ctx.intent.intent_id:return False


@hook('condition_applied')
def burn_binding(ctx,name,subject):
    if name not in ('grappled','restrained') or not furnace_ready(ctx.engine,subject):return
    opts={'str':'Strength check with Advantage','dex':'Dexterity check with Advantage','cultivation':'Cultivation Check with Advantage'}
    answer=choose(ctx,subject,'burn_binding',list(opts),opts,f'Furnace Response: spend Charges and your Reaction to escape {name} with Advantage?',minimum=0,decline=True)
    if not answer:return
    pay_furnace(ctx.engine,subject)
    conditions=[c for c in subject.conditions.values() if c.condition_id=='condition:typed.'+name]
    # An existing origin save controls its repeated save; only effects with no
    # escape procedure use the printed Strength/Dexterity/Cultivation fallback.
    from ..gate2_runtime_models import DiceSpec
    row=owned(ctx.engine,subject);ability=answer[0]
    existing=next((c.data.get('origin_save') or c.data.get('repeat_save') for c in conditions if c.data.get('origin_save') or c.data.get('repeat_save')),None)
    dc=int((existing or {}).get('dc') or ctx.numbers.get('save_dc') or 10)
    bonus=int(subject.saving_throws.get(str(existing.get('ability','CON')).upper(),0)) if existing else int(row['pb'])+int(row['key_mod']) if ability=='cultivation' else int(subject.ability_modifiers.get(ability.upper(),0))
    roll=ctx.engine.roller.roll(DiceSpec(count=1,sides=20,modifier=bonus),actor_id=subject.entity_id,reason='Furnace Response: Burn the Binding',mode='ADVANTAGE');ctx.engine._record_roll(roll)
    if roll.total>=dc:
        for c in conditions:remove_instance(ctx.engine,subject,c.instance_id,F+NAMES[3])
        scar(ctx.engine,subject,ctx.action.source_definition_id,ctx.actor.entity_id)


def furnace_holders(engine):
    from .d20_rewrite import Holder
    for actor in engine.state.actors.values():
        if furnace_ready(engine,actor):yield Holder(actor,F+NAMES[3],{},F+NAMES[3],owned(engine,actor))


def reverse_after(engine,holder,rc,roll,bonus):
    pay_furnace(engine,holder.actor,reaction=False)
    if rc.dc is not None and int(roll.total)>=rc.dc:scar(engine,holder.actor,rc.source_id,getattr(rc.source_actor,'entity_id',None))


def register_furnace():
    from .d20_rewrite import Rule,register
    register(Rule('vessel_reverse_save','Furnace Response: Reverse the Save',finder=furnace_holders,feature=F+NAMES[3],reaction=True,when='failed',additive_save_bonus=lambda e,h,r:int(h.numbers['pb']),after_bonus=reverse_after,guard=lambda e,h,r:furnace_ready(e,h.actor)))
register_furnace()


@hook('save')
def spirit_saves(ctx,subject,ability,named):
    if any(c.condition_id=='condition:typed.vessel_spirit_guard' for c in subject.conditions.values()) and set(named or ())&{'charmed','frightened','possession','soul_displacement'}:return {'bonus':0,'modes':['ADVANTAGE']}


@hook('flight')
def flight(engine,actor):
    if any(c.condition_id=='condition:typed.vessel_flight' for c in actor.conditions.values()):return {'fly_speed_ft':30}


@hook('healing_pending')
def healing(engine,subject,amount,healer,source,kind):
    for c in list(subject.conditions.values()):
        rule=c.data.get('rule') or {}
        if rule.get('vessel_heal_minus') and amount>0:
            remove_instance(engine,subject,c.instance_id,c.source_definition_id)
            return min(amount,int(rule['vessel_heal_minus']))


@hook('masked_conditions')
def reveal(engine,attacker,target):
    out={}
    for who,viewer in ((attacker,target),(target,attacker)):
        if any((c.data.get('rule') or {}).get('vessel_reveal') or (c.data.get('rule') or {}).get('vessel_seen_by')==viewer.entity_id for c in who.conditions.values()):
            out[who.entity_id]={iid for iid,c in who.conditions.items() if c.condition_id in ('condition:typed.invisible','condition:typed.hidden')}
    return out or None


@hook('journey_encounter_settled')
def export(session,actor_id,engine,actor):
    if owned(engine,actor):session.state['actors'][actor_id].setdefault('source_states',{}).setdefault(P,{})['ledger']=state(engine,actor)


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
    for key in ('scar','scar_release','walking','pending'):d.pop(key,None)
    d['charges']=[];data['ledger']=d
    snapshot=session.state['actors'][actor_id].get('encounter_snapshot',{})
    for iid,raw in list(snapshot.get('conditions',{}).items()):
        c=json.loads(raw)
        if c['condition_id']==LEDGER:
            c['data']['ledger']=json.dumps(d,sort_keys=True);snapshot['conditions'][iid]=json.dumps(c,sort_keys=True)


@hook('journey_scene_end')
def scene_end(session,old,new):
    for actor in session.state['actors'].values():
        data=actor.get('source_states',{}).get(P)
        if data:data.get('ledger',{}).pop('scene_used',None)


@hook('effect_origins')
def origins(engine,actor,action):
    if action.parameters.get('vessel_operation')!=NAMES[2] or not owned(engine,actor):return None
    from .qi_path import armament_condition,armament_point
    if walking(state(engine,actor)):
        return [{'id':f'vessel:{x}:{y}','label':f'Tribulation Release from ({x}, {y})','position':{'x':x,'y':y}}
            for x in range(engine.grid.width) for y in range(engine.grid.height)
            if engine.grid.distance_ft(actor.position,(x,y))<=30 and engine.grid.line_of_sight(actor.position,(x,y))]
    if armament_condition(actor):
        x,y=armament_point(actor)
        return [{'id':'vessel:armament','label':'Tribulation Release from your Domain Armament','position':{'x':x,'y':y}}]
