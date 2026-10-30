"""Cremation Cinder Heart's source-owned native progression.

Uses source-scoped fact admission, journey acquisition/continuation, native
conditions, damage, zones, Anchor objects and choice checkpoints. No ownership
means no resource, action, declaration or mutation. Subjective significance is
an explicit table-owner declaration, never inferred from damage or names.
"""
from copy import deepcopy
from dataclasses import replace
import json
from . import hook, effect
from ..journey import require
from ..fact_consent_admission import read, canonical

PARENT='tianxia.subpath.qi.cremation_cinder_heart'
BASE='tianxia.subpath.qi.cinder_heart_cultivator'
FEATURES=tuple(PARENT+'.feature.'+n for n in ('cremation_furnace_core','ash_sentence','burn_the_scripture','cremation_prison','cremate_heaven_and_earth'))
OLD=tuple(BASE+'.feature.'+n for n in ('cinder_touch','heart_of_the_forge','promethean_gift','ashen_rebirth','cinder_sovereign_s_wrath'))
LEVELS=(3,6,10,14,18)
QI='resource:core.qi'; ASH='resource:named.ash_charge'; BLOCK='cremation_cinder_heart'
PREFIX='condition:typed.cremation.'
SENTENCE=PREFIX+'sentence'; SEALED=PREFIX+'sealed'; SCRIPTURE=PREFIX+'scripture'; LEDGER=PREFIX+'ledger'; FIELD=PREFIX+'field'; FINAL=PREFIX+'final'; FUNERAL=PREFIX+'funeral'


def owned(engine,actor,index=0):
    return next((r for r in getattr(engine,'typed_passive_rows',{}).get(actor.entity_id,()) if r.get('block')==BLOCK and FEATURES[index] in r['features']),None)


def conditions(actor,cid):return [c for c in actor.conditions.values() if c.condition_id==cid]
def one(actor,cid):return next(iter(conditions(actor,cid)),None)


@hook('observer_information')
def learned_burn_information(engine, observer):
    """Deliver Burn's owner-only failed-check finding through perception's channel."""
    from ..observer_information import READING
    rows = []
    for condition in observer.conditions.values():
        if condition.condition_id != READING or condition.data.get('viewer_id') != observer.entity_id:
            continue
        if condition.data.get('authority_actor_id') != observer.entity_id:
            continue
        details = condition.data.get('details') or {}
        if not {'source_cl', 'category', 'effect_name'} <= set(details):
            continue
        text = (f"Burn the Scripture revealed {details['effect_name']}: Source CL "
                f"{details['source_cl']}; authority category {details['category']}.")
        rows.append({'kind': 'declaration', 'viewer_id': observer.entity_id,
            'authority_actor_id': observer.entity_id, 'source_id': condition.source_definition_id,
            'text': text, 'details': {'text': text}})
    return rows or None


def admitted_facts(actor):
    """Only still-live native declaration conditions supply combat facts."""
    result={}
    for condition in sorted(conditions(actor,PREFIX+'facts'),key=lambda c:json.loads(c.data['record'])['sequence']):
        record=json.loads(condition.data['record'])
        from ..fact_consent_admission import digest
        require(record['receipt_id']==digest({k:v for k,v in record.items() if k!='receipt_id'}),'The Cremation fact failed its native replay commitment.')
        value=record['value'];identity=value.get('actor_id') or value.get('object_id')
        result.setdefault(identity,{}).update(value)
    return result
def sovereign(actor):return one(actor,FIELD) is not None


def final_fields(engine,actor,target):
    """Every live activation has its own Final allowance and target geometry."""
    from .. import zones
    if target is None or not any(c.source_actor_id==actor.entity_id for c in conditions(target,SENTENCE)):return []
    return [c for c in conditions(actor,FIELD) if not c.data.get('final_used')
        and (z:=engine.state.zones.get(c.data['zone'])) is not None and z.active and zones.actor_inside_zone(engine,target,z)]


def store_field(engine,actor,source,data):
    # The linked zone owns expiry. Updating one marker must not rebind it to
    # another activation's current concentration or remove another marker.
    for c in list(conditions(actor,FIELD)):
        if c.data['zone']==data['zone']:engine._remove_condition_instance(actor,c.instance_id,source,expected=c)
    engine._apply_condition(actor,FIELD,source,actor.entity_id,expires_on='UNTIL_REMOVED',data=data)


def hostile(engine,owner,target):
    from ..relations import relation,ENEMY
    return relation(engine,owner,target)==ENEMY

def put(engine,actor,cid,source,owner,data,expiry='UNTIL_REMOVED'):
    from .owned_effects import remove_conditions
    remove_conditions(engine,actor,source,owner,cid)
    engine._apply_condition(actor,cid,source,owner,expires_on=expiry,data=data)


def ask(ctx,key,options,labels,prompt,*,decline=False,chooser=None):
    from .needle import ask as choose,checkpoint_id
    if not options:return []
    return choose(ctx.engine,ctx.intent or getattr(ctx.engine,'_active_intent',None),checkpoint_id(ctx.engine,'cremation',key,ctx.source),chooser or ctx.actor,
        'choice:needle.cremation.'+key,options,labels=labels,prompt=prompt,name='Cremation Cinder Heart',feature_id=FEATURES[0],
        allow_decline=decline,minimum=0 if decline else 1,default='decline' if decline else 'first')


def context(engine,actor,source,targets=()):
    from .states import context as make
    row=owned(engine,actor)
    ctx=make(engine,actor,source,list(targets),row['numbers'] if row else {})
    from .source_eligibility import catalog_action
    native=catalog_action(engine,source) or next((a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id and (a.parameters.get('typed') or {}).get('source')==source),None)
    if native is not None and native.owner_id==actor.entity_id:
        ctx.action=native;ctx.typed={**deepcopy(native.parameters.get('typed') or {}),'numbers':dict(row['numbers']) if row else {}}
    ctx.intent=getattr(engine,'_active_intent',None)
    return ctx


def turn_key(engine):return f'{engine.state.round_number}:{engine.state.current_actor_id}:{engine.state.actors[engine.state.current_actor_id].turns_started}'

def ledger(actor):
    c=one(actor,LEDGER)
    return json.loads(c.data['ledger']) if c else {'scene':'','generated':[],'round':-1,'touch':'','sentence':'','ash_turn':'','benefits':[],'heaven_used':0}


def save_ledger(engine,actor,data):
    put(engine,actor,LEDGER,FEATURES[0],actor.entity_id,{'ledger':canonical(data),'label':'Cremation furnace: Ash and source clocks'})


def qualifying_subject(ctx,subject):
    from .passive_rows import known_level
    from ..fact_consent_admission import combat_records,admit_choice
    if ctx.engine.state.actors.get(subject.entity_id) is not subject or not hostile(ctx.engine,ctx.actor,subject) or subject.owner_id==ctx.actor.entity_id:return False
    facts=admitted_facts(ctx.actor).get(subject.entity_id,{})
    level=known_level(ctx.engine,subject)
    if level is None:level=facts.get('source_cl')
    if type(level) is not int or level<int(ctx.numbers['cl'])-5:return False
    if 'genuine_threat' in facts and 'farmed' in facts:return facts['genuine_threat']==1 and facts['farmed']==0
    scope=ledger(ctx.actor).get('scene','')+':'+subject.entity_id
    stored=combat_records(ctx.engine,ctx.actor,source=FEATURES[0],kind='ash_qualifying_subject',scope=scope)
    if stored:return stored[-1]['value']=='eligible'
    record=admit_choice(ctx,ctx.actor,FEATURES[0],'ash_qualifying_subject',scope,['eligible','ineligible'],
        labels={'eligible':subject.display_name+' was a genuine threat and was not farmed','ineligible':subject.display_name+' does not qualify'},
        prompt='Ash Charges: was '+subject.display_name+' a genuine threat, not a harmless bystander or consenting training target, and not created, captured, repeatedly revived or preserved solely to produce Charges? Native CL and control restrictions still apply.',
        expires_on='UNTIL_REMOVED',automatic_options=[])
    return record is not None and record['value']=='eligible'


def gain(ctx,identity,*,explicit=False,qualifying_actor=None):
    actor=ctx.actor
    if actor.resources.get(ASH,0)>=actor.resource_maximums.get(ASH,0):return False
    state=ledger(actor);round_no=ctx.engine.state.round_number
    subject=ctx.engine.state.actors.get(identity) or ctx.target
    if not explicit and subject is not None and ctx.engine._distance_actor_to_actor(actor,subject)>60:return False
    clock='escape_round' if explicit else 'round'
    if identity in state['generated'] or state.get(clock,-1)==round_no:return False
    creature=qualifying_actor or ctx.engine.state.actors.get(identity)
    if creature is not None and not qualifying_subject(ctx,creature):return False
    state['generated'].append(identity);state[clock]=round_no
    save_ledger(ctx.engine,actor,state)
    ctx.engine._gain_resource(actor,ASH,1,ctx.source)
    return True


@hook('compile_passives')
def compile_ownership(rows,info):
    ids=set(info['owned_ids']); selected=ids.intersection(FEATURES)
    if not selected:return rows
    require(not any(i.startswith(BASE+'.feature.') for i in ids),'Cinder Heart and Cremation Cinder Heart progressions cannot coexist.')
    cl=int(qi_numbers(info)['cl'])
    require(all(cl>=LEVELS[FEATURES.index(i)] for i in selected),'Cremation progression requires its printed Cultivation Level.')
    return [r for r in rows if r.get('feature_id') not in FEATURES]+[{'block':BLOCK,'feature_id':f,'trigger_owner':BLOCK,'features':sorted(selected),'numbers':dict(info['numbers'])} for f in sorted(selected)]


@hook('compile_resources')
def compile_ash(info):
    if FEATURES[0] not in info['owned_ids']:return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=ASH,initial=0,maximum=int(info['numbers']['pb']))]


def action(info,index,label,operation,*,economy='ACTION',cost=0,target='ANY_CREATURE',reach=60,area=None):
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    typed={'source':FEATURES[index],'numbers':qi_numbers(info),'effects':[{'type':'cremation_operation','operation':operation}],
        'duration':({'kind':'one_minute','concentration':True} if area else {'kind':'instant'}),'riders':[],'qi_powered':True,'manual_inline_choice':True}
    if area:
        typed['area']={'shape':'cylinder','size_ft':area,'height_ft':area,'placed':1}
        if operation in ('prison','heaven'):
            typed['visual']={'material':'ash'}
    return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.cremation.{operation}",display_name=label,owner_id=info['actor_id'],
        economy=EconomyKind(economy),resolution_kind='TYPED',target_kind=target,range_ft=reach,costs=((QI,cost),) if cost else (),
        concentration=bool(area),radius_ft=area,parameters={'cremation_operation':operation,'typed':typed,**({'setting_only':True} if operation in ('prepare','scripture_prepare') else {})})


@hook('compile_actions')
def compile_actions(info):
    ids=set(info['owned_ids']);out=[]
    if FEATURES[0] in ids:
        out.append(action(info,0,'Spend Ash: prepare next Qi feature','prepare',economy='NONE',target='SELF',reach=0))
    if FEATURES[1] in ids:out.append(action(info,1,'Ash Sentence — triggered, 2 Qi','sentence_trigger',economy='NONE',cost=2))
    if FEATURES[2] in ids:
        out.extend([action(info,2,'Burn the Scripture — 5 Qi, or 3 Qi in the sovereign furnace','burn',cost=5),
            action(info,2,'Burn the Scripture — sovereign Bonus Action, 3 Qi','burn_bonus',cost=3,economy='BONUS_ACTION')])
    if FEATURES[3] in ids:out.append(action(info,3,'Cremation Prison — 6 Qi, concentration, 1 minute','prison',cost=6,target='CELL',reach=90,area=20))
    if FEATURES[4] in ids:
        out.extend([action(info,4,'Cremate Heaven and Earth — 10 Qi, concentration, 1 minute','heaven',cost=10,target='CELL',reach=120,area=40),
            action(info,4,'Final Cremation — once during this furnace','final',economy='NONE',reach=120)])
    return out or None


@hook('compile_bundle')
def remove_legacy(bundle,info):
    # Replace legacy inferred rows, keeping a single source-owned implementation.
    if not any(r.get('block')==BLOCK for r in bundle.get('passives',[])) and not any(a.get('parameters',{}).get('cremation_operation') for a in bundle.get('action_catalog',[])):return None
    out=deepcopy(bundle)
    numbers=qi_numbers(info)
    for passive in out.get('typed_passives',[]):
        if passive.get('block')==BLOCK:passive['numbers']=dict(numbers)
    out['actor_template']['resources']=[r for r in out['actor_template']['resources'] if r.get('resource_id')!='resource:named.scripture_ash']
    out['action_catalog']=[a for a in out['action_catalog'] if (a.get('parameters',{}).get('typed') or {}).get('source') not in FEATURES or a.get('parameters',{}).get('cremation_operation')]
    for native in out['action_catalog']:
        if native.get('parameters',{}).get('cremation_operation') in ('prison','heaven'):
            native['parameters']['typed'].pop('zone_spec',None)
    out['actor_template']['action_ids']=[a['source_definition_id'] for a in out['action_catalog']]
    out['typed_reactions']=[r for r in out.get('typed_reactions',[]) if r.get('feature_id') not in FEATURES]
    return out


@hook('damage_defenses')
def defenses(engine,actor,damage_type,typed,source_actor_id):
    if not owned(engine,actor):return None
    return ([{'kind':'immunity','damage_types':['fire']},{'kind':'resistance','damage_types':['necrotic','radiant']}] if sovereign(actor) else [{'kind':'resistance','damage_types':['fire']}])


def qi_powered(ctx):
    t=ctx.typed
    if 'cremation_fire' in ctx.damage_source_flags:return True
    if t.get('qi_powered') is False:return False
    alignment=t.get('technique_alignment') or {}
    if alignment.get('resource_id'):return alignment['resource_id']==QI
    from ..typed_executor import CP_POOLS
    paid={pool for pool,amount in ctx.action.costs if amount and pool in CP_POOLS}
    if paid:return QI in paid
    if t.get('qi_powered') is True:return True
    return QI in dict(ctx.action.costs) or 'qi' in t.get('tags',()) or str(t.get('source','')).startswith(('tianxia.path.qi_cultivation.','tianxia.subpath.qi.'))


def fire(ctx,target,count=0,sides=8,flat=0,*,half=False,source=None):
    from .. import typed_executor as te
    selected=ask(ctx,'fire_type',['FIRE','NECROTIC'],{'FIRE':'Fire Cremation Fire','NECROTIC':'Necrotic Cremation Fire'},f'Cremation Fire: choose Fire or Necrotic damage for {target.display_name}.')
    kinds=selected or ['FIRE']
    fx={'type':'damage','damage_types':[kinds[0].lower()],'flat':flat,'applies_to':'target'}
    if count:fx['dice']={'count':count,'sides':sides}
    child=replace(ctx,targets=[target],target=target,damage_source_flags=(*ctx.damage_source_flags,'cremation_fire'),effect_source=source or ctx.effect_source or ctx.source,damage_cache={'_potency_used':True,**({'_cremation_zone':ctx.damage_cache['_cremation_zone']} if '_cremation_zone' in ctx.damage_cache else {})})
    if half:
        amount,kind=te._damage_roll(child,fx);te._deal(child,target,amount,kind,divisor=2)
    else:te.run_effects(child,[fx])


def sealed(ctx,target,expiry,*,sentence=False,full=True):
    reduce_healing=sentence or full
    end=('until the start of '+ctx.actor.display_name+'’s next turn' if sentence and not full else
        'for up to 1 minute; repeat Constitution save at each turn’s end' if sentence else
        'until the end of '+target.display_name+'’s next turn' if expiry.startswith('END_OF_TURN_AT:') else
        'until the start of '+target.display_name+'’s next turn')
    name='Ash Sentence' if sentence else 'World-Ash Judgment' if ctx.typed.get('source')==FEATURES[4] else 'Cremation Prison'
    label=name+': '+target.display_name+' cannot gain Temporary Hit Points'
    if reduce_healing:label+=f'; healing reduced by {int(ctx.numbers["pb"])}'
    if full:label+='; takes Cremation Fire damage equal to Cultivation Points spent'
    data={'pb':int(ctx.numbers['pb']),'numbers':dict(ctx.numbers),'full':int(full),'reduce_healing':int(reduce_healing),'label':label+' '+end,
        # deny_temp_hp is the typed-effect word used by displays and the authority
        # table; the engine's rule reader consumes temp_hp_denied
        # (typed_executor.condition_rules -> gate2_engine._grant_temp_hp).
        'rule':{'deny_temp_hp':True,'temp_hp_denied':True}}
    put(ctx.engine,target,SENTENCE if sentence else SEALED,ctx.source,ctx.actor.entity_id,data,expiry)


@hook('healing_pending')
def healing(engine,target,amount,healer,source,kind):
    rows=[c for c in target.conditions.values() if c.condition_id in (SENTENCE,SEALED)]
    if not rows:return None
    if kind=='temp_hp':return amount
    rows=[c for c in rows if c.data.get('reduce_healing',1)]
    return min(amount,sum(max(c.data['pb'] for c in rows if c.source_actor_id==aid) for aid in {c.source_actor_id for c in rows}))


@hook('damage_dealt')
def damage_trigger(ctx,target,amount):
    if amount<=0 or not owned(ctx.engine,ctx.actor):return
    ctx=replace(ctx,typed={**ctx.typed,'numbers':dict(owned(ctx.engine,ctx.actor)['numbers'])})
    state=ledger(ctx.actor);now=turn_key(ctx.engine)
    cremation='cremation_fire' in ctx.damage_source_flags
    if qi_powered(ctx) and state['touch']!=now:
        if ask(ctx,'touch',['touch'],{'touch':f'Deal additional Cremation Fire damage to {target.display_name}'},f'Cremation Touch: {target.display_name} was damaged by {ctx.action.display_name}. Add '+('4d8' if sovereign(ctx.actor) else str(ctx.numbers['pb']))+' damage, once per turn?',decline=True):
            state['touch']=now;save_ledger(ctx.engine,ctx.actor,state)
            fire(ctx,target,4 if sovereign(ctx.actor) else 0,flat=0 if sovereign(ctx.actor) else int(ctx.numbers['pb']),source=FEATURES[0])
    if cremation and owned(ctx.engine,ctx.actor,1):
        state=ledger(ctx.actor)
        used=state['benefits'] if state['ash_turn']==now else []
        ash_discount=ctx.actor.resources.get(ASH,0)>0 and 'discount' not in used and len(used)<(2 if sovereign(ctx.actor) else 1)
        if state['sentence']!=now and ctx.actor.resources.get(QI,0)>=(1 if ash_discount else 2) and ask(ctx,'sentence',['sentence'],{'sentence':f'Pay 2 Qi: Ash Sentence on {target.display_name}'},f'Ash Sentence: your Cremation Fire damaged {target.display_name}. Pay 2 Qi; Constitution save; healing reduction and no Temporary Hit Points; failed save also burns spent Cultivation Points for up to 1 minute.',decline=True):
            trigger=next(a for a in ctx.engine.action_catalog.values() if a.owner_id==ctx.actor.entity_id and a.parameters.get('cremation_operation')=='sentence_trigger')
            child=replace(ctx,action=trigger,typed=deepcopy(trigger.parameters['typed']),targets=[target],target=target,effect_source=None,damage_cache={})
            prepare_activation(ctx.engine,ctx.actor,trigger,None,ctx.intent or getattr(ctx.engine,'_active_intent',None))
            if ctx.engine._can_pay(ctx.actor,trigger.costs,source_id=trigger.source_definition_id):
                state=ledger(ctx.actor);state['sentence']=now;save_ledger(ctx.engine,ctx.actor,state)
                ctx.engine._spend_costs(ctx.actor,trigger.costs,trigger.source_definition_id)
                spend_prepared(ctx.engine,ctx.actor,trigger)
                consume_scripture(ctx.engine,ctx.actor,trigger)
                from .. import typed_executor as te
                te.run_effects(child,[{'type':'save','ability':'con','on_fail':[{'type':'cremation_sentence','full':1}], 'on_success':[{'type':'cremation_sentence','full':0}]}])
    if cremation and any(int(p.get('hp_before',0))>0 and p.get('remaining_hp')==0 for p in ctx.damage_packets):
        if cremation:
            if ctx.engine._distance_actor_to_actor(ctx.actor,target)<=60:gain(ctx,target.entity_id)


@effect('cremation_sentence')
def sentence_effect(ctx,row):
    target=ctx.target;full=bool(row['full'])
    sealed(ctx,target,minute_expiry(ctx.engine) if full else f'START_OF_TURN_AT:{ctx.actor.entity_id}:{ctx.actor.turns_started+1}',sentence=True,full=full)


@hook('state_event')
def point_damage(engine,event):
    if event.event_type!='RESOURCE_SPENT' or event.payload.get('amount',0)<=0:return
    from ..typed_executor import CP_POOLS
    if event.payload.get('resource_id') not in CP_POOLS:return
    target=engine.state.actors.get(event.actor_id)
    if target is None:return
    seen=set()
    for c in [*conditions(target,SENTENCE),*conditions(target,SEALED)]:
        if not c.data.get('full') or c.source_actor_id in seen:continue
        seen.add(c.source_actor_id)
        owner=engine.state.actors.get(c.source_actor_id)
        if owner and owned(engine,owner):fire(context(engine,owner,c.source_definition_id,[target]),target,flat=event.payload['amount'])


@hook('turn_end')
def repeat_sentence(engine,actor):
    from .. import typed_executor as te
    for c in list(conditions(actor,SENTENCE)):
        if not c.data['full']:continue
        owner=engine.state.actors.get(c.source_actor_id)
        if owner is None:continue
        ctx=context(engine,owner,c.source_definition_id,[actor])
        te.run_effects(ctx,[{'type':'save','ability':'con','on_fail':[], 'on_success':[{'type':'cremation_end_sentence','instance':c.instance_id}]}])


@effect('cremation_end_sentence')
def end_sentence(ctx,row):
    c=ctx.target.conditions.get(row['instance'])
    if c:ctx.engine._remove_condition_instance(ctx.target,c.instance_id,ctx.source,payload={'condition_id':SENTENCE,'instance_id':c.instance_id,'reason':'SAVE'},expected=c)


@hook('candidate_allowed')
def candidate_gate(engine,actor,candidate,action):
    if action is None:return None
    op=action.parameters.get('cremation_operation')
    if op is None:return None
    row=owned(engine,actor)
    if not row:return False
    if op=='sentence_trigger':return False
    if op in ('burn','burn_bonus'):
        target=engine.state.actors.get(next(iter(candidate.target_ids),''))
        if target is None or not burnable(context(engine,actor,candidate.source_definition_id),target):return False
    if op=='scripture_prepare' and one(actor,SCRIPTURE) is None:return False
    if op=='prepare':
        state=ledger(actor);used=state['benefits'] if state['ash_turn']==turn_key(engine) else []
        if not actor.resources.get(ASH,0) or len(used)>=(2 if sovereign(actor) else 1):return False
    if op=='burn_bonus' and (not sovereign(actor) or actor.turn_flags.get('typed_once_turn:cremation_burn_bonus')):return False
    if op=='heaven' and ledger(actor)['heaven_used']:return False
    if op=='final':
        target=engine.state.actors.get(next(iter(candidate.target_ids),''))
        if not final_fields(engine,actor,target):return False
    return None


@effect('cremation_operation')
def operation(ctx,row):
    op=row['operation']
    if op=='prepare':prepare(ctx)
    elif op=='scripture_prepare':scripture_prepare(ctx,{})
    elif op.startswith('burn'):
        burn(ctx)
        if op=='burn_bonus':ctx.actor.turn_flags['typed_once_turn:cremation_burn_bonus']=True
    elif op in ('prison','heaven'):field(ctx,op)
    elif op=='final':final(ctx)


def prepare(ctx):
    state=ledger(ctx.actor);now=turn_key(ctx.engine)
    benefits=state['benefits'] if state['ash_turn']==now else []
    maximum=2 if sovereign(ctx.actor) else 1
    choices=['damage','discount','temp_hp','move','armament','reveal']
    choices=[s for s in choices if s not in benefits]
    from .qi_path import armament_condition
    if armament_condition(ctx.actor) is None:choices.remove('armament') if 'armament' in choices else None
    if len(benefits)>=maximum or ctx.actor.resources.get(ASH,0)<1:return
    labels={'damage':'Add 1d8 Cremation Fire damage to one damage roll','discount':'Reduce Qi cost by 1, minimum 1','temp_hp':f'Gain {2*int(ctx.numbers["pb"])} Temporary Hit Points','move':'Move 10 feet without Opportunity Attacks','armament':'Move your Domain Armament 20 feet','reveal':'One damaged target sheds visible ash until your next turn'}
    pick=ask(ctx,'spend_ash',choices,labels,'Spend Ash: prepare one benefit for the next Qi-powered activation. It costs one Ash Charge when that feature activates. A single activation spends at most one Charge.',decline=True)
    if pick:put(ctx.engine,ctx.actor,PREFIX+'prepared',FEATURES[0],ctx.actor.entity_id,{'benefit':pick[0],'label':'Prepared Spend Ash: '+labels[pick[0]]})


@hook('technique_cost_discount')
def discounts(engine,actor,source,costs):
    if not owned(engine,actor):return None
    action=engine.action_catalog.get(source)
    if action is None:return None
    cut=2 if sovereign(actor) and (action.parameters.get('typed') or {}).get('source')==FEATURES[2] and action.parameters.get('cremation_operation')=='burn' else 0
    prepared=one(actor,PREFIX+'prepared')
    if prepared and prepared.data['benefit']=='discount' and actor.resources.get(ASH,0):
        state=ledger(actor);used=state['benefits'] if state['ash_turn']==turn_key(engine) else []
        if 'discount' not in used and len(used)<(2 if sovereign(actor) else 1):cut+=1
    return {QI:min(max(0,costs.get(QI,0)-1),cut)} if cut and QI in costs else None


@hook('technique_start')
def spend_prepared(engine,actor,action):
    if not owned(engine,actor) or action.parameters.get('cremation_operation')=='prepare':return None
    ctx=context(engine,actor,action.source_definition_id)
    ctx.action=action;ctx.typed=action.parameters.get('typed') or {}
    if not qi_powered(ctx):return None
    c=one(actor,PREFIX+'prepared');state=ledger(actor);now=turn_key(engine)
    benefits=state['benefits'] if state['ash_turn']==now else []
    if c and actor.resources.get(ASH,0) and len(benefits)<(2 if sovereign(actor) else 1) and c.data['benefit'] not in benefits:
        from .. import typed_executor as te
        kind=c.data['benefit'];engine._remove_condition(actor,PREFIX+'prepared',FEATURES[0]);engine._spend_resource(actor,ASH,1,FEATURES[0])
        state.update(ash_turn=now,benefits=[*benefits,kind]);save_ledger(engine,actor,state)
        if kind=='temp_hp':engine._grant_temp_hp(actor,2*int(ctx.numbers['pb']),FEATURES[0],actor.entity_id)
        elif kind=='move':te.run_effects(ctx,[{'type':'rider_step','distance_ft':10,'no_oa':True,'label':'Spend Ash'}])
        elif kind=='armament':
            from .devil_heart_second_furnace import move_armament_choice
            move_armament_choice(ctx,actor,20,feature_id=FEATURES[0],name='Spend Ash')
        elif kind in ('damage','reveal'):
            intent=getattr(engine,'_active_intent',None)
            engine._apply_condition(actor,PREFIX+'activation',action.source_definition_id,actor.entity_id,data={'kind':kind,'source':action.source_definition_id,'activation_intent':intent.intent_id if intent else '', 'zones':[], 'label':'Spend Ash for one damage roll or damaged target of this feature'},expires_on='UNTIL_REMOVED')
    return None


@hook('technique_used')
def finish_activation(ctx):
    c=next((c for c in conditions(ctx.actor,PREFIX+'activation') if c.data['source']==ctx.source and activation_matches(ctx,c)),None)
    if c and c.data['source']==ctx.source:
        if c.data['kind']=='reveal':
            damaged={t for e in ctx.engine.events[ctx.technique_event_start or 0:] if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==ctx.actor.entity_id and e.payload.get('hp_damage',0)+e.payload.get('temporary_hp_absorbed',0)>0 for t in e.target_ids}
            options=sorted(damaged)
            pick=ask(ctx,'ash_reveal',options,{a:ctx.engine.state.actors[a].display_name for a in options},'Spend Ash: choose one damaged creature. Its visible ash prevents Invisible and ordinary concealment from hiding it from you until your next turn.')
            if pick:put(ctx.engine,ctx.engine.state.actors[pick[0]],PREFIX+'revealed',FEATURES[0],ctx.actor.entity_id,{'label':'Visible ash reveals this creature to its cremator'},f'START_OF_TURN_AT:{ctx.actor.entity_id}:{ctx.actor.turns_started+1}')
        if not c.data.get('zones'):ctx.engine._remove_condition_instance(ctx.actor,c.instance_id,FEATURES[0],expected=c)


def source_profile(ctx,item):
    from .end_effect import source_action,source_cl
    action=source_action(ctx,item)
    if action is None:return None
    typed=action.parameters.get('typed') or {};numbers=typed.get('numbers') or {}
    from .source_eligibility import printed_source_tags
    types=set();tags=set(printed_source_tags(action))
    def visit(value):
        if isinstance(value,dict):
            types.update(str(t).upper() for t in value.get('damage_types') or ())
            tags.update(value.get('source_tags') or ())
            for v in value.values():visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    visit(typed.get('effects') or [])
    source=str(typed.get('option_of') or typed.get('source') or '')
    category=next((name for token,name in (('.subpath.','Subpath'),('.path.','Path'),('.sphere.','Sphere'),('.method.','Method'),('.foundation.','Foundation'),('.item.','item'),('.formation.','Formation'),('.bloodline.','bloodline')) if token in source),'another recorded category')
    data=getattr(item,'data',{}) or {}
    from ..observer_information import source_profile as native_profile
    profile=native_profile(ctx.engine,item.source_definition_id,data)
    types.update(str(t).upper() for t in profile.get('damage_types') or [])
    visit(data)
    if typed.get('sphere'):category='Sphere'
    level=profile.get('source_cl') or data.get('source_cl') or typed.get('source_cl') or numbers.get('cl')
    require(type(level) is int and level>=1,'Burn the Scripture requires the selected effect’s recorded Source CL.')
    save_dc=(data.get('origin_save') or {}).get('dc') or profile.get('save_dc')
    if save_dc is None:
        save_dc=8+int(numbers.get('pb',0))+int(numbers.get('key_mod',0))
    return {'name':action.display_name,'cl':level,'dc':int(save_dc),
        'types':sorted(types),'tags':sorted(tags),'category':category,'source':source}


def burnable(ctx,target):
    from .end_effect import source_action
    from ..senses import perceives as can_see
    if target is not ctx.actor and not can_see(ctx.engine,ctx.actor,target):return []
    from . import query
    from ..concentration import is_recipient_effect
    from ..observer_information import readings
    hidden={iid for ids in query('presentation_hidden_conditions',ctx.engine,target) for iid in ids}
    known={r.get('details',{}).get('source_instance') for r in readings(ctx.engine,ctx.actor)}
    result=[]
    for kind,store in (('condition',target.conditions),('modifier',target.modifiers)):
        for key,item in store.items():
            if kind=='condition' and not is_recipient_effect(item):continue
            if kind=='condition' and item.data.get('hidden') and key not in known and item.source_actor_id!=ctx.actor.entity_id:continue
            if key in hidden and key not in known and item.source_actor_id!=ctx.actor.entity_id:continue
            if kind=='condition' and item.condition_id.startswith('condition:typed.suppressed.'):continue
            if kind=='modifier' and item.target_field.startswith('suppressed:'):continue
            if item.expires_on in (None,'UNTIL_REMOVED') and not (kind=='condition' and item.data.get('maintained')):continue
            if source_action(ctx,item) is None:continue
            profile=source_profile(ctx,item)
            if profile:result.append((kind,key,item,profile))
    from .. import zones
    for zone in ctx.engine.state.zones.values():
        if not zone.active or not zones.actor_inside_zone(ctx.engine,target,zone):continue
        action=ctx.engine.action_catalog.get(zone.source_definition_id)
        if action is None:continue
        typed=action.parameters.get('typed') or {};native=zone.trigger_profile.get('source_profile') or {};numbers=zone.trigger_profile.get('numbers') or {}
        level=native.get('source_cl') or numbers.get('cl')
        if type(level) is not int:continue
        types=set(str(t).upper() for t in native.get('damage_types') or [])
        def visit(value):
            if isinstance(value,dict):
                types.update(str(k).upper() for k in value.get('damage_types',[]))
                for v in value.values():visit(v)
            elif isinstance(value,list):
                for v in value:visit(v)
        visit(zone.trigger_profile.get('triggers',[]))
        profile={'name':str(zone.trigger_profile.get('name') or action.display_name),'cl':level,'dc':int(native.get('save_dc') or numbers.get('save_dc') or (8+int(numbers.get('pb',0))+int(numbers.get('key_mod',0)))),
            'types':sorted(types),'tags':list(native.get('source_tags') or []),'category':str(native.get('source_category') or ('Formation' if native.get('authority')=='Formation' else 'another recorded category')),'source':str(typed.get('source') or '')}
        result.append(('zone',zone.zone_id,zone,profile))
    return result


def burn(ctx):
    target=ctx.target
    if target is None:return
    rows=burnable(ctx,target)
    from ..canonical import canonical_sha256
    keys=['cremation-effect:'+canonical_sha256({'viewer':ctx.actor.entity_id,'instance':i})[:24] for k,i,_,_ in rows]
    pick=ask(ctx,'burn_effect',keys,{option:p['name'] for option,(_,_,_,p) in zip(keys,rows)},f'Burn the Scripture: choose one active perceived effect on {target.display_name}; Constitution save, then a Cultivation Check. Lower Source CL ends; equal suppresses 1 minute; higher suppresses until your next turn ends.')
    if not pick:return
    kind,key,item,profile=rows[keys.index(pick[0])]
    from .. import typed_executor as te
    te.run_effects(ctx,[{'type':'save','ability':'con','on_fail':[{'type':'cremation_burn_result','kind':kind,'key':key,'profile':profile}],
        'on_success':[{'type':'cremation_fire_damage','count':3,'sides':8}]}])


@effect('cremation_fire_damage')
def fire_effect(ctx,row):
    fire(ctx,ctx.target,row.get('count',0),row.get('sides',8),row.get('flat',0),half=bool(row.get('half')))


@effect('cremation_burn_result')
def burn_result(ctx,row):
    from .ability_source import cultivation_check
    from .end_effect import remove_instance,suppress
    target=ctx.target;kind=row['kind'];key=row['key'];profile=row['profile']
    item=(ctx.engine.state.zones if kind=='zone' else target.conditions if kind=='condition' else target.modifiers).get(key)
    if item is None:return
    if not cultivation_check(ctx.engine,ctx.actor,ctx.numbers,profile['dc'],ctx.source,'Burn the Scripture Cultivation Check'):
        from ..observer_information import publish
        publish(ctx.engine,ctx.actor,ctx.source,ctx.actor,'declaration',{'source_cl':profile['cl'],'category':profile['category'],'effect_name':profile['name']},'UNTIL_REMOVED')
        return
    cl=int(ctx.numbers['cl'])
    if kind=='zone':
        burn_zone(ctx,target,item,profile)
        return
    from ..concentration import made_at,is_recipient_effect
    from .suppressed_effects import lifetime
    def activation(row_id,value):
        clock=lifetime(ctx.engine,target,value)
        if clock.get('cast'):return ('cast',clock['cast'])
        sequence=made_at(row_id,value)
        event=next((e for e in ctx.engine.events if e.sequence==sequence),None)
        return ('intent',event.transaction_id,event.trigger_or_intent_id) if event and event.transaction_id else ('instance',row_id)
    selected_activation=activation(key,item)
    group=[(k,i,x) for k,store in (('condition',target.conditions),('modifier',target.modifiers)) for i,x in list(store.items()) if x.source_definition_id==item.source_definition_id and x.source_actor_id==item.source_actor_id and x.expires_on==item.expires_on and is_recipient_effect(x) and activation(i,x)==selected_activation]
    if profile['cl']<cl:
        for k,i,x in group:remove_instance(ctx,target,k,i,x)
    else:
        for k,i,x in group:suppress(target,k,i,x,rounds=10 if profile['cl']==cl else 1,by=ctx.actor,engine=ctx.engine,expires_on=minute_expiry(ctx.engine) if profile['cl']==cl else None)
        if profile['cl']==cl:
            ctx.engine._apply_condition(target,PREFIX+'burn_repeat',ctx.source,ctx.actor.entity_id,data={'kind':kind,'key':key,'keys':[i for k,i,x in group],'label':'Burn the Scripture: repeat Constitution save at turn end','numbers':dict(ctx.numbers)},expires_on=minute_expiry(ctx.engine))
    gain(ctx,'effect:'+item.source_actor_id+':'+kind+':'+key)
    store_scripture(ctx,profile)


@hook('turn_end')
def repeat_burn(engine,actor):
    from .. import typed_executor as te
    for c in conditions(actor,PREFIX+'burn_repeat'):
        owner=engine.state.actors.get(c.source_actor_id)
        if owner:
            ctx=context(engine,owner,c.source_definition_id,[actor])
            te.run_effects(ctx,[{'type':'save','ability':'con','on_fail':[],'on_success':[{'type':'cremation_restore_effect','instance':c.instance_id}]}])


@effect('cremation_restore_effect')
def restore_effect(ctx,row):
    from .end_effect import restore_suppressed
    target=ctx.target;c=target.conditions.get(row['instance'])
    if not c:return
    if c.data.get('zone'):
        from .area_suppression import restore_record
        zone=ctx.engine.state.zones.get(c.data['zone'])
        if zone:restore_record(ctx.engine,zone,c.data['record_key'])
    for saved in list(target.turn_flags.get('typed_round_suppressed',[])):
        if saved.get('key') in c.data.get('keys',[c.data.get('key','')]):restore_suppressed(ctx.engine,target,saved)
    ctx.engine._remove_condition_instance(target,c.instance_id,ctx.source,expected=c)


def field(ctx,kind):
    from .. import zones
    heaven=kind=='heaven';size=40 if heaven else 20
    # Native zones own concentration, duration, entry/start trigger accounting.
    spec={'name':'Cremate Heaven and Earth' if heaven else 'Cremation Prison','shape':'cylinder','size_ft':size,'height_ft':size,'placed':1,
        'duration':{'kind':'one_minute','concentration':True},'profile':{'cremation':kind},
        'visual':dict(ctx.typed.get('visual') or {}),
        'triggers':[{'id':'cremation_judgment','on':['enter','start'],'who':'any','effects':[{'type':'cremation_judgment','heaven':int(heaven)}]}]}
    from ..zone_sources import compile_profile
    spec['source_profile']={**compile_profile({**ctx.typed,'effects':[{'type':'zone','mundane':False}]},{},spec['duration']),
        'damage_types':['FIRE','NECROTIC'],'source_category':'Subpath'}
    zone=zones.create(ctx,spec)
    if not zone:return
    if heaven:
        state=ledger(ctx.actor);state['heaven_used']=1;save_ledger(ctx.engine,ctx.actor,state)
        store_field(ctx.engine,ctx.actor,ctx.source,{'zone':zone.zone_id,'final_used':0,'label':'Sovereign cremation furnace: 1 minute, concentration'})
    else:
        from ..asset_anchor_runtime import create
        obj=create(ctx.engine,ctx.actor,ctx.source,{'name':'Furnace Anchor','kind':'CULTIVATION_ANCHOR','ac':17,'hp':5*int(ctx.numbers['cl']),
            'source_cl':int(ctx.numbers['cl']),'height_ft':5,'group':zone.zone_id,'resist':['BLUDGEONING','PIERCING','SLASHING','FIRE','NECROTIC'],'immune':['POISON','PSYCHIC']},zone.center,
            component={'cremation_zone':zone.zone_id,'blocks':False})


@effect('cremation_judgment')
def judgment(ctx,row):
    if not hostile(ctx.engine,ctx.actor,ctx.target):return
    source=FEATURES[4] if row['heaven'] else FEATURES[3]
    now=turn_key(ctx.engine)
    if any(c.source_actor_id==ctx.actor.entity_id and c.source_definition_id==source and c.data.get('turn')==now for c in conditions(ctx.target,PREFIX+'judgment_used')):return
    put(ctx.engine,ctx.target,PREFIX+'judgment_used',source,ctx.actor.entity_id,{'turn':now,'label':'This creature has resolved this cultivator’s furnace judgment this turn'},'END_OF_CURRENT_TURN')
    from .. import typed_executor as te
    te.run_effects(ctx,[{'type':'save','ability':'con','on_fail':[{'type':'cremation_judgment_result','heaven':row['heaven'],'failed':1}],
        'on_success':[{'type':'cremation_judgment_result','heaven':row['heaven'],'failed':0}]}])


def system_label(system):
    """Return the player's public name for a stored cultivation-system key."""
    if system.startswith('tianxia.sphere.'):
        import json
        from ..factory_compiler import TYPED_AUTHORITY
        names=json.loads(TYPED_AUTHORITY.read_bytes()).get('sphere_names') or {}
        return names.get(system) or system.rsplit('.',1)[-1].replace('_',' ').title()
    return system.replace('_',' ').title()



@effect('cremation_judgment_result')
def judgment_result(ctx,row):
    target=ctx.target;heaven=bool(row['heaven']);failed=bool(row['failed'])
    fire(ctx,target,8 if heaven else 5,half=not failed)
    expiry=f'END_OF_TURN_AT:{target.entity_id}:{target.turns_started+1}' if heaven and failed else f'START_OF_TURN_AT:{target.entity_id}:{target.turns_started+1}'
    sealed(ctx,target,expiry,full=heaven or failed)
    if failed:
        put(ctx.engine,target,PREFIX+'prison_lock',ctx.source,ctx.actor.entity_id,{'label':'Cremation Prison prevents teleport, Incorporeal movement and spirit departure','rule':{'no_teleport':True,'no_incorporeal':True,'no_spirit_projection':True}},expiry)
    if failed and heaven:
        systems=active_systems(ctx,target)
        chosen=ask(ctx,'scorch',systems,{s:system_label(s) for s in systems},f'World-Ash Judgment: choose one perceived active cultivation system on {target.display_name}. It is suppressed until the end of its next turn.')
        if chosen:
            system=chosen[0]
            put(ctx.engine,target,PREFIX+'system_scorched',ctx.source,ctx.actor.entity_id,{'system':system,'label':'World-Ash Judgment suppresses '+system_label(system),
                'flight_disabled':int(system=='flight'),'rule':{'no_teleport':system=='teleportation'}},expiry)
            scorch_ongoing(ctx,target,system,expiry)


def active_systems(ctx,actor):
    """Choice knowledge is the cremator's, never the target's whole catalog.

    Ongoing perceived effects derive their system from their actual native
    source. A table-owner perception declaration can admit other known systems;
    it cannot grant a system that the target does not mechanically possess.
    """
    available=set()
    for aid in actor.action_ids:
        action=ctx.engine.action_catalog.get(aid)
        if action:available.update(action_systems(action))
    perceived=set(admitted_facts(ctx.actor).get(actor.entity_id,{}).get('systems',[]))
    for kind,key,item,profile in burnable(ctx,actor):
        action=ctx.engine.action_catalog.get(item.source_definition_id)
        if action:perceived.update(action_systems(action))
    if actor is ctx.actor:perceived.update(available)
    return sorted(available.intersection(perceived))


def action_systems(action):
    typed=action.parameters.get('typed') or {};source=str(typed.get('option_of') or typed.get('source') or '')
    result=set(typed.get('cultivation_systems') or [])
    for token,name in (('.subpath.','subpath_features'),('.method.','method_active_features'),('.foundation.','foundation_active_features'),('.item.','item_activations')):
        if token in source:result.add(name)
    if typed.get('sphere'):result.add(str(typed['sphere']))
    if typed.get('weapon'):result.add('weapon_delivered_techniques')
    if action.parameters.get('armament'):result.add('domain_armament')
    from .qi_path import GOLDEN,SECOND_GOLDEN,ARMAMENT,NASCENT_SOUL
    if source in (GOLDEN,SECOND_GOLDEN):result.add('golden_core_form')
    if source==ARMAMENT:result.add('domain_armament')
    if source==NASCENT_SOUL:result.add('nascent_soul_continuity')
    types=effect_types(action)
    if types.intersection({'flight','fly','flight_mode'}):result.add('flight')
    if types.intersection({'teleport','teleport_steps'}):result.add('teleportation')
    return result


def scorch_ongoing(ctx,target,system,expiry):
    """Suppress represented live pieces through the public native APIs.

    This is the selected source system, rather than an unrelated effect on the
    bearer. Original clocks keep ageing under the existing suppression reader.
    """
    from .end_effect import suppress,source_action
    for kind,store in (('condition',target.conditions),('modifier',target.modifiers)):
        for key,item in list(store.items()):
            if kind=='condition' and item.condition_id.startswith(PREFIX):continue
            action=source_action(ctx,item)
            if action and system in action_systems(action):
                suppress(target,kind,key,item,rounds=1,by=ctx.actor,engine=ctx.engine,expires_on=expiry)
    from .. import zones
    from .area_suppression import suppress as suppress_area
    for zone in list(ctx.engine.state.zones.values()):
        action=ctx.engine.action_catalog.get(zone.source_definition_id)
        if zone.active and zone.owner_id==target.entity_id and action and system in action_systems(action):
            suppress_area(ctx.engine,ctx.actor,zone,expiry,ctx.source)


@hook('candidate_allowed')
def scorch_gate(engine,actor,candidate,action):
    if action is None:return None
    if any(c.data['system'] in action_systems(action) for c in conditions(actor,PREFIX+'system_scorched')):return False
    from ..typed_executor import CP_POOLS
    if one(actor,FINAL) and any(r in CP_POOLS and n for r,n in action.costs):return False
    return None


def final(ctx):
    from .. import typed_executor as te
    target=ctx.target;fields=final_fields(ctx.engine,ctx.actor,target)
    if not fields:return
    keys=[c.data['zone'] for c in fields]
    labels={c.data['zone']:f'Furnace centered at square {ctx.engine.state.zones[c.data["zone"]].center.x}, {ctx.engine.state.zones[c.data["zone"]].center.y}: Final Cremation on {target.display_name}' for c in fields}
    selected=ask(ctx,'final_furnace',keys,labels,'Final Cremation: choose the active furnace whose once-per-activation use to spend.') if len(fields)>1 else keys
    if not selected:return
    field=fields[keys.index(selected[0])]
    data=dict(field.data);data['final_used']=1
    store_field(ctx.engine,ctx.actor,field.source_definition_id,data)
    te.run_effects(ctx,[{'type':'save','ability':'con','on_fail':[{'type':'cremation_final_result','failed':1}],
        'on_success':[{'type':'cremation_final_result','failed':0}]}])


@hook('save')
def final_modes(ctx,target,ability,named):
    if (ctx.action.parameters.get('cremation_operation')!='final' or ability!='CON'):return None
    from .passive_rows import known_level
    level=known_level(ctx.engine,target);own=int(ctx.numbers['cl'])
    if level is None:
        level=admitted_facts(ctx.actor).get(target.entity_id,{}).get('source_cl')
    require(level is not None,'Final Cremation requires the target’s recorded Source CL; the native table owner must supply unknown cultivation authority before resolution.')
    return {'bonus':0,'modes':['ADVANTAGE'] if level>own else ['DISADVANTAGE'] if level<=own-6 else []}


@effect('cremation_final_result')
def final_result(ctx,row):
    target=ctx.target;failed=bool(row['failed']);fire(ctx,target,12,10,half=not failed)
    if failed:
        put(ctx.engine,target,FINAL,ctx.source,ctx.actor.entity_id,{'label':'Final Cremation suppresses all Cultivation Point expenditure'},f'END_OF_TURN_AT:{target.entity_id}:{target.turns_started+1}')
        if target.current_hp==0:
            sovereign_ash(ctx,target)
            for previous in list(conditions(target,FUNERAL)):
                if previous.source_actor_id==ctx.actor.entity_id:ctx.engine._remove_condition_instance(target,previous.instance_id,ctx.source,expected=previous)
            put(ctx.engine,target,FUNERAL,FEATURES[4],ctx.actor.entity_id,{'dc':int(ctx.numbers['save_dc']),'cl':int(ctx.numbers['cl']),'sovereign':1,'failed_methods':[],
                'label':'Sovereign ash: restoration requires a Cultivation Check until scene end; true soul and protected existence remain'},'UNTIL_REMOVED')


@hook('state_event')
def anchor_lifecycle(engine,event):
    if event.event_type not in ('OBJECT_UPDATED','ZONE_REMOVED'):return
    from .. import zones
    for obj in list(engine.state.objects.values()):
        zid=(obj.component or {}).get('cremation_zone')
        if not zid:continue
        zone=engine.state.zones.get(zid)
        if obj.destroyed and zone and zone.active:zones.remove(engine,zone,'ANCHOR_DESTROYED')
        elif not obj.destroyed and (zone is None or not zone.active):
            from ..asset_anchor_runtime import retire
            retire(engine,obj,obj.component['created_by'])
    for actor in engine.state.actors.values():
        for c in list(conditions(actor,FIELD)):
            if c.data['zone'] not in engine.state.zones or not engine.state.zones[c.data['zone']].active:engine._remove_condition_instance(actor,c.instance_id,c.source_definition_id,expected=c)


@hook('object_damage_defenses')
def anchor_defenses(engine,actor,obj,packets,source):
    if not (obj.component or {}).get('cremation_zone'):return None
    return [{'kind':'resistance','damage_types':list((obj.component or {}).get('resist',()))}]


@hook('fact_admission_schema')
def admission_schema(session,source,subject,kind):
    if source!=PARENT or subject not in session.state['actors']:return None
    if kind in ('source_access','remains','qualifying_subject','qualifying_object','source_authority','perceived_systems'):
        return {'value_type':'document','maximum_seconds':2592000,'authority':'table_owner','description':'Source-scoped native world-owner declaration of legal access or meaningful remains/threat provenance.'}
    if kind=='conversion_environment':return {'value_type':'flag','maximum_seconds':28800,'description':'Confirm an actual calm ambient-Qi environment for a two-hour Cultivation Session.'}
    return None


def source_state(actor):return actor.setdefault('source_states',{}).setdefault(PARENT,{'sheet':'','training':0,'ash':0,'generated':[],'scene':'','facts':{}})


@hook('journey_acquisition')
def acquire(session,actor_id,source,payload,owner_sheet):
    if source!=PARENT:return None
    actor=session.state['actors'][actor_id];state=source_state(actor)
    require(not actor['incapacitated'],'An incapacitated creature cannot acquire this Variant.')
    access=read(session,PARENT,actor_id,'source_access',payload.get('access_scope',''),actor_id)
    require(access is not None,'The native table owner must grant legal Forbidden Variant access first.')
    value=access['value']
    require(set(value)=={'variant','route','source_rule'} and value['variant']==PARENT and value['route'] in ('direct','conversion') and type(value['source_rule']) is str and bool(value['source_rule'].strip()),'Name the Variant, entry route and legal Source Rule.')
    require(not state['sheet'],'This Variant is already acquired; acquisition cannot reset its limits.')
    sheet=deepcopy(owner_sheet);paths=sheet.get('path_and_subpath') or {};cl=int(sheet['identity']['cultivation_level']);pb=int(sheet['identity']['proficiency_bonus'])
    qi_path=next((r for r in paths.get('paths',[]) if r.get('path_id')=='tianxia.path.qi_cultivation'),{})
    qi_key=qi_path.get('key_ability') or sheet['identity']['key_ability']
    require(qi_key in ('INT','CHA'),'Qi Cultivation requires its chosen Intelligence or Charisma key ability.')
    require('tianxia.path.qi_cultivation' in [paths.get('path_record_id'),*(paths.get('path_record_ids') or [])],'Acquire the Qi Cultivation Path first.')
    level=next((int(r.get('attainment',0)) for r in paths.get('paths',[]) if r.get('path_id')=='tianxia.path.qi_cultivation'),0)
    require(3<=level<=cl,'Qi Path attainment, not overall CL alone, must reach 3.')
    ids=set(paths.get('path_feature_record_ids') or [])|set(paths.get('source_granted_subpath_feature_record_ids') or [])|set(paths.get('advancement_feature_record_ids') or [])
    ids.update(r['feature_id'] for r in paths.get('earned_feature_occurrences',[]) if r.get('feature_id'))
    parent=ids.intersection(OLD);selections=set(paths.get('subpath_record_ids') or [])
    if paths.get('subpath_record_id'):selections.add(paths['subpath_record_id'])
    selections.update(r.get('subpath_id','') for r in [*paths.get('subpaths',[]),*paths.get('bindings',[])] if r.get('owning_path_id',r.get('path_id'))=='tianxia.path.qi_cultivation')
    selections={sid for sid in selections if sid.startswith('tianxia.subpath.qi.')}
    if value['route']=='direct':require(not selections and not any(i.startswith('tianxia.subpath.qi.') for i in ids),'Direct Entry must be the first Qi Subpath choice.')
    else:require(parent and selections<={BASE} and all(i.startswith(BASE+'.feature.') for i in ids if i.startswith('tianxia.subpath.qi.')),'Conversion Entry requires the attained Cinder Heart parent alone on this Path.')
    procedure=payload.get('procedure','complete')
    if procedure=='train':
        require(value['route']=='conversion' and set(payload)=={'access_scope','procedure','environment_scope'},'Choose Conversion training and its actual environment.')
        environment=read(session,PARENT,actor_id,'conversion_environment',payload['environment_scope'],actor_id)
        require(environment and environment['value']==1,'Confirm calm ambient Qi for the Cultivation Session.')
        session.tick(7200)
        require(read(session,PARENT,actor_id,'conversion_environment',payload['environment_scope'],actor_id) is not None,'The actual cultivation environment expired during training.')
        state['training']+=1;session.emit('CREMATION_CONVERSION_SESSION',actor_id,source=source,seconds=7200)
        return {'sheet':None,'acquisition_id':access['receipt_id']}
    require(procedure=='complete' and set(payload)<={'access_scope','procedure'},'Choose the complete acquisition procedure.')
    if value['route']=='conversion':
        require(state['training']>=len(parent),'One completed Cultivation Session is required for every attained parent feature.')
        state['training']-=len(parent)
        from ..gate2_rolls import DeterministicRollAuthority
        roller=DeterministicRollAuthority(session.state['journey_id']+':cremation-conversion',counter=state.get('roll_counter',0))
        key=qi_key;mod=next(int(a['modifier']) for a in sheet['ability_scores_and_statistics']['abilities'] if a['ability']==key)
        roll=roller.d20(modifier=pb+mod,actor_id=actor_id,reason='CREMATION_CONVERSION');state['roll_counter']=roller.counter
        session.emit('CREMATION_CONVERSION_CHECK',actor_id,roll=canonical(roll.model_dump(mode='json')),dc=10+pb+len(parent),sessions_spent=len(parent))
        if roll.total<10+pb+len(parent):return {'sheet':None,'acquisition_id':access['receipt_id']}
    earned=[f for f,l in zip(FEATURES,LEVELS) if l<=level] if value['route']=='direct' else [f for old,f in zip(OLD,FEATURES) if old in parent]
    for field in ('path_feature_record_ids','source_granted_subpath_feature_record_ids','advancement_feature_record_ids'):
        paths[field]=list(dict.fromkeys([i for i in paths.get(field,[]) if not i.startswith(BASE+'.feature.')]+earned))
    paths['earned_feature_occurrences']=[r for r in paths.get('earned_feature_occurrences',[]) if not r.get('feature_id','').startswith(BASE+'.feature.')]
    paths['subpath_record_id']=PARENT;paths['subpath_record_ids']=[sid for sid in paths.get('subpath_record_ids',[]) if not sid.startswith('tianxia.subpath.qi.')]+[PARENT]
    subpath={'subpath_id':PARENT,'display_name':'Cremation Cinder Heart','owning_path_id':'tianxia.path.qi_cultivation','source_packet_ids':[access['receipt_id']]}
    paths['subpath']=subpath
    paths['subpaths']=[r for r in paths.get('subpaths',[]) if r.get('owning_path_id')!='tianxia.path.qi_cultivation']+[subpath]
    paths['bindings']=[r for r in paths.get('bindings',[]) if r.get('path_id')!='tianxia.path.qi_cultivation']+[{'path_id':'tianxia.path.qi_cultivation','subpath_id':PARENT,'source_packet_ids':[access['receipt_id']]}]
    paths['subpath_acquisition']={'route':value['route'],'access_receipt':access['receipt_id'],'path_level':level,'earned_features':earned,'replaced_features':sorted(parent),'source_rule':value['source_rule']}
    sheet['path_and_subpath']=paths;state['sheet']=canonical(sheet);state['ash']=0;state['scene']=session.state.get('scene_id',session.state['journey_id'])
    for recipient in session.state['actors'].values():
        snapshot=recipient.get('encounter_snapshot')
        if snapshot:
            for field in ('conditions','modifiers'):
                snapshot[field]={k:v for k,v in snapshot.get(field,{}).items() if not (json.loads(v).get('source_actor_id')==actor_id and json.loads(v).get('source_definition_id','').startswith(BASE+'.feature.'))}
    session.emit('CREMATION_SOURCE_ACQUIRED',actor_id,source=source,access_receipt=access['receipt_id'],earned_features=earned,replaced_features=sorted(parent))
    return {'sheet':sheet,'acquisition_id':access['receipt_id']}


@hook('journey_source_sheet')
def acquired_sheet(sheet,session,actor_id):
    saved=session.state['actors'][actor_id].get('source_states',{}).get(PARENT,{})
    if saved.get('sheet'):
        result=deepcopy(sheet);old=json.loads(saved['sheet'])['path_and_subpath'];current=deepcopy(result.get('path_and_subpath') or {})
        level=next((int(r.get('attainment',0)) for r in current.get('paths',[]) if r.get('path_id')=='tianxia.path.qi_cultivation'),0)
        prior=int(old['subpath_acquisition']['path_level'])
        extra=[f for f,l in zip(FEATURES,LEVELS) if prior<l<=level]
        earned=list(dict.fromkeys([i for i in old.get('source_granted_subpath_feature_record_ids',[]) if i in FEATURES]+extra))
        for key in ('path_feature_record_ids','source_granted_subpath_feature_record_ids','advancement_feature_record_ids'):
            current[key]=list(dict.fromkeys([i for i in current.get(key,[]) if not i.startswith(BASE+'.feature.') and i not in FEATURES]+earned))
        current['earned_feature_occurrences']=[r for r in current.get('earned_feature_occurrences',[]) if not r.get('feature_id','').startswith(BASE+'.feature.')]
        for key in ('subpath_record_id','subpath','subpath_acquisition'):
            if key in old:current[key]=deepcopy(old[key])
        current['subpath_record_ids']=list(dict.fromkeys([sid for sid in current.get('subpath_record_ids',[]) if not sid.startswith('tianxia.subpath.qi.')]+[PARENT]))
        current['subpaths']=[r for r in current.get('subpaths',[]) if r.get('owning_path_id')!='tianxia.path.qi_cultivation']+[deepcopy(old['subpath'])]
        current['bindings']=[r for r in current.get('bindings',[]) if r.get('path_id')!='tianxia.path.qi_cultivation']+[deepcopy(r) for r in old.get('bindings',[]) if r.get('path_id')=='tianxia.path.qi_cultivation']
        result['path_and_subpath']=current
        return result
    return None


def export(session,actor_id):
    actor=session.state['actors'][actor_id];state=actor.get('source_states',{}).get(PARENT)
    if state and (state.get('sheet') or state.get('effects')):
        state['clock']=int(session.clock())
        if state.get('sheet'):actor.setdefault('resources',{})[ASH]=int(state.get('ash',0))
        state['fact_records']={key:record for key,old in state.get('fact_records',{}).items() if (record:=read(session,PARENT,actor_id,old['kind'],old['scope'],actor_id)) is not None}
        actor['bundle'][BLOCK]=deepcopy(state)


@hook('journey_acquired')
def acquired(session,actor_id,source,acquisition_id):
    if source==PARENT:export(session,actor_id)


@hook('journey_initialize')
def initialize_journey(session,actor_id):
    saved=session.state['actors'][actor_id]['bundle'].get(BLOCK)
    if saved:
        saved=deepcopy(saved)
        # Deadlines are absolute in the previous journey. Rebase them onto
        # this journey's clock while preserving only their unelapsed time.
        previous_clock=int(saved.get('clock',0))
        for collection in ('effects','modifiers','fields'):
            for row in saved.get(collection,[]):
                if row.get('until',-1)>=0:
                    row['until']=max(0,int(row['until'])-previous_clock)
        saved['clock']=0
        session.state['actors'][actor_id].setdefault('source_states',{})[PARENT]=saved


@hook('journey_initialized')
def initialized(session):
    for aid in session.state['actors']:export(session,aid)


@hook('match_initialize')
def initialize_match(engine):
    for bundle in engine.typed_bundle_documents:
        saved=bundle.get(BLOCK);actor=engine.state.actors.get(bundle['actor_id'])
        if not saved or actor is None or not owned(engine,actor):continue
        desired=min(int(saved.get('ash',0)),actor.resource_maximums[ASH]);current=actor.resources[ASH]
        if desired>current:engine._gain_resource(actor,ASH,desired-current,FEATURES[0])
        elif current>desired:engine._spend_resource(actor,ASH,current-desired,FEATURES[0])
        data=ledger(actor);data.update(generated=list(saved.get('generated',[])),scene=saved.get('scene',''),heaven_used=int(saved.get('heaven_used',0)))
        save_ledger(engine,actor,data)
        from .effect_durations import round_token
        for record in saved.get('fact_records',{}).values():
            seconds=record['expires_at']-saved.get('clock',0)
            if seconds<=0:continue
            engine._apply_condition(actor,PREFIX+'facts',FEATURES[0],actor.entity_id,expires_on=round_token(engine,max(1,(seconds+5)//6)),
                data={'record':canonical(record),'label':'Source-scoped world declaration; authority, privacy, receipt and expiry retained'})


def cremated_remains(session,identity):
    """Family physical producer shared by all native cultivators in this journey.

    A scene boundary or a second declaration cannot recreate consumed remains.
    A new significant residue is a separately identified world-owner fact.
    """
    for native in session.state['actors'].values():
        record=native.get('source_states',{}).get(PARENT,{}).get('remains',{}).get(identity)
        if record and record.get('physical_state')=='cremated_ash':return record
    return None


@hook('journey_command')
def rite(session,actor_id,kind,payload):
    if kind not in ('cremation_rite','cremation_collect_facts'):return None
    actor=session.state['actors'][actor_id];state=actor.get('source_states',{}).get(PARENT)
    require(state and state.get('sheet') and not actor['incapacitated'],'Acquire Cremation-Furnace Core before this procedure.')
    if kind=='cremation_collect_facts':
        require(set(payload)=={'scope'},'Choose the declared qualifying subject.')
        record=read(session,PARENT,actor_id,'qualifying_subject',payload['scope'],actor_id) or read(session,PARENT,actor_id,'qualifying_object',payload['scope'],actor_id) or read(session,PARENT,actor_id,'source_authority',payload['scope'],actor_id) or read(session,PARENT,actor_id,'perceived_systems',payload['scope'],actor_id)
        require(record is not None,'The table owner must record actual threat and farming provenance.')
        value=record['value']
        if record['kind']=='qualifying_subject':
            require(set(value)=={'actor_id','genuine_threat','farmed'} and value['actor_id'] in session.state['actors'] and all(type(value[k]) is int and value[k] in (0,1) for k in ('genuine_threat','farmed')),'Name a native creature and explicit threat/farming facts.')
            identity=value['actor_id']
        elif record['kind']=='perceived_systems':
            require(set(value)=={'actor_id','systems'} and value['actor_id'] in session.state['actors'] and isinstance(value['systems'],list) and value['systems'] and all(type(v) is str and v for v in value['systems']) and len(set(value['systems']))==len(value['systems']),'Record the creature and the systems actually perceived by this observer; an action catalog is not observation.')
            identity=value['actor_id']
        elif record['kind']=='source_authority':
            require(set(value)=={'actor_id','source_cl'} and type(value['actor_id']) is str and bool(value['actor_id']) and type(value['source_cl']) is int and value['source_cl']>=1,'Record the actual creature and its Source CL.')
            identity=value['actor_id']
        else:
            require(set(value)=={'object_id','meaningful','farmed'} and type(value['object_id']) is str and bool(value['object_id']) and all(type(value[k]) is int and value[k] in (0,1) for k in ('meaningful','farmed')),'Name the actual object and explicit significance/farming facts.')
            identity=value['object_id']
        state['facts'].setdefault(identity,{}).update(deepcopy(value))
        state.setdefault('fact_records',{})[record['kind']+':'+record['scope']]=deepcopy(record)
        export(session,actor_id);return True
    require(set(payload)=={'scope','result'},'Choose one actual remains record and one rite result.')
    record=read(session,PARENT,actor_id,'remains',payload['scope'],actor_id)
    require(record is not None,'The table owner must record actual remains in touch range.')
    value=record['value']
    require(set(value)=={'id','kind','meaningful','position','source_cl','properties'} and value['kind'] in ('corpse','spirit_shell','destroyed_summon','cultivation_residue','artifact_fragment') and type(value['meaningful']) is int and value['meaningful'] in (0,1),'Record the actual remains kind, significance, position, Source CL and known properties.')
    from ..gate2_runtime_models import Position
    native_body=session.state['actors'].get(value['id'])
    if native_body is not None:
        require(value['position']==native_body['position'],'Use the remains’ actual committed native position.')
        from .life_state import SOUL,DEAD
        snapshot=native_body.get('encounter_snapshot') or {}
        deceased=any(json.loads(raw).get('condition_id') in (SOUL,DEAD) for raw in snapshot.get('conditions',{}).values())
        ashed=any(row.get('condition')==PREFIX+'sovereign_ash' for row in native_body.get('source_states',{}).get(PARENT,{}).get('effects',[]))
        require(deceased or (ashed and value['kind']=='cultivation_residue'),'This native creature has no recorded death or source-produced bodily residue; low HP, inactivity or a declaration cannot turn a living actor into remains.')
    require(session.grid.distance_ft(Position(**actor['position']),Position(**value['position']))<=5,'Corpse and Residue Rite requires touch.')
    choice=payload['result'];require(choice in ('reanimation','purify','determine','ash'),'Choose one of the four printed rite results.')
    require(value['kind']!='artifact_fragment' or choice=='ash','The common artifact-fragment rite grants Ash; the other CL3 rite results require one of its printed remains kinds.')
    require(value['id'] not in state['generated'] or choice!='ash','These remains have already generated Ash for you this scene.')
    require(cremated_remains(session,value['id']) is None,'These remains are already cremated; declare a separately identified, actual significant residue if one remains.')
    session.tick(600)
    require(read(session,PARENT,actor_id,'remains',payload['scope'],actor_id) is not None,'The remains declaration expired before the ten-minute rite ended.')
    # The acquisition sheet is provenance. The compiled owned row reflects the
    # current PB and effective Qi CL, including advancement between journeys.
    numbers=next(row['numbers'] for row in actor['bundle']['typed_passives'] if row.get('block')==BLOCK)
    outcome={'id':value['id'],'result':choice,'clock':int(session.clock()),'source_cl':int(numbers['cl'])}
    if choice=='ash':
        require(value['meaningful']==1 and value['id'] not in state['generated'],'Only meaningful remains not already used this scene generate Ash.')
        state['generated'].append(value['id'])
        if state['ash']<int(numbers['pb']):state['ash']+=1
    elif choice=='determine':
        keys=('curse','possession','poison','corruption','soul_fragment','cultivation_imprint')
        require(all(type(value['properties'].get(k)) is int and value['properties'][k] in (0,1) for k in keys),'The native world owner must supply all six actual properties; omitted facts are unknown, not absent.')
        outcome['properties']={k:value['properties'][k] for k in keys}
    remains=state.setdefault('remains',{})
    current=deepcopy(value)
    current.update(physical_state='cremated_ash',cremator=actor_id,receipt_id=record['receipt_id'],cremated_at=int(session.clock()),scene=state['scene'])
    outcome['physical_state']='cremated_ash'
    if choice=='purify':
        current['properties']['mundane_disease']=0;current['properties']['ordinary_corpse_contamination']=0
    if choice=='reanimation':current['ordinary_reanimation_prevented']=1;current['ward_source_cl']=outcome['source_cl']
    remains[value['id']]=current
    state.setdefault('rites',[]).append(outcome)
    session.emit('CREMATION_RITE_COMPLETED',actor_id,source=FEATURES[0],outcome=canonical(outcome),seconds=600,access_receipt=record['receipt_id'])
    export(session,actor_id);return True


@hook('journey_options')
def journey_options(session,actor_id):
    state=session.state['actors'][actor_id].get('source_states',{}).get(PARENT)
    if not state or not state.get('sheet'):return []
    out=[]
    for r in session.state.get('fact_consent_admission',[]):
        if r['source']!=PARENT or r['subject']!=actor_id or r['kind']!='remains':continue
        if read(session,PARENT,actor_id,'remains',r['scope'],actor_id) is None or cremated_remains(session,r['value'].get('id')):continue
        for choice,label in [('reanimation','Prevent ordinary reanimation'),('purify','Purify mundane disease and ordinary contamination'),('determine','Determine curses, possession, poison, corruption, soul fragments and cultivation imprints'),('ash','Gain one Ash Charge from meaningful remains')]:
            if r['value'].get('kind')=='artifact_fragment' and choice!='ash':continue
            out.append({'id':f'cremation_rite:{r["scope"]}:{choice}','kind':'cremation_rite','payload':{'scope':r['scope'],'result':choice},'label':f'Corpse and Residue Rite: {label}; touch, 10 minutes'})
    return out


@hook('journey_rest')
def rest(session,actor_id):
    state=session.state['actors'][actor_id].get('source_states',{}).get(PARENT)
    if state:state['ash']=0;export(session,actor_id)


@hook('journey_scene_end')
def scene_end(session,old,new):
    for aid,actor in session.state['actors'].items():
        state=actor.get('source_states',{}).get(PARENT)
        if state:
            state.update(generated=[],scene=new,heaven_used=0)
            state['fact_records']={k:r for k,r in state.get('fact_records',{}).items() if r['kind']=='source_authority'}
            snapshot=actor.get('encounter_snapshot')
            if snapshot:
                from ..fact_consent_admission import CONDITION
                snapshot['conditions']={k:raw for k,raw in snapshot.get('conditions',{}).items() if not (json.loads(raw).get('condition_id')==CONDITION and json.loads(json.loads(raw).get('data',{}).get('record','{}')).get('source')==FEATURES[0] and json.loads(json.loads(raw).get('data',{}).get('record','{}')).get('kind')=='ash_qualifying_subject')}
            state['effects']=[r for r in state.get('effects',[]) if r['condition'] not in (SCRIPTURE,PREFIX+'scripture_ready',PREFIX+'scripture_prepared') and not (r['condition']==FUNERAL and json.loads(r['data']).get('sovereign'))]
            export(session,aid)


@hook('journey_encounter_settled')
def settled(session,actor_id,engine,creature):
    state=session.state['actors'][actor_id].get('source_states',{}).get(PARENT)
    if not state:return
    data=ledger(creature);state.update(ash=int(creature.resources.get(ASH,0)),generated=list(data['generated']),heaven_used=int(data['heaven_used']))
    export(session,actor_id)


def minute_expiry(engine):
    from .effect_durations import round_token
    return round_token(engine,10)


def effect_types(action):
    result=set()
    def visit(v):
        if isinstance(v,dict):
            if v.get('type'):result.add(v['type'])
            for c in v.values():visit(c)
        elif isinstance(v,list):
            for c in v:visit(c)
    visit((action.parameters.get('typed') or {}).get('effects') or [])
    return result


@hook('technique_declared')
def intercept(engine,user,action,candidate,intent):
    from .. import zones,typed_executor as te
    from .ability_source import cultivation_check,numbers_of
    types=effect_types(action)
    escape=bool(types&{'teleport','teleport_steps','incorporeal','become_incorporeal','possession','spirit_projection','transformation','transform'})
    if escape:
        for zone in list(engine.state.zones.values()):
            if not zone.active or not (zone.trigger_profile.get('profile') or {}).get('cremation'):continue
            owner=engine.state.actors.get(zone.owner_id)
            if not owner or not hostile(engine,owner,user) or not zones.actor_inside_zone(engine,user,zone):continue
            ctx=context(engine,owner,zone.source_definition_id,[user]);ctx.intent=intent
            # A failed save places a temporary receipt in the current transaction.
            te.run_effects(ctx,[{'type':'save','ability':'cha','on_fail':[{'type':'cremation_escape_failed'}],'on_success':[]}])
            marker=one(user,PREFIX+'escape_failed')
            if marker:
                engine._remove_condition(user,PREFIX+'escape_failed',zone.source_definition_id)
                gain(ctx,'escape:'+user.entity_id+':'+str(engine.state.round_number),explicit=True,qualifying_actor=user)
                protect_failed_costs(engine,user,action,intent,zone.source_definition_id)
                return {'source_id':zone.source_definition_id,'label':'Burn the Escape: activation suppressed; normal Cultivation Point cost is spent','cancel':True,'spend_activation':True}
    restoration=bool(types&{'healing','heal','revive','resurrect','reincarnate','soul_return','capture_soul','possession','reanimate','create_undead','create_asset','restore_creature'})
    if restoration:
        for tid in candidate.target_ids:
            target=engine.state.actors.get(tid)
            if target is None:continue
            for c in conditions(target,FUNERAL):
                if target.current_hp>0 and types<= {'healing','heal'}:continue
                profile=action.parameters.get('typed') or {};numbers=profile.get('numbers') or numbers_of(engine,user)
                method=str(profile.get('source') or action.source_definition_id)
                level=numbers.get('cl');failed_methods=c.data.get('failed_methods',[])
                require(type(level) is int and level>=1,'Restoration requires the method’s actual recorded Source CL.')
                failures=[m for m in failed_methods if m.get('restorer')==user.entity_id]
                known_methods=[m for failure in failures for m in failure.get('known_methods',[])]
                if c.data.get('sovereign') and int(numbers_of(engine,target).get('cl',1))<c.data['cl'] and failures and (level<=max(m['cl'] for m in failures) or {'method':method,'cl':level} in known_methods):
                    return {'source_id':c.source_definition_id,'label':'Final Cremation: this failed restoration needs a new higher-authority method, artifact or Anchor','cancel':True,'spend_activation':False}
                if not cultivation_check(engine,user,numbers,c.data['dc'],action.source_definition_id,'Restoration through cremation ash'):
                    if c.data.get('sovereign'):
                        data=deepcopy(c.data)
                        known=[]
                        for aid in user.action_ids:
                            native=engine.action_catalog.get(aid)
                            if native is None or not effect_types(native).intersection({'healing','heal','revive','resurrect','reincarnate','soul_return','capture_soul','possession','reanimate','create_undead','create_asset','restore_creature'}):continue
                            typed=native.parameters.get('typed') or {};native_cl=(typed.get('numbers') or {}).get('cl')
                            if type(native_cl) is int:known.append({'method':str(typed.get('source') or native.source_definition_id),'cl':native_cl})
                        data['failed_methods']=[*failed_methods,{'method':method,'cl':level,'restorer':user.entity_id,'known_methods':known}]
                        put(engine,target,FUNERAL,c.source_definition_id,c.source_actor_id,data,c.expires_on)
                    # Material/permanent/story-limited costs execute only on resolution;
                    # ordinary CP costs and economy are the native cancellation payment.
                    protect_failed_costs(engine,user,action,intent,c.source_definition_id)
                    return {'source_id':c.source_definition_id,'label':'Cremation ash blocks restoration: ordinary recoverable costs are spent; permanent or irreplaceable resolution costs are retained','cancel':True,'spend_activation':True}
    return None


@effect('cremation_escape_failed')
def escape_failed(ctx,row):
    put(ctx.engine,ctx.target,PREFIX+'escape_failed',ctx.source,ctx.actor.entity_id,{'label':'Burn the Escape: failed Charisma save'},'END_OF_CURRENT_TURN')


@hook('compile_actions')
def scripture_action(info):
    if FEATURES[2] in info['owned_ids']:
        return [action(info,2,'Scripture Ash: prepare a burned-law benefit','scripture_prepare',economy='NONE',target='SELF',reach=0)]
    return None


@effect('cremation_scripture_prepare')
def scripture_prepare(ctx,row):
    c=one(ctx.actor,SCRIPTURE)
    if c is None:return
    profile=json.loads(c.data['profile']);types=profile['types']
    choices=['save','discount']+(['damage','resistance'] if types else [])
    labels={'damage':'Add 3d8 damage of a type used by '+profile['name'],'resistance':'Resistance to one of its damage types until your next turn','save':'Add Proficiency Bonus to one save against '+profile['name'],'discount':'Reduce a Qi feature sharing a tag by 2, minimum 1'}
    selected=ask(ctx,'scripture_benefit',choices,labels,'Scripture Ash: prepare one benefit. The Ash is consumed only when a Qi-powered feature activates.',decline=True)
    if not selected:return
    damage_type=''
    if selected[0] in ('damage','resistance'):
        chosen=ask(ctx,'scripture_type',types,{t:t.title() for t in types},'Scripture Ash: choose a damage type actually used by the burned effect.')
        if not chosen:return
        damage_type=chosen[0]
    put(ctx.engine,ctx.actor,PREFIX+'scripture_prepared',FEATURES[2],ctx.actor.entity_id,{'kind':selected[0],'damage_type':damage_type,'profile':canonical(profile),'ash_instance':c.instance_id,'label':labels[selected[0]]})


def store_scripture(ctx,profile):
    """Replacing the one stored ash invalidates only its unconsumed choice."""
    ctx.engine._remove_condition(ctx.actor,PREFIX+'scripture_prepared',FEATURES[2])
    put(ctx.engine,ctx.actor,SCRIPTURE,FEATURES[2],ctx.actor.entity_id,{'profile':canonical(profile),'label':'Scripture Ash: one stored burned effect until scene end'})


def prepared_scripture(actor):
    c=one(actor,PREFIX+'scripture_prepared');ash=one(actor,SCRIPTURE)
    return c if c and ash and c.data.get('ash_instance')==ash.instance_id else None


@hook('technique_start')
def consume_scripture(engine,actor,action):
    c=prepared_scripture(actor)
    if c is None:return None
    ctx=context(engine,actor,action.source_definition_id);ctx.action=action;ctx.typed=action.parameters.get('typed') or {}
    if not qi_powered(ctx) or action.parameters.get('cremation_operation')=='scripture_prepare':return None
    profile=json.loads(c.data['profile']);kind=c.data['kind']
    from .source_eligibility import printed_source_tags
    if kind=='discount' and not set(profile['tags']).intersection(printed_source_tags(action)):return None
    engine._remove_condition(actor,SCRIPTURE,FEATURES[2]);engine._remove_condition(actor,PREFIX+'scripture_prepared',FEATURES[2])
    if kind=='resistance':
        engine._add_modifier(actor,FEATURES[2],'damage_resistance','SET',c.data['damage_type'],'SELF',expires_on=f'START_OF_TURN_AT:{actor.entity_id}:{actor.turns_started+1}',source_actor_id=actor.entity_id)
    elif kind in ('damage','save'):
        put(engine,actor,PREFIX+'scripture_ready',FEATURES[2],actor.entity_id,{**c.data,'activation_source':action.source_definition_id,'activation_intent':getattr(getattr(engine,'_active_intent',None),'intent_id',''),'zones':[]},'UNTIL_REMOVED')
    return None


@hook('technique_cost_discount')
def scripture_discount(engine,actor,source,costs):
    c=prepared_scripture(actor)
    if not c or c.data['kind']!='discount' or QI not in costs:return None
    action=engine.action_catalog.get(source)
    if action is None:return None
    from .source_eligibility import printed_source_tags
    if set(json.loads(c.data['profile'])['tags']).intersection(printed_source_tags(action)):return {QI:min(2,max(0,costs[QI]-1))}
    return None


@hook('save')
def scripture_save(ctx,target,ability,named):
    c=one(target,PREFIX+'scripture_ready')
    if not c or c.data['kind']!='save':return None
    profile=json.loads(c.data['profile'])
    if str(ctx.typed.get('option_of') or ctx.typed.get('source') or '')!=profile['source']:return None
    if ask(ctx,'scripture_save',['use'],{'use':'Add your Proficiency Bonus to this save'},f'Scripture Ash: {target.display_name} saves against {profile["name"]}. Use your stored Proficiency Bonus?',decline=True,chooser=target):
        ctx.engine._remove_condition(target,PREFIX+'scripture_ready',FEATURES[2])
        row=owned(ctx.engine,target)
        return {'bonus':int(row['numbers']['pb']),'modes':[]}
    return None


@hook('damage_roll_resolved')
def scripture_damage_roll(ctx,row,key):
    if '_cremation_scripture_roll' in ctx.damage_cache:ctx.damage_cache['_cremation_scripture_current']=key
    c=next((c for c in conditions(ctx.actor,PREFIX+'scripture_ready') if c.data['kind']=='damage' and c.data['activation_source']==ctx.source and activation_matches(ctx,c)),None)
    if c is None:return
    ctx.damage_cache['_cremation_scripture_current']=key
    if '_cremation_scripture_roll' in ctx.damage_cache:return
    if ask(ctx,'scripture_roll',['add'],{'add':'Add 3d8 '+c.data['damage_type'].title()+' damage to this roll'},'Scripture Ash: add the burned effect’s 3d8 damage to this one damage roll?',decline=True):
        from .. import typed_executor as te
        from ..gate2_runtime_models import DiceSpec
        ctx.damage_cache['_cremation_scripture_roll']=(key,te._roll(ctx,DiceSpec(count=3,sides=8),'SCRIPTURE_ASH'),c.data['damage_type'])
        ctx.engine._remove_condition_instance(ctx.actor,c.instance_id,FEATURES[2],expected=c)


@hook('deal_bonus')
def scripture_damage_packet(ctx,target,amount):
    bonus=ctx.damage_cache.get('_cremation_scripture_roll')
    if not bonus or ctx.damage_cache.get('_cremation_scripture_current')!=bonus[0]:return None
    used=ctx.damage_cache.setdefault('_cremation_scripture_recipients',set())
    if target.entity_id in used:return None
    used.add(target.entity_id)
    from .. import typed_executor as te
    # The chosen roll is shared by its native recipients. Each packet retains
    # its own save divisor, Resistance, Immunity and normal damage ordering.
    te._deal(replace(ctx,damage_cache={'_potency_used':True}),target,bonus[1],bonus[2],divisor=max(ctx.damage_divisor,2 if ctx.failed_save is False else 1))
    return None


@hook('masked_conditions')
def reveal_invisibility(engine,viewer,target):
    if not any(c.source_actor_id==viewer.entity_id for c in conditions(target,PREFIX+'revealed')):return None
    return {target.entity_id:{iid for iid,c in target.conditions.items() if c.condition_id in ('condition:typed.invisible','condition:typed.hidden')}}


@hook('obscurement_ignored')
def reveal_concealment(engine,zone,viewer,target):
    if any(c.source_actor_id==viewer.entity_id for c in conditions(target,PREFIX+'revealed')):
        profile=zone.trigger_profile
        # Ordinary concealment only; opaque walls/absolute source authority remain.
        if profile.get('obscured') and not profile.get('absolute_obscurement'):return True
    return None


@hook('state_event')
def funeral_any_drop(engine,event):
    if event.event_type!='DAMAGE_COMMITTED' or event.payload.get('hp_before',0)<=0 or event.payload.get('remaining_hp',1)!=0:return
    for tid in event.target_ids:
        target=engine.state.actors.get(tid)
        if target is None:continue
        for c in conditions(target,SENTENCE):
            owner=engine.state.actors.get(c.source_actor_id)
            if owner is None or not owned(engine,owner,1):continue
            ctx=context(engine,owner,FEATURES[1],[target]);gain(ctx,target.entity_id)
            put(engine,target,FUNERAL,FEATURES[1],owner.entity_id,{'dc':int(ctx.numbers['save_dc']),'cl':int(ctx.numbers['cl']),'label':'Funeral Flame: restoration requires a Cultivation Check'},f'END_OF_SOURCE_TURN_AT:{owner.turns_started+1}')


@hook('journey_snapshot_actor')
def snapshot_actor(creature,session,actor_id,engine):
    ids=[iid for iid,c in creature.conditions.items() if c.condition_id.startswith(PREFIX)]
    if not ids:return None
    result=creature.model_copy(deep=True)
    for iid in ids:result.conditions.pop(iid,None)
    from ..concentration import HELD
    from .concentration_duration import DEADLINE
    own_fields={z.source_definition_id for z in engine.state.zones.values() if z.active and z.owner_id==actor_id and (z.trigger_profile.get('profile') or {}).get('cremation')}
    result.conditions={iid:c for iid,c in result.conditions.items() if not (c.condition_id in (HELD,DEADLINE) and c.source_actor_id==actor_id and c.source_definition_id in own_fields)}
    result.modifiers={mid:m for mid,m in result.modifiers.items() if not (m.source_actor_id==actor_id and m.source_definition_id in FEATURES)}
    if result.concentration and any(z.active and z.owner_id==actor_id and z.source_definition_id==result.concentration.source_definition_id and (z.trigger_profile.get('profile') or {}).get('cremation') for z in engine.state.zones.values()):result.concentration=None
    return result


def seconds_remaining(engine,holder,condition):
    from .suppressed_effects import lifetime
    from .effect_durations import parse,parse_round
    clock=lifetime(engine,holder,condition);expiry=clock['expiry']
    if expiry in ('','UNTIL_REMOVED'):return -1
    slot=parse_round(expiry)
    if slot:
        rounds,idx=slot;steps=(rounds-engine.state.round_number)*len(engine.state.initiative_order)+idx-engine.state.current_slot_index
        return max(0,(steps*6+len(engine.state.initiative_order)-1)//len(engine.state.initiative_order))
    turn=parse(expiry)
    if turn:
        edge,aid,count=turn;actor=engine.state.actors.get(aid)
        return max(0,(count-actor.turns_started)*6) if actor else 0
    return 0


@hook('journey_encounter_settled')
def export_timed_states(session,actor_id,engine,creature):
    if not session.state['actors'][actor_id].get('source_states',{}).get(PARENT) and not any(c.condition_id.startswith(PREFIX) for c in creature.conditions.values()):return
    state=source_state(session.state['actors'][actor_id]);rows=[]
    for c in creature.conditions.values():
        if not c.condition_id.startswith(PREFIX) or c.condition_id in (LEDGER,PREFIX+'facts',FIELD,PREFIX+'escape_failed',PREFIX+'judgment_used'):continue
        seconds=seconds_remaining(engine,creature,c)
        if c.condition_id in (PREFIX+'activation',PREFIX+'scripture_ready') and c.data.get('kind') in ('damage','reveal'):
            bound=[z for z in engine.state.zones.values() if z.active and z.zone_id in c.data.get('zones',[])]
            if not bound:continue
            seconds=max(max(0,(int(z.duration_rounds or 10)-engine.state.round_number+z.created_round)*6) for z in bound)
        if seconds==0:continue
        rows.append({'condition':c.condition_id,'source':c.source_definition_id,'owner':c.source_actor_id,'instance':c.instance_id,'data':canonical(c.data),'until':int(session.clock())+seconds if seconds>=0 else -1})
    state['effects']=rows
    state['modifiers']=[{'document':m.model_dump_json(),'until':int(session.clock())+seconds_remaining(engine,creature,m)} for m in creature.modifiers.values() if m.source_actor_id==actor_id and m.source_definition_id in FEATURES and seconds_remaining(engine,creature,m)>0]
    export(session,actor_id)


@hook('match_initialize')
def import_timed_states(engine):
    from .effect_durations import round_token
    for bundle in engine.typed_bundle_documents:
        saved=bundle.get(BLOCK);actor=engine.state.actors.get(bundle['actor_id'])
        if not saved or actor is None:continue
        restored_instances={}
        for row in saved.get('effects',[]):
            seconds=row['until']-saved.get('clock',0) if row['until']>=0 else -1
            if seconds==0 or seconds< -1:continue
            # Do not use put(): separately paid activations may intentionally
            # share condition/source/owner and must remain independently bound.
            before=set(actor.conditions)
            engine._apply_condition(actor,row['condition'],row['source'],row['owner'],
                expires_on='UNTIL_REMOVED' if seconds==-1 else round_token(engine,max(1,(seconds+5)//6)),
                data=json.loads(row['data']))
            restored=next((condition for instance,condition in actor.conditions.items()
                           if instance not in before and condition.condition_id==row['condition']
                           and condition.source_definition_id==row['source']
                           and condition.source_actor_id==row['owner']),None)
            if row.get('instance') and restored is not None:
                restored_instances[row['instance']]=restored.instance_id
        for condition in conditions(actor,PREFIX+'scripture_prepared'):
            old=condition.data.get('ash_instance')
            if old in restored_instances:condition.data['ash_instance']=restored_instances[old]
        for row in saved.get('modifiers',[]):
            seconds=row['until']-saved.get('clock',0)
            if seconds<=0:continue
            doc=json.loads(row['document'])
            engine._add_modifier(actor,doc['source_definition_id'],doc['target_field'],doc['operation'],doc['value'],doc['applies_to'],
                expires_on=round_token(engine,max(1,(seconds+5)//6)),source_actor_id=doc['source_actor_id'],application_id=doc.get('application_id'))


@hook('journey_elapsed')
def elapsed(session,actor_id,before,seconds,moving):
    actor=session.state['actors'][actor_id]
    state=actor.get('source_states',{}).get(PARENT)
    if not state:return
    state['effects']=[r for r in state.get('effects',[]) if r['until']==-1 or r['until']>session.clock()]
    state['modifiers']=[r for r in state.get('modifiers',[]) if r['until']>session.clock()]
    state['fields']=[r for r in state.get('fields',[]) if r['until']>session.clock()]
    export(session,actor_id)


@hook('technique_cost_floor')
def ash_floor(engine,actor,source,listed,current):
    if not owned(engine,actor) or not listed.get(QI):return None
    if one(actor,PREFIX+'prepared') or one(actor,PREFIX+'scripture_prepared') or sovereign(actor):return {QI:1}
    return None


@hook('damage_roll_resolved')
def ash_roll(ctx,row,key):
    if '_cremation_ash_roll' in ctx.damage_cache:ctx.damage_cache['_cremation_current_roll']=key
    c=next((c for c in conditions(ctx.actor,PREFIX+'activation') if c.data['source']==ctx.source and activation_matches(ctx,c)),None)
    if not c or c.data['source']!=ctx.source or c.data['kind']!='damage':return
    ctx.damage_cache['_cremation_current_roll']=key
    if '_cremation_ash_roll' in ctx.damage_cache:return
    if ask(ctx,'ash_roll',['add'],{'add':'Add 1d8 Cremation Fire to this damage roll'},'Spend Ash: add your prepared 1d8 Cremation Fire damage to this damage roll?',decline=True):
        from .. import typed_executor as te
        from ..gate2_runtime_models import DiceSpec
        chosen=ask(ctx,'ash_roll_type',['FIRE','NECROTIC'],{'FIRE':'Fire','NECROTIC':'Necrotic'},'Spend Ash: choose the Cremation Fire damage type.')
        ctx.damage_cache['_cremation_ash_roll']=(key,te._roll(ctx,DiceSpec(count=1,sides=8),'SPEND_ASH'),chosen[0] if chosen else 'FIRE')
        ctx.engine._remove_condition_instance(ctx.actor,c.instance_id,FEATURES[0],expected=c)


@hook('deal_bonus')
def ash_packet(ctx,target,amount):
    bonus=ctx.damage_cache.get('_cremation_ash_roll')
    if not bonus or ctx.damage_cache.get('_cremation_current_roll')!=bonus[0]:return None
    used=ctx.damage_cache.setdefault('_cremation_ash_recipients',set())
    if target.entity_id in used:return None
    used.add(target.entity_id)
    from .. import typed_executor as te
    te._deal(replace(ctx,damage_cache={'_potency_used':True},damage_source_flags=(*ctx.damage_source_flags,'cremation_fire'),effect_source=FEATURES[0]),target,bonus[1],bonus[2],divisor=max(ctx.damage_divisor,2 if ctx.failed_save is False else 1))
    return None


@hook('candidate_allowed')
def prison_body_gate(engine,actor,candidate,action):
    if action is None or one(actor,PREFIX+'prison_lock') is None:return None
    if effect_types(action)&{'teleport','teleport_steps','incorporeal','become_incorporeal','spirit_projection'}:return False
    return None


@hook('object_packets')
def spend_ash_object_packet(engine,actor,obj,packets,source):
    ctx=context(engine,actor,source)
    c=next((c for c in conditions(actor,PREFIX+'activation')
        if c.data['source']==source and activation_matches(ctx,c)),None)
    if not c or c.data['kind']!='damage':return None
    if not ask(ctx,'ash_object',['add'],{'add':'Add 1d8 Cremation Fire to '+str((obj.component or {}).get('name') or 'this object')},'Spend Ash: add your prepared Cremation Fire to this object damage roll?',decline=True):return None
    from .. import typed_executor as te
    from ..gate2_runtime_models import DiceSpec
    damage_type=ask(ctx,'ash_object_type',['FIRE','NECROTIC'],{'FIRE':'Fire','NECROTIC':'Necrotic'},'Spend Ash: choose Cremation Fire damage for this object.')[0]
    amount=te._roll(ctx,DiceSpec(count=1,sides=8),'CREMATION_OBJECT_ASH')
    engine._remove_condition_instance(actor,c.instance_id,FEATURES[0],expected=c)
    put(engine,actor,PREFIX+'object_packet',FEATURES[0],actor.entity_id,{'object':obj.object_id,'source':source,'type':damage_type,'label':'Source-bound Cremation Fire object packet'},'END_OF_CURRENT_TURN')
    return {'object':obj,'packets':[(amount,damage_type)]}


@hook('state_event')
def native_object_destroyed(engine,event):
    if event.event_type!='OBJECT_UPDATED' or not event.payload.get('damage',{}).get('taken'):return
    actor=engine.state.actors.get(event.actor_id)
    if actor is None or not owned(engine,actor):return
    marker=one(actor,PREFIX+'object_packet');obj=event.payload.get('object',{})
    if marker is None or marker.data['source']!=event.source_definition_id or marker.data['object']!=obj.get('object_id'):return
    engine._remove_condition(actor,PREFIX+'object_packet',FEATURES[0])
    if not obj.get('destroyed'):return
    known=admitted_facts(actor)
    eligibility=known.get(obj['object_id'],{})
    if eligibility.get('meaningful')!=1 or eligibility.get('farmed')!=0 or obj.get('owner_id')==actor.entity_id:return
    from ..gate2_runtime_models import Position
    if engine.grid.distance_ft(actor.position,Position(**obj['position']))<=60:
        gain(context(engine,actor,event.source_definition_id),obj['object_id'])


@hook('candidate_allowed')
def prison_placement_gate(engine,actor,candidate,action):
    if action is None or action.parameters.get('cremation_operation')!='prison':return None
    if candidate.destination is None:return False
    from ..asset_anchor_runtime import legal_placement
    return None if legal_placement(engine,[candidate.destination],5) else False


def protect_failed_costs(engine,actor,action,intent,source):
    """Retain irreplaceable prices using the existing native spend-reduction seam.

    The Source Rule can explicitly classify an additional ordinary recoverable
    resource or name prices paid before resolution. Unknown non-CP prices stay
    protected. No resource-name heuristic supplies recoverability.
    """
    from ..typed_executor import CP_POOLS
    spec=(action.parameters.get('typed') or {}).get('cremation_cost_policy') or {}
    recoverable=set(CP_POOLS)|set(spec.get('ordinary_recoverable') or [])
    early=set(spec.get('paid_before_resolution') or [])
    preserve=[rid for rid,n in action.costs if rid not in recoverable and rid not in early and n>0]
    if preserve:
        put(engine,actor,PREFIX+'protected_costs',source,actor.entity_id,{'activation_source':action.source_definition_id,'intent_id':intent.intent_id,'resources':preserve,
            'label':'Failed cremation pre-resolution check: permanent and irreplaceable prices retained'},'END_OF_CURRENT_TURN')


@hook('resource_spend_reduction')
def protected_prices(engine,actor,resource_id,amount,source_id):
    from ..typed_executor import CP_POOLS
    if amount>0 and resource_id in CP_POOLS and one(actor,FINAL):
        raise ValueError('Final Cremation suppresses this creature’s Cultivation Point expenditure until the end of its next turn.')
    intent=getattr(engine,'_active_intent',None)
    c=one(actor,PREFIX+'protected_costs')
    if c and intent and c.data['intent_id']==intent.intent_id and c.data['activation_source']==source_id and resource_id in c.data['resources']:return amount
    return None


@hook('activation_end')
def clear_failed_costs(engine,actor,action,candidate,intent):
    c=one(actor,PREFIX+'protected_costs')
    if c and c.data['intent_id']==intent.intent_id:engine._remove_condition(actor,PREFIX+'protected_costs',c.source_definition_id)


@hook('journey_encounter_settled')
def export_field(session,actor_id,engine,creature):
    owned_zones=[z for z in engine.state.zones.values() if z.active and z.owner_id==actor_id and (z.trigger_profile.get('profile') or {}).get('cremation')]
    state=session.state['actors'][actor_id].get('source_states',{}).get(PARENT)
    if not state:return
    fields=[]
    for zone in owned_zones:
        remaining=max(0,(int(zone.duration_rounds or 10)-engine.state.round_number+zone.created_round)*6)
        if remaining==0:continue
        fields.append({'zone':canonical(zone.model_dump(mode='json')),'until':int(session.clock())+remaining,
            'objects':[canonical(o.model_dump(mode='json')) for o in engine.state.objects.values() if (o.component or {}).get('cremation_zone')==zone.zone_id],
            'final_used':next((int(c.data.get('final_used',0)) for c in conditions(creature,FIELD) if c.data['zone']==zone.zone_id),0)})
    state['fields']=fields;export(session,actor_id)


@hook('match_initialize')
def import_fields(engine):
    from ..gate2_runtime_models import ZoneState,RuntimeObjectState
    for bundle in engine.typed_bundle_documents:
        saved=bundle.get(BLOCK);actor=engine.state.actors.get(bundle['actor_id'])
        if not saved or actor is None or not owned(engine,actor):continue
        for field_state in saved.get('fields',[]):
            remaining=field_state['until']-saved.get('clock',0)
            if remaining<=0:continue
            doc=json.loads(field_state['zone']);doc.update(created_round=engine.state.round_number,duration_rounds=max(1,(remaining+5)//6),per_turn_triggered={})
            zone=ZoneState.model_validate(doc)
            engine._start_concentration(actor,zone.source_definition_id)
            engine.state.zones[zone.zone_id]=zone
            engine._append_event('ZONE_CREATED',zone.source_definition_id,actor_id=actor.entity_id,payload={'zone':zone.model_dump(mode='json')})
            if actor.concentration:actor.concentration.zone_id=zone.zone_id
            for raw in field_state['objects']:
                obj=RuntimeObjectState.model_validate(json.loads(raw));engine._update_object(obj,zone.source_definition_id,actor.entity_id)
            if (zone.trigger_profile.get('profile') or {}).get('cremation')=='heaven':
                store_field(engine,actor,zone.source_definition_id,{'zone':zone.zone_id,'final_used':field_state['final_used'],'label':'Sovereign cremation furnace: remaining duration, concentration'})


def qi_numbers(info):
    numbers=dict(info['numbers']);paths=(info.get('owner_sheet') or {}).get('path_and_subpath') or {}
    for path in paths.get('paths',[]):
        if path.get('path_id')!='tianxia.path.qi_cultivation':continue
        level=next((path[k] for k in ('effective_cl','owning_path_level','attainment') if type(path.get(k)) is int),None)
        if level is not None:
            require(1<=level<=int(numbers['cl']),'Qi Path authority must not exceed the recorded Cultivation Level.')
            numbers['cl']=level
        key=path.get('key_ability')
        if key:
            require(key in ('INT','CHA'),'The recorded Qi key ability must be Intelligence or Charisma.')
            abilities=(info.get('owner_sheet') or {}).get('ability_scores_and_statistics',{}).get('abilities',[])
            modifier=next((int(a['modifier']) for a in abilities if a.get('ability')==key),None)
            require(modifier is not None,'The recorded Qi key ability needs its native ability modifier.')
            numbers['key_mod']=modifier
            if key!=(info.get('owner_sheet') or {}).get('identity',{}).get('key_ability'):numbers['save_dc']=8+int(numbers['pb'])+modifier
        break
    return numbers


@hook('match_initialize')
def import_rite_wards(engine):
    for bundle in engine.typed_bundle_documents:
        saved=bundle.get(BLOCK);owner=engine.state.actors.get(bundle['actor_id'])
        if not saved or owner is None or not owned(engine,owner):continue
        for identity,body in saved.get('remains',{}).items():
            target=engine.state.actors.get(identity)
            if target is None:continue
            if body.get('ordinary_reanimation_prevented'):
                put(engine,target,PREFIX+'rite_ward',FEATURES[0],owner.entity_id,{'source_cl':body['ward_source_cl'],'label':'Corpse and Residue Rite prevents ordinary reanimation'},'UNTIL_REMOVED')
            # Only explicitly classified mundane disease/ordinary contamination
            # can be purified; curse/possession/corruption and other sources remain.
            if body['properties'].get('mundane_disease')==0 and body['properties'].get('ordinary_corpse_contamination')==0:
                for iid,c in list(target.conditions.items()):
                    tags=set(c.data.get('source_tags') or [])
                    if tags.intersection({'mundane_disease','ordinary_corpse_contamination'}):
                        engine._remove_condition_instance(target,iid,FEATURES[0],actor_id=owner.entity_id,payload={'condition_id':c.condition_id,'instance_id':iid,'reason':'PURIFIED'},expected=c)


@hook('technique_declared')
def ordinary_reanimation_ward(engine,user,action,candidate,intent):
    if not effect_types(action).intersection({'reanimate','create_undead'}):return None
    typed=action.parameters.get('typed') or {}
    if typed.get('authority')!='ordinary' and not typed.get('mundane'):return None
    for tid in candidate.target_ids:
        target=engine.state.actors.get(tid)
        if target is None:continue
        ward=one(target,PREFIX+'rite_ward')
        if ward:return {'source_id':ward.source_definition_id,'label':'Corpse and Residue Rite prevents ordinary reanimation of these remains','cancel':True,'spend_activation':False}
    return None


@hook('compile_action')
def ash_damage_delivery(action,info):
    if FEATURES[0] not in info['owned_ids']:return None
    typed=deepcopy(action.parameters.get('typed') or {})
    stats=(info.get('owner_sheet') or {}).get('ability_scores_and_statistics') or {}
    from ..typed_executor import CP_POOLS
    alignment=typed.get('technique_alignment') or {}
    paid=[pool for pool,amount in action.costs if amount and pool in CP_POOLS]
    pool=alignment.get('resource_id') or (paid[0] if paid else None)
    if pool:
        typed['technique_alignment']={**alignment,'resource_id':pool}
        if pool!=QI or type(typed.get('qi_powered')) is not bool:typed['qi_powered']=pool==QI
    from .qi_path import ARMAMENT,GOLDEN
    native_qi=(action.parameters.get('armament') and ARMAMENT in info['owned_ids']) or ((action.parameters.get('golden_choice') or action.parameters.get('golden_reservoir')) and GOLDEN in info['owned_ids'])
    if type(typed.get('qi_powered')) is not bool and native_qi:typed['qi_powered']=True
    if type(typed.get('qi_powered')) is not bool and typed.get('sphere') and not typed.get('attack_action') and str((stats.get('primary_resource') or {}).get('name') or '').lower()=='qi':typed['qi_powered']=True
    if typed.get('qi_powered') is False:return action.model_copy(update={'parameters':{**action.parameters,'typed':typed}})
    if not (typed.get('qi_powered') is True or QI in dict(action.costs) or 'qi' in typed.get('tags',[]) or str(typed.get('source','')).startswith(('tianxia.path.qi_cultivation.','tianxia.subpath.qi.'))):return None
    result=deepcopy(typed);result['manual_inline_choice']=True;changed=True
    def visit(value):
        nonlocal changed
        if isinstance(value,dict):
            if value.get('type')=='damage':value['damage_bonus_packet']=True;changed=True
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(result.get('effects') or [])
    return action.model_copy(update={'parameters':{**action.parameters,'typed':result}}) if changed else None


def sovereign_ash(ctx,target):
    """The printed 0-HP result changes only the actual current body/projections.

    This is source-granted bodily destruction, not an inference from ordinary
    damage. True soul, Samsara identity, Secret Law and artifact existence are
    explicitly retained. Independently acquired future projections remain legal.
    """
    # Shared lifecycle helpers from astral_projection.py keep projection ownership
    # detection and cleanup consistent across providers.
    from .astral_projection import projected_instances,end_projection
    from ..summons import dismiss
    from ..asset_anchor_runtime import retire
    shells=[];projections=[]
    projected=projected_instances(ctx.engine,target)
    if projected:
        projections.extend(c.instance_id for c in projected)
        end_projection(ctx.engine,target,'Final Cremation reduces the current projection to sovereign ash')
    for actor in list(ctx.engine.state.actors.values()):
        profile=actor.summon or {};tags=set(profile.get('source_tags') or [])
        if actor.owner_id!=target.entity_id or not actor.active:continue
        if 'spirit_shell' in tags or 'cultivation_projection' in tags:
            (shells if 'spirit_shell' in tags else projections).append(actor.entity_id)
            dismiss(ctx.engine,actor,'Final Cremation: the current shell or projection becomes sovereign ash')
    for obj in list(ctx.engine.state.objects.values()):
        data=obj.component or {};tags=set(data.get('source_tags') or [])
        if obj.owner_id==target.entity_id and not obj.destroyed and tags.intersection({'spirit_shell','cultivation_projection'}):
            (shells if 'spirit_shell' in tags else projections).append(obj.object_id)
            retire(ctx.engine,obj,ctx.source)
    put(ctx.engine,target,PREFIX+'sovereign_ash',ctx.source,ctx.actor.entity_id,{'body':'sovereign_ash','shells':shells,'projections':projections,
        'true_soul_erased':0,'samsara_identity_erased':0,'secret_law_erased':0,'artifact_existence_erased':0,
        'label':'Body reduced to sovereign ash; ordinary HP healing does not rebuild it; true soul and protected existence remain'},'UNTIL_REMOVED')


@hook('healing_pending')
def ash_body_healing(engine,target,amount,healer,source,kind):
    if kind=='hp' and one(target,PREFIX+'sovereign_ash'):
        action=engine.action_catalog.get(source)
        if action is None or not ((action.parameters.get('typed') or {}).get('restores_body') or 'restore_body' in effect_types(action)):return amount
    return None


@hook('candidate_allowed')
def ash_body_actions(engine,actor,candidate,action):
    if one(actor,PREFIX+'sovereign_ash') is None:return None
    from ..typed_executor import condition_rules
    independent=any(row.get('body_independent') for row in condition_rules(actor))
    if independent:return None
    if action is not None:
        typed=action.parameters.get('typed') or {}
        if typed.get('body_independent') or typed.get('requires_body') is False:return None
    if str(candidate.kind) in ('ACTION','BONUS_ACTION','REACTION','MOVE'):return False
    return None


@hook('technique_used')
def body_restoration_completed(ctx):
    if not (ctx.typed.get('restores_body') or 'restore_body' in effect_types(ctx.action)):return
    for target in ctx.targets:
        c=one(target,PREFIX+'sovereign_ash')
        if c and any(e.event_type in ('HEALING_APPLIED','LIFE_STATE_CHANGED') and target.entity_id in e.target_ids for e in ctx.engine.events[ctx.technique_event_start or 0:]):
            ctx.engine._remove_condition_instance(target,c.instance_id,ctx.source,expected=c)


def burn_zone(ctx,target,zone,profile):
    from .. import zones,concentration
    from .area_suppression import suppress
    cl=int(ctx.numbers['cl'])
    if profile['cl']<cl:
        caster=ctx.engine.state.actors.get(zone.owner_id)
        casts=([*concentration.held(caster),*([('',caster.concentration)] if caster.concentration else [])] if caster else [])
        for iid,c in casts:
            if c.zone_id==zone.zone_id:
                if iid:concentration.end_held(ctx.engine,caster,iid,'BURN_THE_SCRIPTURE')
                else:ctx.engine._end_concentration(caster,'BURN_THE_SCRIPTURE')
        zones.remove(ctx.engine,zone,'BURN_THE_SCRIPTURE')
    else:
        until=minute_expiry(ctx.engine) if profile['cl']==cl else f'END_OF_TURN_AT:{ctx.actor.entity_id}:{ctx.actor.turns_started+1}'
        record=suppress(ctx.engine,ctx.actor,zone,until,ctx.source)
        if record is None:return
        if profile['cl']==cl:
            ctx.engine._apply_condition(target,PREFIX+'burn_repeat',ctx.source,ctx.actor.entity_id,data={'zone':zone.zone_id,'record_key':record['key'],'label':'Burn the Scripture: repeat Constitution save to end suppression'},expires_on=until)
    gain(ctx,'effect:'+zone.zone_id)
    store_scripture(ctx,profile)


@hook('technique_declared')
def prepare_activation(engine,actor,action,candidate,intent):
    """Collect optional benefits before the native caller quotes/pays its cost.

    Foreground and the source's real damage-triggered Ash Sentence use this
    same producer. Selection alone spends nothing; actual technique_start owns
    consumption. A canceled declaration cannot spend an unactivated benefit.
    """
    if not owned(engine,actor) or action.parameters.get('setting_only'):return None
    ctx=context(engine,actor,action.source_definition_id);ctx.action=action;ctx.intent=intent;ctx.typed=deepcopy(action.parameters.get('typed') or {})
    if not qi_powered(ctx):return None
    if one(actor,PREFIX+'prepared') is None:prepare(ctx)
    if one(actor,SCRIPTURE) and prepared_scripture(actor) is None:scripture_prepare(ctx,{})
    return None


@hook('presentation_hidden_conditions')
def private_source_declarations(engine,actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in (PREFIX+'facts',LEDGER,PREFIX+'prepared',PREFIX+'scripture_prepared')]


def activation_matches(ctx,condition):
    """Only the accepted creating intent or its actual committed zone can spend it."""
    zone=ctx.damage_cache.get('_cremation_zone')
    if zone:return zone in condition.data.get('zones',[])
    return bool(ctx.intent and condition.data.get('activation_intent')==ctx.intent.intent_id)


@hook('zone_trigger_context')
def bind_delayed_context(ctx,zone,creature,moment):
    if owned(ctx.engine,ctx.actor):ctx.damage_cache['_cremation_zone']=zone.zone_id


@hook('technique_resolution_enabled')
def needs_activation_binding(ctx):
    if not owned(ctx.engine,ctx.actor) or ctx.intent is None:return None
    return any(c.condition_id in (PREFIX+'activation',PREFIX+'scripture_ready') and c.data.get('activation_intent')==ctx.intent.intent_id for c in ctx.actor.conditions.values())


@hook('technique_resolved')
def bind_actual_activation(ctx,receipt):
    if not owned(ctx.engine,ctx.actor) or receipt['owner_id']!=ctx.actor.entity_id or receipt['source_id']!=ctx.source:return
    sequences={r['event_sequence'] for r in receipt['effect_origin'] if r['event_type']=='ZONE_CREATED'}
    zones=[e.payload['zone']['zone_id'] for e in ctx.engine.events if e.sequence in sequences and e.event_type=='ZONE_CREATED']
    for c in list(ctx.actor.conditions.values()):
        if c.condition_id not in (PREFIX+'activation',PREFIX+'scripture_ready') or c.data.get('activation_intent')!=receipt['activation_id']:continue
        if c.data.get('kind') not in ('damage','reveal'):continue
        if not zones:
            # Spend Ash reveal is offered by technique_used after this receipt.
            if c.condition_id==PREFIX+'scripture_ready':ctx.engine._remove_condition_instance(ctx.actor,c.instance_id,c.source_definition_id,expected=c)
        else:
            data={**c.data,'zones':zones}
            ctx.engine._remove_condition_instance(ctx.actor,c.instance_id,c.source_definition_id,expected=c)
            ctx.engine._apply_condition(ctx.actor,c.condition_id,c.source_definition_id,c.source_actor_id,expires_on='UNTIL_REMOVED',data=data)


@hook('state_event')
def retire_activation_benefits(engine,event):
    if event.event_type!='ZONE_REMOVED':return
    zid=event.payload.get('zone_id')
    for actor in engine.state.actors.values():
        for c in list(actor.conditions.values()):
            if c.condition_id not in (PREFIX+'activation',PREFIX+'scripture_ready') or zid not in c.data.get('zones',[]):continue
            left=[z for z in c.data['zones'] if z!=zid and z in engine.state.zones and engine.state.zones[z].active]
            ctx_source=c.source_definition_id
            engine._remove_condition_instance(actor,c.instance_id,ctx_source,expected=c)
            if left:engine._apply_condition(actor,c.condition_id,ctx_source,c.source_actor_id,expires_on=c.expires_on,data={**c.data,'zones':left})


@hook('damage_dealt')
def delayed_ash_reveal(ctx,target,amount):
    if amount<=0 or not ctx.damage_cache.get('_cremation_zone'):return None
    c=next((c for c in conditions(ctx.actor,PREFIX+'activation') if c.data.get('kind')=='reveal' and c.data['source']==ctx.source and activation_matches(ctx,c)),None)
    if c is None:return None
    if ask(ctx,'ash_reveal',[target.entity_id],{target.entity_id:target.display_name},'Spend Ash: choose '+target.display_name+', damaged by this activation. Visible ash prevents Invisible and ordinary concealment from hiding it from you until your next turn.',decline=True):
        put(ctx.engine,target,PREFIX+'revealed',FEATURES[0],ctx.actor.entity_id,{'label':'Visible ash reveals this creature to its cremator'},f'START_OF_TURN_AT:{ctx.actor.entity_id}:{ctx.actor.turns_started+1}')
        ctx.engine._remove_condition_instance(ctx.actor,c.instance_id,FEATURES[0],expected=c)
    return None
