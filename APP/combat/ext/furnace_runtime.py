"""Public Second Furnace state/producer API used by all five family consumers.

Authority and initiation are collected through the fact-consent owner's native
admission interface. Resource triggers read committed resource/damage events;
source classifications never come from display names. Native journey acquisition
publishes the real build and retains an immutable access receipt and organ choice.
All hooks are inert without an acquired furnace feature. See docs/second_furnace.md.
"""
from __future__ import annotations
import copy
import json
from . import hook, effect
from .needle import ask, checkpoint_id, condition, numbers_of
from ..alternative_payments import owned
from ..fact_consent_admission import read
from ..journey import require, integer

PARENT = 'tianxia.subpath.qi.devil_heart_second_furnace'
PREFIX = PARENT + '.feature.'
FEATURES = ('demon_seed_overdraw','devil_qi_augment','second_furnace_core','heart_devil_counterflow','demon_emperor_s_second_engine')
LEVELS = (3,6,10,14,18)
SEED, AUGMENT, CORE, COUNTER, ENGINE = (PREFIX + name for name in FEATURES)
DEVIL, QI, CORRUPTION = 'resource:named.devil_qi','resource:core.qi','resource:named.corruption'
ORGAN = 'condition:typed.second_furnace_organ'
DORMANT = 'condition:typed.second_furnace_dormant'
UNSTABLE = 'condition:typed.second_furnace_unstable'
FORM = 'condition:typed.second_furnace_engine'
INTERFERENCE = 'condition:typed.second_furnace_interference'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False)


def source_numbers(engine,actor,feature=SEED):
    """The owned family's sealed numbers, independent of a delivery's level."""
    for row in engine.typed_passive_rows.get(actor.entity_id,[]):
        if row.get('feature_id')==feature or (row.get('block')=='devil_heart_second_furnace' and row.get('kind')==feature.removeprefix(PREFIX)):
            if row.get('numbers'):return dict(row['numbers'])
    for action in engine.action_catalog.values():
        typed=action.parameters.get('typed') or {}
        if action.owner_id==actor.entity_id and typed.get('source')==feature and typed.get('numbers'):return dict(typed['numbers'])
    return numbers_of(engine,actor)


def owns(engine, actor, feature=SEED):
    return owned(engine, actor, feature) and int(source_numbers(engine,actor,feature).get('cl',1)) >= LEVELS[FEATURES.index(feature.removeprefix(PREFIX))]


def acquired(actor):
    return condition(actor, ORGAN) is not None


def engine_form(actor):
    return condition(actor, FORM)


def temp_hp(engine, actor, source):
    pb=int(numbers_of(engine,actor).get('pb',actor.proficiency_bonus))
    engine._grant_temp_hp(actor,pb,source,actor.entity_id)


def usable(engine, actor):
    organ=condition(actor,ORGAN)
    if not organ or organ.data.get('removed') or condition(actor,DORMANT) or not owns(engine,actor):return False
    cl=int(source_numbers(engine,actor).get('cl',1))
    for c in actor.conditions.values():
        if c.condition_id!=INTERFERENCE or not c.data.get('second_suppressed') or c.data.get('interrupt_next_activation'):continue
        d=c.data
        if (engine_form(actor) and d.get('ordinary_suppressed') and int(d['source_cl'])<cl
                and not d.get('multiple_systems') and not d.get('complete')):continue
        return False
    return True


def context(engine, actor, source=SEED):
    from .states import context as make
    numbers=source_numbers(engine,actor,source) if source.startswith(PREFIX) else numbers_of(engine,actor)
    ctx=make(engine,actor,source,[actor],numbers)
    if source not in engine.action_catalog:
        from dataclasses import replace
        from ..typed_numbers import authority_mechanics
        record=authority_mechanics().get(source,{})
        ctx=replace(ctx,action=ctx.action.model_copy(update={'source_definition_id':source,'owner_id':actor.entity_id,
            'display_name':record.get('name') or 'Second Furnace'}))
    ctx.intent=getattr(engine,'_active_intent',None)
    return ctx.with_source(source)


def choose(ctx, key, options, labels, prompt, *, optional=False, actor=None, automatic=None, cost='No additional cost'):
    subject=actor or ctx.actor
    return ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'SECOND_FURNACE',ctx.source,key,subject.entity_id),subject,
        'choice:needle.second_furnace.'+key,options,labels=labels,prompt=prompt,
        name='Second Furnace',feature_id=ctx.source,allow_decline=optional,default='decline' if optional else 'first',
        automatic_options=automatic,
        prompt_context={'cost':cost,'affected_id':subject.entity_id})


def reinforcement(ctx, *, overflow=False):
    from . import qi_path
    from .. import typed_executor as te
    options=['temp_hp','move','advantage']
    if qi_path.armament_condition(ctx.actor): options.append('armament')
    label='Devil Qi overflow' if overflow else 'Seed-Fed Reinforcement'
    labels={'temp_hp':'Gain Temporary Hit Points equal to '+('twice ' if engine_form(ctx.actor) else '')+'PB',
        'move':'Move up to 5 feet without Opportunity Attacks','armament':'Move your Domain Armament up to 10 feet',
        'advantage':'Advantage on your next Intimidation check before your next turn ends' if overflow else
            'Advantage on one Intimidation or Cultivation Check before your next turn ends'}
    selected=choose(ctx,'overflow' if overflow else 'seed_reinforcement',options,labels,
        f'{label}: {ctx.actor.display_name} gained Devil Qi. Choose one benefit; it costs no action or resource.')
    if not selected:return
    if selected[0]=='temp_hp':temp_hp(ctx.engine,ctx.actor,ctx.source)
    elif selected[0]=='move':te.run_effects(ctx,[{'type':'rider_step','distance_ft':5,'no_oa':True,'label':label}])
    elif selected[0]=='armament':
        from .devil_heart_second_furnace import move_armament_choice
        move_armament_choice(ctx,ctx.actor,10,feature_id=ctx.source,name=label)
    else:
        ctx.engine._apply_condition(ctx.actor,'condition:typed.second_furnace_advantage',ctx.source,ctx.actor.entity_id,
            expires_on=f'END_OF_SOURCE_TURN_AT:{ctx.actor.turns_started+1}',
            data={'cultivation':int(not overflow),'label':labels['advantage']})


def gain(engine, actor, trigger, *, limited=True):
    """One native gain attempt; independent trigger clocks survive cold reload."""
    if not usable(engine,actor):return False
    flag='_round_second_furnace_gain:'+trigger
    if limited and actor.turn_flags.get(flag)==engine.state.round_number:return False
    if limited:actor.turn_flags[flag]=engine.state.round_number
    if actor.resources.get(DEVIL,0)>=actor.resource_maximums.get(DEVIL,0):
        reinforcement(context(engine,actor),overflow=True)
        return False
    engine._gain_resource(actor,DEVIL,1,SEED)
    return True


def source_profile(engine, source):
    """Printed/compiled source classification, never guessed from an action name."""
    from ..typed_numbers import authority_mechanics
    action=engine.action_catalog.get(source)
    typed=(action.parameters.get('typed') or {}) if action else {}
    sid=str(typed.get('source') or typed.get('option_of') or source).removeprefix('passive:')
    row=authority_mechanics().get(sid,{})
    profile=dict(typed.get('cultivation_cost_profile') or {})
    from .source_eligibility import printed_text
    text=printed_text(sid)
    import re
    if re.search(r'(?im)^\s*(?:This|The) cost cannot be (?:further )?reduced[.\s]*$',text):profile['cannot_further_reduce']=1
    category=str(typed.get('source_category') or '').lower().replace('-','_')
    if category in ('artifact','legendary','secret_law','immortal_art'):profile[category]=1
    if (typed.get('duration') or {}).get('kind') in ('permanent','indefinite'):profile[(typed['duration']['kind'])]=1
    if row.get('kind')=='immortal_art':profile['immortal_art']=1
    for bundle in engine.typed_bundle_documents:
        declared=(bundle.get('second_furnace_native') or {}).get('cost_profiles',{}).get(source)
        if declared:
            native=bundle['second_furnace_native']
            from fractions import Fraction
            remaining=profile_expiry(declared)-Fraction(native.get('clock_num',native.get('clock_seconds',0)),native.get('clock_den',1))
            initial_round=int(native.get('initial_round',1))
            if remaining>0 and engine.state.round_number<initial_round+max(1,(remaining/6).__ceil__()):profile.update(declared['classification'])
    if sid.startswith(PREFIX) or row.get('sphere_id')=='tianxia.sphere.daemonic_cultivation' or subpath_daemonic(row.get('subpath_id')):profile['daemonic']=1
    kind=row.get('kind')
    profile['ordinary_qi']=bool((kind=='path_feature' and row.get('path_id')=='tianxia.path.qi_cultivation') or
        kind=='subpath_feature' and str(row.get('subpath_id','')).startswith('tianxia.subpath.qi.') or
        row.get('sphere_id') or row.get('recorded_art') or kind in ('recorded_art','forged_technique') or typed.get('forged_from') or
        (action and action.parameters.get('armament')) or profile.get('accepts_user_qi'))
    # Prerequisite structures are mechanical authority, independent of the
    # reservoir chosen for payment. Declarations may add, never erase them.
    required=list(profile.get('required_structures',[]))
    required.extend(row[key] for key in ('sphere_id','path_id','method_id') if row.get(key))
    if str(row.get('subpath_id','')).startswith('tianxia.subpath.qi.'):
        required.append('tianxia.path.qi_cultivation')
    profile['required_structures']=list(dict.fromkeys(required))
    # Known authority fields have priority over optional action-local exceptions.
    tags={str(t).lower().replace('-','_') for t in (row.get('tags') or []) if isinstance(t,str)}
    for tag in ('artifact','legendary','secret','secret_law','immortal','immortal_art'):
        if tag in tags:profile[tag]=1
    return profile


def qualifying_hostile(engine, owner, other, *, perceived=True):
    from ..relations import relation, ENEMY
    from ..target_knowledge import can_see
    if relation(engine,owner,other)!=ENEMY or not other.active:return False
    if engine._distance_actor_to_actor(owner,other)>60 or (perceived and not can_see(engine,owner,other)):return False
    if int(numbers_of(engine,other).get('cl',1))+5<int(numbers_of(engine,owner).get('cl',1)):return False
    # The world owner supplies subjective meaningful hostility; control, CL,
    # range, perception and actual expenditure/damage are native state checks.
    facts=[c for c in other.conditions.values() if c.condition_id==INTERFERENCE and c.data.get('beneficiary')==owner.entity_id]
    if other.summon and other.summon.get('owner_id')==owner.entity_id:return False
    return any(c.data.get('qualifying_hostility')==1 for c in facts) and not any(
        getattr(other,key,None)==owner.entity_id for key in ('summoner_id','controller_id','owner_id'))


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source!=PARENT or subject not in session.state['actors']:return None
    if kind=='source_access':return {'value_type':'document','maximum_seconds':2592000,'authority':'table_owner',
        'description':'Actual Daemonic Source granting this Subpath: source_rule and furnace nature. It grants access, not Qi Path attainment.'}
    if kind=='cost_profile':return {'value_type':'document','maximum_seconds':28800,'authority':'table_owner',
        'description':'An actual owned activation’s printed cost classifications and Source Rule quotation; no invented feature or item acquisition.'}
    if kind=='furnace_environment':return {'value_type':'document','maximum_seconds':28800,'authority':'table_owner',
        'description':'Source-scoped second-furnace context: explicit consecration, anti-daemonic suppression, destroyed structures, or meaningful hostility.'}
    if kind=='voluntary_price':return {'value_type':'document','maximum_seconds':28800,
        'description':'The affected creature’s controller accepts this exact permanent price from its Source Rule.'}
    if kind in ('stabilization_consent','repair_consent'):return {'value_type':'document','maximum_seconds':(2**53-1 if kind=='repair_consent' else 28800),
        'description':'The actual specialist’s controller accepts this specific patient and named repair/stabilization procedure.'}
    if kind=='repair':return {'value_type':'document','maximum_seconds':2**53-1,'authority':'table_owner',
        'description':'Actual medical, sealing, purification or Daemonic repair of an Unstable furnace, with Source Rule, specialist, Source CL and duration.'}
    if kind=='stabilization':return {'value_type':'document','maximum_seconds':28800,'authority':'table_owner',
        'description':'An actual physician, exorcist, seal master, Daemonic specialist, or self stabilization session and its Source CL.'}


@hook('journey_acquisition')
def acquire(session,actor_id,source,payload,owner_sheet):
    if source!=PARENT:return None
    require(set(payload)=={'access_scope'},'Choose this furnace’s actual source-access declaration.')
    actor=session.state['actors'][actor_id]
    access=read(session,PARENT,actor_id,'source_access',payload['access_scope'],actor_id)
    require(access is not None,'The native table owner must grant an actual Daemonic Source first.')
    value=access['value']
    require(set(value)=={'source_rule','nature'} and all(type(v) is str and v.strip() for v in value.values()),
        'Name the granting Source Rule and actual implanted or awakened furnace.')
    require(not actor['incapacitated'],'An incapacitated creature cannot initiate a second furnace.')
    sheet=copy.deepcopy(owner_sheet);paths=sheet.get('path_and_subpath') or {}
    attained=next((int(row[k]) for row in paths.get('paths',[]) if row.get('path_id')=='tianxia.path.qi_cultivation'
        for k in ('attainment','owning_path_level','effective_cl') if integer(row.get(k),1)),0)
    require(3<=attained<=int(sheet['identity']['cultivation_level']),'This requires actual Qi Path attainment of at least 3.')
    selections=set(paths.get('subpath_record_ids',[]))
    if paths.get('subpath_record_id'):selections.add(paths['subpath_record_id'])
    existing=set(paths.get('path_feature_record_ids',[]))|set(paths.get('source_granted_subpath_feature_record_ids',[]))
    require(not any(s.startswith('tianxia.subpath.qi.') and s!=PARENT for s in selections)
        and not any(s.startswith('tianxia.subpath.qi.') and not s.startswith(PREFIX) for s in existing),
        'Choose this as your Qi Subpath; an existing progression cannot be retained or reset by this procedure.')
    earned=[PREFIX+n for n,l in zip(FEATURES,LEVELS) if attained>=l]
    paths['source_granted_subpath_feature_record_ids']=earned
    paths['path_feature_record_ids']=list(dict.fromkeys([*[sid for sid in paths.get('path_feature_record_ids',[]) if not sid.startswith(PREFIX)],*earned]))
    paths['subpath_record_id']=PARENT;paths['subpath_record_ids']=list(dict.fromkeys([*sorted(selections),PARENT]))
    paths['subpath_acquisition']={'source_rule':value['source_rule'],'access_receipt':access['receipt_id'],
        'nature':value['nature'],'path_level':attained,'earned_features':earned}
    sheet['path_and_subpath']=paths
    actor.setdefault('source_states',{})[PARENT]={'acquired_sheet':canonical(sheet),'nature':value['nature'],
        'access_receipt':access['receipt_id'],'organ_removed':0,'dormant':0,'scene_id':session.state.get('scene_id',session.state['journey_id'])}
    session.emit('SECOND_FURNACE_ACQUIRED',actor_id,access_receipt=access['receipt_id'],features=earned,nature=value['nature'])
    return {'sheet':sheet,'acquisition_id':access['receipt_id']}


@hook('journey_source_sheet')
def acquired_sheet(sheet,session,actor_id):
    state=session.state['actors'][actor_id].get('source_states',{}).get(PARENT,{})
    if not state.get('acquired_sheet'):return None
    saved=json.loads(state['acquired_sheet'])
    result=copy.deepcopy(sheet);current=copy.deepcopy(sheet.get('path_and_subpath') or {})
    old=saved['path_and_subpath'];entry=old['subpath_acquisition']
    attained=next((int(row[k]) for row in current.get('paths',[]) if row.get('path_id')=='tianxia.path.qi_cultivation'
        for k in ('attainment','owning_path_level','effective_cl') if integer(row.get(k),1)),int(entry['path_level']))
    earned=list(dict.fromkeys([*entry['earned_features'],*[PREFIX+n for n,l in zip(FEATURES,LEVELS) if int(entry['path_level'])<l<=attained]]))
    for key in ('path_feature_record_ids','source_granted_subpath_feature_record_ids'):
        current[key]=list(dict.fromkeys([sid for sid in current.get(key,[]) if not sid.startswith(PREFIX)]+earned))
    current['subpath_record_id']=PARENT
    current['subpath_record_ids']=list(dict.fromkeys([*[sid for sid in current.get('subpath_record_ids',[]) if not sid.startswith('tianxia.subpath.qi.')],PARENT]))
    current['subpath_acquisition']={**entry,'path_level':max(attained,int(entry['path_level'])),'earned_features':earned}
    result['path_and_subpath']=current
    return result


@hook('compile_bundle')
def compile_organ(bundle,info):
    paths=info['owner_sheet'].get('path_and_subpath',{})
    entry=paths.get('subpath_acquisition',{})
    if paths.get('subpath_record_id')==PARENT and entry.get('access_receipt'):
        bundle['second_furnace_native']={'nature':entry['nature'],'access_receipt':entry['access_receipt']}
        path_cl=int(entry['path_level'])
        effective=next((r['effective_cl'] for r in paths.get('paths',[]) if r.get('path_id')=='tianxia.path.qi_cultivation' and integer(r.get('effective_cl'))),path_cl)
        path_cl=min(path_cl,int(effective))
        def scaled(existing):
            result={**existing,'cl':path_cl}
            if path_cl<int(entry['path_level']):
                pb=2+(max(1,path_cl)-1)//4
                delta=int(existing.get('pb',pb))-pb
                result['pb']=pb
                for key in ('save_dc','attack_bonus'):
                    if key in result:result[key]=int(result[key])-delta
            return result
        for row in [*bundle.get('typed_passives',[]),*bundle.get('typed_reactions',[])]:
            if str(row.get('feature_id','')).startswith(PREFIX) and row.get('numbers'):row['numbers']=scaled(row['numbers'])
        for action in bundle['action_catalog']:
            typed=action.get('parameters',{}).get('typed',{})
            if str(typed.get('source','')).startswith(PREFIX) and typed.get('numbers'):typed['numbers']=scaled(typed['numbers'])
    return bundle


@hook('journey_acquired')
@hook('journey_initialize')
def publish(session,actor_id,*args):
    actor=session.state['actors'][actor_id];state=actor.get('source_states',{}).get(PARENT)
    if not state:return
    from fractions import Fraction
    if state.get('clock_journey_id') and state['clock_journey_id']!=session.state['journey_id']:
        previous=Fraction(state['persisted_clock_num'],state['persisted_clock_den'])
        shift=session.clock()-previous
        if state.get('engine'):
            expiry=Fraction(state['engine']['expires_num'],state['engine']['expires_den'])+shift
            state['engine']['expires_num']=expiry.numerator;state['engine']['expires_den']=expiry.denominator
        for profile in [*state.get('environment',[]),*state.get('cost_profiles',{}).values()]:
            expiry=profile_expiry(profile)+shift
            profile['expires_num']=expiry.numerator;profile['expires_den']=expiry.denominator
            profile['expires_at']=expiry.__ceil__()
    state['clock_journey_id']=session.state['journey_id']
    state['persisted_clock_num']=session.clock().numerator;state['persisted_clock_den']=session.clock().denominator
    bundle=actor['bundle'];bundle['second_furnace_native']={k:copy.deepcopy(v) for k,v in state.items() if k!='acquired_sheet'}
    bundle['second_furnace_native']['clock_seconds']=int(session.clock())
    bundle['second_furnace_native']['clock_num']=session.clock().numerator
    bundle['second_furnace_native']['clock_den']=session.clock().denominator
    bundle['second_furnace_native']['environment']=[p for p in state.get('environment',[]) if profile_expiry(p)>session.clock()]
    engine=state.get('engine')
    pb=next((int((a.get('parameters',{}).get('typed',{}).get('numbers') or {}).get('pb',2)) for a in bundle['action_catalog'] if (a.get('parameters',{}).get('typed',{}).get('source'))==ENGINE),int(bundle['actor_template'].get('proficiency_bonus',2)))
    for pool in bundle['actor_template']['resources']:
        if pool['resource_id']==DEVIL:pool['maximum']=pb+(3 if engine else 0)
    from ..canonical import canonical_sha256
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)


@hook('match_initialize')
def initialize(engine):
    for bundle in engine.typed_bundle_documents:
        native=bundle.get('second_furnace_native')
        actor=engine.state.actors.get(bundle['actor_id'])
        if not native or not actor or not owned(engine,actor,SEED):continue
        if not condition(actor,ORGAN):engine._apply_condition(actor,ORGAN,SEED,actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'nature':native['nature'],'access_receipt':native['access_receipt'],'removed':native.get('organ_removed',0),
                  'information_profile':{'tags':['daemonic','cultivated_organ'],'source_cl':int(source_numbers(engine,actor)['cl']),'permanent':1},
                  'label':'Second furnace: '+native['nature']})
        if native.get('dormant') and not condition(actor,DORMANT):
            engine._apply_condition(actor,DORMANT,ENGINE,actor.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Second furnace Dormant: Long Rest and one-hour stabilization required'})
        if native.get('scene_engine_used'):actor.turn_flags['_round_second_engine_used']=1
        for profile in native.get('environment',[]):
            target=engine.state.actors.get(profile['subject'])
            if target:
                from ..typed_executor import clock_expiry
                from fractions import Fraction
                seconds=max(Fraction(1),profile_expiry(profile)-Fraction(native.get('clock_num',native.get('clock_seconds',0)),native.get('clock_den',1)))
                engine._apply_condition(target,INTERFERENCE,profile['source_rule'],profile.get('source_actor_id'),
                    expires_on=clock_expiry(engine,'rounds',(seconds/6).__ceil__()),
                    data={**profile,'label':'Second-furnace source authority'})


@hook('journey_command')
def journey_command(session,actor_id,kind,payload):
    if kind not in ('furnace_environment','furnace_stabilize','furnace_repair','furnace_organ','furnace_cost_profile'):return None
    actor=session.state['actors'][actor_id];state=actor.get('source_states',{}).get(PARENT)
    require(state is not None,'This creature has not acquired a second furnace.')
    if kind=='furnace_cost_profile':
        require(set(payload)=={'scope'},'Choose a source-scoped printed-cost declaration.')
        record=read(session,PARENT,actor_id,'cost_profile',payload['scope'],actor_id)
        require(record is not None,'A native world-owner declaration of the printed cost is required.')
        value=record['value']
        require(set(value)=={'source_rule','quotation','classification'} and type(value['quotation']) is str and value['quotation'].strip(),
            'Quote the controlling printed Source Rule and provide its typed cost classification.')
        action=next((a for a in actor['bundle']['action_catalog'] if a['source_definition_id']==value['source_rule']),None)
        require(action is not None and action['owner_id']==actor_id,'Classify an actual acquired action owned by this creature.')
        keys={'legendary','artifact','secret','secret_law','immortal','immortal_art','permanent','indefinite','strategic_travel',
            'world_scale','expensive_materials','sacrifice','artifact_charges','lifespan','maximum_reduction','another_creature','cannot_further_reduce',
            'explicit_zero','accepts_user_qi','accepts_devil_qi','restores_devil_qi','daemonic','forced_corruption','required_structures'}
        require(isinstance(value['classification'],dict) and set(value['classification'])<=keys and all((k=='required_structures' and isinstance(v,list) and all(type(x) is str and x for x in v)) or (k!='required_structures' and type(v) is int and v in (0,1)) for k,v in value['classification'].items()),
            'Use only typed printed-cost flags with integer zero/one values.')
        state.setdefault('cost_profiles',{})[value['source_rule']]={**copy.deepcopy(value),'admission_receipt':record['receipt_id'],'expires_at':record['expires_at']}
        session.emit('SECOND_FURNACE_COST_CLASSIFIED',actor_id,receipt=record['receipt_id'],source=value['source_rule'])
    elif kind=='furnace_environment':
        require(set(payload)=={'scope'},'Choose a source-scoped environment declaration.')
        record=read(session,PARENT,actor_id,'furnace_environment',payload['scope'],actor_id)
        require(record is not None,'A live world-owner declaration is required.')
        profile=copy.deepcopy(record['value'])
        allowed={'source_rule','source_cl','subject','source_actor_id','beneficiary','qualifying_hostility','consecrated',
            'ward_object_id','ward_creature','activation_save','source_object_id','save_ability','on_fail_condition','irresistible','voluntary_permanent_price','voluntary_price_scope',
            'forbids_rerolls','forced_corruption','anti_daemonic','interrupt_next_activation','ordinary_suppressed','second_suppressed','save_dc','complete','multiple_systems','destroyed_structure','suppressed_structure','outside_structure'}
        require(set(profile)<=allowed and {'source_rule','source_cl','subject'}<=set(profile), 'Supply a typed source, Source CL and subject; no inferred tags.')
        require(type(profile['source_rule']) is str and profile['source_rule'] and integer(profile['source_cl'],1)
            and profile['subject'] in session.state['actors'],'Choose a real source, known Source CL and present subject.')
        identities={'source_rule','subject','source_actor_id','beneficiary','ward_object_id','source_object_id','save_ability',
            'on_fail_condition','destroyed_structure','suppressed_structure','voluntary_price_scope'}
        numeric={'source_cl','save_dc'}
        require(all((k in identities and type(v) is str and v) or (k in numeric and integer(v,1))
            or (k not in identities|numeric and type(v) is int and v in (0,1)) for k,v in profile.items()),
            'Use nonempty text identities, positive Source CL/save DC and integer zero/one flags.')
        require(not (profile.get('ordinary_suppressed') and profile.get('second_suppressed') and not profile.get('complete')
            and profile['source_cl']==int(actor['bundle'].get('cl',1))),
            'An equal-Source-CL ordinary effect must identify the furnace it suppresses; complete suppression must be explicit.')
        if profile.get('voluntary_permanent_price'):
            consent=read(session,PARENT,profile['subject'],'voluntary_price',profile.get('voluntary_price_scope',''),actor_id)
            require(consent is not None and consent['value']=={'source_rule':profile['source_rule'],'accepted':1},
                'A permanent price requires the affected creature’s own live source-scoped acceptance.')
            profile['consent_receipt']=consent['receipt_id']
        profile['admission_receipt']=record['receipt_id'];profile['expires_at']=record['expires_at']
        state.setdefault('environment',[]).append(profile)
        session.emit('SECOND_FURNACE_ENVIRONMENT',actor_id,receipt=record['receipt_id'],profile=profile)
    elif kind in ('furnace_stabilize','furnace_repair'):
        repairing=kind=='furnace_repair'
        require(set(payload)=={'scope'} and state.get('unstable' if repairing else 'dormant'),'An actual Unstable/Dormant furnace is required for this procedure.')
        record=read(session,PARENT,actor_id,'repair' if repairing else 'stabilization',payload['scope'],actor_id)
        require(record is not None,'An actual stabilization procedure and specialist must be declared.')
        p=record['value'];cl=int(actor['bundle'].get('cl',1))
        expected={'specialist','specialty','source_cl'} | ({'consent_scope'} if p.get('specialist')!=actor_id else set()) | ({'source_rule','quotation','duration_seconds'} if repairing else set())
        require(set(p)==expected and p['specialty'] in (('medical','sealing','purification','daemonic') if repairing else ('self','physician','exorcist','seal_master','daemonic'))
            and p['specialist'] in session.state['actors'] and integer(p['source_cl'],cl),'Use yourself or an equal/higher-CL physician, exorcist, seal master or Daemonic specialist.')
        specialist=session.state['actors'][p['specialist']]
        require(not specialist['incapacitated'] and int(specialist['bundle'].get('cl',0))==p['source_cl'],
            'The actual specialist must be available and use their committed Source CL.')
        require(p['specialty']!='self' or p['specialist']==actor_id,'Only the patient may perform self-stabilization.')
        consent=None
        if p['specialist']!=actor_id:
            consent=read(session,PARENT,p['specialist'],'repair_consent' if repairing else 'stabilization_consent',p['consent_scope'],actor_id)
            require(consent is not None and consent['value']=={'patient':actor_id,'procedure_scope':payload['scope']},
                'The actual specialist must consent to this patient and procedure and share that consent with the patient.')
        seconds=p['duration_seconds'] if repairing else 3600
        require(integer(seconds,1),'Supply the Source Rule’s actual positive procedure duration.')
        if repairing:require(all(type(p[k]) is str and p[k].strip() for k in ('source_rule','quotation')),'Quote the actual repair procedure.')
        session.tick(seconds)
        require(read(session,PARENT,actor_id,'repair' if repairing else 'stabilization',payload['scope'],actor_id) is not None,'The procedure’s source expired before stabilization completed.')
        if consent:require(read(session,PARENT,p['specialist'],'repair_consent' if repairing else 'stabilization_consent',p['consent_scope'],actor_id) is not None,
            'The specialist’s consent expired during the session.')
        if repairing:
            state['unstable']=0
            snapshot=actor.get('encounter_snapshot')
            if snapshot:snapshot['conditions']={k:v for k,v in snapshot['conditions'].items() if json.loads(v)['condition_id']!=UNSTABLE}
        else:
            state['stabilization_completed']=1
            if state.get('rest_completed'):clear_dormancy(actor,state)
        session.emit('SECOND_FURNACE_REPAIRED' if repairing else 'SECOND_FURNACE_STABILIZED',actor_id,receipt=record['receipt_id'],seconds=seconds)
    else:
        require(set(payload)=={'scope'},'Use a world-owner organ procedure declaration.')
        record=read(session,PARENT,actor_id,'furnace_environment',payload['scope'],actor_id)
        require(record is not None and set(record['value'])=={'organ_operation','source_rule'}
            and record['value']['organ_operation'] in ('removed','reconstructed','replaced'), 'Record actual surgical/conceptual removal or reconstruction, not ordinary retraining.')
        state['organ_removed']=int(record['value']['organ_operation']=='removed')
        snapshot=actor.get('encounter_snapshot')
        if snapshot:snapshot['conditions']={k:v for k,v in snapshot['conditions'].items() if json.loads(v)['condition_id']!=ORGAN}
        session.emit('SECOND_FURNACE_ORGAN_PROCEDURE',actor_id,receipt=record['receipt_id'],operation=record['value']['organ_operation'])
    publish(session,actor_id)
    return True


@hook('journey_rest')
def rest(session,actor_id):
    state=session.state['actors'][actor_id].get('source_states',{}).get(PARENT)
    if state and state.get('dormant'):
        state['rest_completed']=1
        if state.get('stabilization_completed'):clear_dormancy(session.state['actors'][actor_id],state)
    publish(session,actor_id)


@hook('journey_scene_end')
def scene_end(session,*args):
    for aid,actor in session.state['actors'].items():
        state=actor.get('source_states',{}).get(PARENT)
        if not state:continue
        state['scene_engine_used']=0;state['unstable']=0
        state['environment']=[]
        snapshot=actor.get('encounter_snapshot')
        if snapshot:
            snapshot['conditions']={k:v for k,v in snapshot['conditions'].items()
                if json.loads(v)['condition_id'] not in (UNSTABLE,'condition:typed.second_furnace_augmented_activation')}
        if DEVIL in actor['resources']:actor['resources'][DEVIL]=0
        publish(session,aid)


@hook('journey_encounter_settled')
def continue_state(session,actor_id,engine,actor):
    state=session.state['actors'][actor_id].get('source_states',{}).get(PARENT)
    if not state:return
    dormant=int(condition(actor,DORMANT) is not None)
    if dormant and not state.get('dormant'):
        state['rest_completed']=0;state['stabilization_completed']=0
    state['dormant']=dormant
    state['scene_engine_used']=int(bool(actor.turn_flags.get('_round_second_engine_used')))
    state['unstable']=int(condition(actor,UNSTABLE) is not None)
    if not engine_form(actor):state.pop('engine',None)
    publish(session,actor_id)


@hook('resource_gain_allowed')
def devil_gain_allowed(engine,actor,resource,amount,source):
    forced=source_profile(engine,source).get('forced_corruption') if resource==CORRUPTION and condition(actor,UNSTABLE) else False
    if resource==CORRUPTION and condition(actor,UNSTABLE):
        forced=forced or any(c.condition_id==INTERFERENCE and c.source_definition_id==source and c.data.get('forced_corruption')==1 for c in actor.conditions.values())
    if forced:
        from .forged_exhaustion import add
        add(engine,actor,1,source)
        return False
    if resource!=DEVIL or not owns(engine,actor):return None
    return usable(engine,actor) and source in (SEED,ENGINE)


@hook('state_event')
def native_triggers(engine,event):
    if event.event_type not in ('RESOURCE_SPENT','RESOURCE_GAINED','DAMAGE_COMMITTED'):return
    source_actor=engine.state.actors.get(event.actor_id)
    if event.event_type=='RESOURCE_GAINED' and event.payload.get('resource_id')==CORRUPTION and event.payload.get('gained',0)>0 and source_actor:
        if owns(engine,source_actor) and source_profile(engine,event.source_definition_id.removeprefix('passive:')).get('daemonic'):
            gain(engine,source_actor,'corruption')
        return
    for actor in list(engine.state.actors.values()):
        if not owns(engine,actor) or not usable(engine,actor) or source_actor is None or not qualifying_hostile(engine,actor,source_actor,perceived=event.event_type=='RESOURCE_SPENT'):continue
        if event.event_type=='RESOURCE_SPENT':
            from ..typed_executor import CP_POOLS
            if event.payload.get('resource_id') in CP_POOLS and event.payload.get('amount',0)>0:
                if not source_profile(engine,event.source_definition_id).get('restores_devil_qi'):gain(engine,actor,'hostile_expenditure')
        elif event.event_type=='DAMAGE_COMMITTED' and actor.entity_id in event.target_ids and int(event.payload.get('hp_before',actor.current_hp))*2<actor.maximum_hp:
            if event.payload.get('hp_damage',0)+event.payload.get('temporary_hp_absorbed',0)>0:gain(engine,actor,'hostile_damage')




@hook('ability_check_mode')
def reinforcement_mode(engine,actor,ability,skill,against):
    held=condition(actor,'condition:typed.second_furnace_advantage')
    if held and (str(skill).lower()=='intimidation' or held.data.get('cultivation') and str(skill).lower()=='cultivation'):
        return 'ADVANTAGE'


@hook('d20_finalized')
def consume_advantage(engine,roll,intent):
    scope=engine.d20_context(roll) or {}
    actor=engine.state.actors.get(roll.actor_id)
    if not actor or scope.get('kind')!='check':return
    held=condition(actor,'condition:typed.second_furnace_advantage')
    if held and (str(scope.get('skill','')).lower()=='intimidation' or held.data.get('cultivation') and scope.get('check_kind')=='cultivation'):
        from .condition_ownership import remove_instance
        remove_instance(engine,actor,held.instance_id,held.source_definition_id)


@hook('temp_hp_offered_bonus')
def engine_temp_hp(engine,actor,amount,source,source_actor_id,*,consume):
    if amount>0 and source.startswith(PREFIX) and engine_benefits(engine,actor):
        pb=int(numbers_of(engine,actor).get('pb',actor.proficiency_bonus))
        return max(0,2*pb-amount)


def price_damage(ctx, *, breach=False):
    from .. import typed_executor as te
    picked=choose(ctx,'breach_damage' if breach else 'engine_end_damage',['psychic','necrotic'],
        {'psychic':'Take Psychic damage','necrotic':'Take Necrotic damage'},
        f'{ctx.actor.display_name}: choose the type of 4d10 damage from '+('Furnace Breach (ignores Resistance and Temporary Hit Points).' if breach else 'the Engine ending (ignores Resistance).'))
    damage_type=picked[0] if picked else 'psychic'
    typed={**ctx.typed,'effects':[{'type':'ignore_resistance','damage_types':[damage_type]}]}
    from dataclasses import replace
    sub=replace(ctx,typed=typed,targets=[ctx.actor],target=ctx.actor,damage_source_flags=(*ctx.damage_source_flags,'cost_damage'))
    te.run_effects(sub,[{'type':'damage','applies_to':'self','dice':{'count':4,'sides':10},'damage_types':[damage_type],
        'bypass_temporary_hp':breach,'evidence':'Furnace Breach' if breach else 'End of the Engine'}])


def breach(ctx):
    require(not condition(ctx.actor,UNSTABLE),'An Unstable furnace cannot accept another Furnace Breach.')
    accepted=choose(ctx,'breach',['accept'],{'accept':'Accept 4d10 damage, blocked healing until your next turn ends, and an Unstable furnace'},
        f'{ctx.actor.display_name} has 10 Corruption. Accept a Furnace Breach to Overdraw?',optional=True,automatic=['accept'] if ctx.actor.current_hp>40 else [],
        cost='4d10 damage ignoring Resistance and Temporary Hit Points; healing blocked until your next turn ends; furnace Unstable')
    require(bool(accepted),'Overdraw canceled: a Furnace Breach was not accepted.')
    price_damage(ctx,breach=True)
    ctx.engine._apply_condition(ctx.actor,UNSTABLE,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'label':'Second furnace Unstable: first Devil Qi spend each turn deals PB Force damage; forced Corruption becomes Exhaustion'})
    ctx.engine._apply_condition(ctx.actor,'condition:typed.second_furnace_no_healing',ctx.source,ctx.actor.entity_id,
        expires_on=f'END_OF_SOURCE_TURN_AT:{ctx.actor.turns_started+1}',data={'rule':{'healing_denied':True},
            'label':'Furnace Breach: cannot regain Hit Points until your next turn ends'})
    form=engine_form(ctx.actor)
    if form:
        ctx.engine._apply_condition(ctx.actor,'condition:typed.second_furnace_engine_breached',ENGINE,ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED',data={'label':'This Engine suffered a Furnace Breach'})


@effect('second_furnace_engine')
def open_engine(ctx,eff):
    require(owns(ctx.engine,ctx.actor,ENGINE) and usable(ctx.engine,ctx.actor),'An available acquired second furnace is required.')
    require(not ctx.actor.turn_flags.get('_round_second_engine_used'),'Demon Emperor’s Second Engine is once per scene.')
    from ..typed_executor import clock_expiry
    expiry=clock_expiry(ctx.engine,'minutes',1)
    ctx.actor.turn_flags['_round_second_engine_used']=1
    ctx.engine._set_resource_maximum(ctx.actor,DEVIL,int(ctx.numbers['pb'])+3,ENGINE)
    ctx.engine._apply_condition(ctx.actor,FORM,ENGINE,ctx.actor.entity_id,expires_on=expiry,
        data={'label':'Demon Emperor’s Second Engine: 1 minute, Fly 40 feet and Hover; Necrotic/Psychic Resistance',
            'fly_speed_ft':40,'flight_hover':1,'rule':{'damage_resistances':['NECROTIC','PSYCHIC']},
            'corruption_start':ctx.actor.resources.get(CORRUPTION,0),'event_start':len(ctx.engine.events),'retain_removal_data':1})


@hook('candidate_allowed')
def furnace_candidates(engine,actor,candidate,action):
    if action is None:return None
    source=(action.parameters.get('typed') or {}).get('source',action.source_definition_id)
    if source not in (SEED,AUGMENT,CORE,COUNTER,ENGINE):return None
    if not owns(engine,actor,source):return False
    if source==ENGINE and actor.turn_flags.get('_round_second_engine_used'):return False
    if acquired(actor) and not usable(engine,actor):return False


@hook('turn_start')
def engine_pulse(engine,actor):
    if engine_benefits(engine,actor):gain(engine,actor,'engine_turn',limited=False)


@hook('event')
def ended(engine,event_type,kwargs):
    if event_type!='CONDITION_REMOVED':return
    event=kwargs.get('originating_event')
    ended_effect=kwargs.get('ended_effect')
    # The exact removed instance carries the state even after it is gone.
    if not ended_effect or ended_effect.get('condition_id')!=FORM:return
    actor=next((engine.state.actors[aid] for aid in event.target_ids if aid in engine.state.actors),None)
    if actor is None:return
    data=ended_effect.get('data') or {}
    ctx=context(engine,actor,ENGINE)
    gained=int(data.get('continued_corruption',0))+sum(int(e.payload.get('gained',0)) for e in engine.events[int(data.get('event_start',0)):]
        if e.event_type=='RESOURCE_GAINED' and e.actor_id==actor.entity_id and e.payload.get('resource_id')==CORRUPTION
        and e.source_definition_id.startswith(PREFIX))
    ctx.engine._set_resource_maximum(actor,DEVIL,int(ctx.numbers['pb']),ENGINE)
    if gained>=2:price_damage(ctx)
    if gained>=4:
        from .forged_exhaustion import add
        add(engine,actor,1,ENGINE)
    breached=condition(actor,'condition:typed.second_furnace_engine_breached')
    if breached:
        engine._remove_condition_instance(actor,breached.instance_id,ENGINE)
        engine._apply_condition(actor,DORMANT,ENGINE,actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'label':'Second furnace Dormant: complete a Long Rest and one-hour stabilization before gaining or spending Devil Qi'})


@hook('state_event')
def unstable_spend(engine,event):
    if event.event_type!='RESOURCE_SPENT' or event.payload.get('resource_id')!=DEVIL or not event.payload.get('amount'):return
    actor=engine.state.actors.get(event.actor_id)
    if not actor or not condition(actor,UNSTABLE) or actor.turn_flags.get('typed_once_turn:unstable_spend'):return
    actor.turn_flags['typed_once_turn:unstable_spend']=1
    from .. import typed_executor as te
    ctx=context(engine,actor)
    from dataclasses import replace
    ctx=replace(ctx,damage_source_flags=(*ctx.damage_source_flags,'cost_damage'))
    te.run_effects(ctx,[{'type':'damage','applies_to':'self','flat':int(ctx.numbers['pb']),'damage_types':['force']}])


@hook('armament_range_bonus')
def engine_armament_range(engine,actor):
    return 30 if engine_benefits(engine,actor) else None


@hook('armament_movement_bonus')
def engine_armament_movement(engine,actor):
    return 20 if engine_benefits(engine,actor) else None


@hook('choice_reactors')
def choice_owners(engine):
    return [a.entity_id for a in engine.state.actors.values() if owns(engine,a) or consecrated_cl(engine,a)>0]


@hook('resource_spend_allowed')
def devil_expenditure(engine,actor,resource,amount,source):
    if not owns(engine,actor):return None
    if resource==QI and amount>0 and ordinary_suppressed(actor):return False
    if resource!=DEVIL or amount<=0:return None
    # Historical compiled owners remain playable; native acquisitions carry
    # the persistent organ/recovery state and may not bypass it by rest/reload.
    if not acquired(actor):return None
    if not usable(engine,actor):return False
    profile=source_profile(engine,source)
    required=profile.get('required_structures',[])
    cl=int(source_numbers(engine,actor).get('cl',1))
    for c in actor.conditions.values():
        if c.condition_id!=INTERFERENCE:continue
        d=c.data
        if any(d.get(k) in required for k in ('destroyed_structure','suppressed_structure') if d.get(k)):return False
        if not d.get('ordinary_suppressed'):continue
        if d.get('outside_structure'):continue
        if engine_form(actor) and d['source_cl']<cl and not d.get('multiple_systems') and not d.get('complete'):continue
        if not owns(engine,actor,CORE):continue
        if d['source_cl']<cl:continue
        if d['source_cl']>=cl+3:return False
        if any(held.condition_id=='condition:typed.second_furnace_continuity' and held.data.get('interference_instance')==c.instance_id for held in actor.conditions.values()):continue
        ctx=context(engine,actor,CORE)
        accepted=choose(ctx,'continuity:'+c.instance_id,['save'],{'save':'Make a Constitution save to keep the second furnace usable until your next turn ends'},
            f'{actor.display_name}: ordinary Qi is suppressed. Make a Constitution save against DC {d.get("save_dc",0)} for Second-Furnace Continuity?',optional=True)
        if not accepted or not integer(d.get('save_dc'),1):return False
        roll=engine._roll_save(actor,'CON',d['save_dc'],c.source_definition_id,
            roll_context={'source_actor_id':d.get('source_actor_id'),
                'spec':{'source_cl':d['source_cl'],'source_object_id':d.get('source_object_id','')}})
        if roll is None or roll.total<d['save_dc']:return False
        engine._apply_condition(actor,'condition:typed.second_furnace_continuity',CORE,actor.entity_id,
            expires_on=f'END_OF_SOURCE_TURN_AT:{actor.turns_started+1}',data={'interference_instance':c.instance_id,'label':'Second-Furnace Continuity: usable against this effect until your next turn ends'})
    return True


@hook('observer_information_rows')
def furnace_diagnosis(engine,viewer):
    from ..senses import of,reach
    rows=[]
    for actor in engine.state.actors.values():
        held=condition(actor,ORGAN)
        if not held:continue
        senses=of(engine,viewer,seen=actor)
        if viewer is actor or ('qi_sensing' in senses and engine._distance_actor_to_actor(viewer,actor)<=reach(engine,viewer,'qi_sensing',actor)):
            rows.append({'kind':'declaration','viewer_id':viewer.entity_id,'authority_actor_id':actor.entity_id,
                'source_id':SEED,'details':{'text':actor.display_name+' has a real second furnace: '+held.data['nature']},
                'label':'Second furnace diagnosis'})
    return rows


@hook('presentation_hidden_conditions')
def private_context(engine,actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in (ORGAN,INTERFERENCE,'condition:typed.second_furnace_augmented_activation')]


@hook('activation_settlement', priority=-50)
def admitted_internal_response(ctx):
    """Native source-owner environmental event, scoped to an admitted furnace.

    GM declarations establish the unknown Source Rule/authority, not outcomes.
    Actual activation, dice, failed save, Reaction payment and backlash are native.
    The source may be a represented object without attributing it to a creature.
    """
    if not acquired(ctx.actor) or not source_profile(ctx.engine,ctx.action.source_definition_id).get('ordinary_qi'):return
    for held in list(ctx.actor.conditions.values()):
        if held.condition_id!=INTERFERENCE or not held.data.get('activation_save'):continue
        data=held.data
        object_id=data.get('source_object_id')
        if object_id and object_id not in ctx.engine.state.objects:raise ValueError('The declared source object is not present in this encounter.')
        key='typed_once_turn:furnace_environment:'+held.instance_id
        if ctx.actor.turn_flags.get(key):continue
        ctx.actor.turn_flags[key]=1
        actor_id=data.get('source_actor_id')
        if actor_id and actor_id not in ctx.engine.state.actors:raise ValueError('The declared source creature is not present.')
        ability=str(data.get('save_ability','')).upper()
        if ability not in ('STR','DEX','CON','INT','WIS','CHA') or not integer(data.get('save_dc'),1):
            raise ValueError('An admitted source must supply its actual save ability and DC.')
        roll=ctx.engine._roll_save(ctx.actor,ability,data['save_dc'],held.source_definition_id,
            roll_context={'source_actor_id':actor_id,'spec':{'source_cl':data['source_cl'],
                'source_object_id':object_id or '',**{k:int(data.get(k,0)) for k in
                    ('irresistible','voluntary_permanent_price','forbids_rerolls')}}})
        if roll is not None and roll.total<data['save_dc'] and data.get('on_fail_condition'):
            ctx.engine._apply_condition(ctx.actor,'condition:typed.'+data['on_fail_condition'],held.source_definition_id,
                actor_id,expires_on=f'END_OF_SOURCE_TURN_AT:{ctx.actor.turns_started+1}',
                data={'label':'Failed internal response: '+data['on_fail_condition']})


from contextvars import ContextVar
_LINK_PASS=ContextVar('second_furnace_link_pass',default=None)


def consecrated_routes(engine,actor,start,end):
    """Actual mapped Source records crossed by one Armament route."""
    from ..gate2_runtime_models import Position
    from ..observer_information import sources
    from ..object_geometry import target_cells
    ray=set(engine.grid.ray_cells(Position(x=start[0],y=start[1]),Position(x=end[0],y=end[1]))[1:])
    result=[]
    for row in sources(engine):
        if 'consecrated' not in row['tags'] or type(row.get('cl')) is not int:continue
        ward=bool(row.get('profile',{}).get('ward') or 'ward' in row['tags'])
        creature=bool(row.get('profile',{}).get('ward_creature') or 'consecrated_creature' in row['tags'])
        if not ward and not creature:continue
        if row.get('zone'):cells={(p.x,p.y) for p in row['zone'].affected_cells}
        elif row.get('holder_id') in engine.state.actors:cells=set(engine._actor_cells(engine.state.actors[row['holder_id']]))
        else:continue
        if ray&cells:result.append((row['id'],row['cl'],row.get('dc'),cells,ward))
    for holder in engine.state.actors.values():
        for c in holder.conditions.values():
            if c.condition_id!=INTERFERENCE or not c.data.get('consecrated'):continue
            obj=engine.state.objects.get(c.data.get('ward_object_id',''))
            if obj and not obj.destroyed:cells={(p.x,p.y) for p in target_cells(engine,obj)}
            elif c.data.get('ward_creature'):cells=set(engine._actor_cells(holder))
            else:continue
            if ray&cells:
                cl=int(c.data['source_cl']);result.append((c.instance_id,cl,c.data.get('save_dc'),cells,bool(obj)))
    return result


def armament_offer(engine,actor,start,end,*,link=False):
    rows=consecrated_routes(engine,actor,start,end)
    if any(tuple(end) in cells for _,_,_,cells,_ in rows):return False
    return not rows or link


def move_link(ctx,point,distance_ft):
    """Resolve printed ward checks then grant only this exact native movement."""
    from . import qi_path
    from ..typed_executor import resolve_opposed_check
    start=qi_path.armament_point(ctx.actor);end=(point.x,point.y)
    cl=int(ctx.numbers['cl'])
    for key,level,dc,cells,ward in consecrated_routes(ctx.engine,ctx.actor,start,end):
        if end in cells:return False
        if level<cl:continue
        if not ward or not integer(dc,1):return False
        answer=choose(ctx,'furnace_link_check:'+key,['check'],{'check':f'Make a Cultivation Check against DC {dc} to pass this consecrated ward'},
            f'Domain Armament Furnace Link: the ward is Source CL {level}. Attempt the Cultivation Check?',optional=True)
        if not answer:return False
        result=resolve_opposed_check(ctx,ctx.actor,{'kind':'cultivation','label':'Furnace Link Cultivation Check'},
            {'kind':'dc','dc':dc,'label':'Consecrated ward save DC'})
        if not result.success:return False
    token=_LINK_PASS.set((ctx.actor.entity_id,start,end))
    try:return bool(qi_path.move_armament(ctx.engine,ctx.actor,point,CORE,distance_ft=distance_ft))
    finally:_LINK_PASS.reset(token)


@hook('armament_route_allowed')
def armament_ward_gate(engine,actor,start,end,source):
    if not owns(engine,actor):return None
    finish=(end.x,end.y)
    if not consecrated_routes(engine,actor,start,finish):return None
    return _LINK_PASS.get()==(actor.entity_id,start,finish)


@hook('compile_bundle')
def engine_armament_actions(bundle,info):
    if not any(r.get('feature_id')==ENGINE for r in bundle.get('typed_passives',[])) and not any(
            a.get('parameters',{}).get('typed',{}).get('source')==ENGINE for a in bundle['action_catalog']):return bundle
    removed=set()
    for action in bundle['action_catalog']:
        if action.get('parameters',{}).get('typed',{}).get('source')==ENGINE:
            removed.update(r for r,n in action.get('costs',[]) if r.startswith('resource:uses.'))
            action['costs']=[row for row in action.get('costs',[]) if row[0] not in removed]
    if removed:
        bundle['actor_template']['resources']=[r for r in bundle['actor_template']['resources'] if r['resource_id'] not in removed]
    for action in list(bundle['action_catalog']):
        if action['parameters'].get('armament')!='attack':continue
        extra=copy.deepcopy(action);extra['source_definition_id']+='+second_furnace_engine_range'
        extra['range_ft']=int(action['range_ft'])+30
        extra['parameters']['second_furnace_engine_range']=1
        bundle['action_catalog'].append(extra);bundle['actor_template']['action_ids'].append(extra['source_definition_id'])
    return bundle


@hook('candidate_allowed')
def engine_armament_range_admission(engine,actor,candidate,action):
    if action is None:return None
    if action.parameters.get('second_furnace_engine_range'):return engine_benefits(engine,actor)
    if action.parameters.get('armament')=='attack' and engine_benefits(engine,actor) and any(
            a.owner_id==actor.entity_id and a.parameters.get('second_furnace_engine_range') for a in engine.action_catalog.values()):return False


def engine_benefits(engine,actor):
    return bool(engine_form(actor) and owns(engine,actor,ENGINE) and usable(engine,actor))


@hook('flight_grant_allowed')
def engine_flight_active(engine,actor,held):
    if held.condition_id==FORM:return engine_benefits(engine,actor)


@hook('condition_excluded')
def engine_rule_active(engine,actor,held):
    if held.condition_id==FORM and not engine_benefits(engine,actor):return True


def clear_dormancy(actor,state):
    """The two actual recovery procedures may be completed in either order."""
    state['dormant']=0;state['rest_completed']=0;state['stabilization_completed']=0
    snapshot=actor.get('encounter_snapshot')
    if snapshot:snapshot['conditions']={k:v for k,v in snapshot['conditions'].items() if json.loads(v)['condition_id']!=DORMANT}


def ordinary_suppressed(actor):
    return any(c.condition_id==INTERFERENCE and c.data.get('ordinary_suppressed') for c in actor.conditions.values())


@hook('resource_quote_allowed')
def resource_availability_quote(engine,actor,resource,amount,source):
    if not owns(engine,actor):return None
    if resource==QI and amount>0 and ordinary_suppressed(actor):return False
    if resource==DEVIL and amount>0 and acquired(actor):
        if not usable(engine,actor):return False
        required=source_profile(engine,source).get('required_structures',[])
        cl=int(source_numbers(engine,actor)['cl'])
        for c in actor.conditions.values():
            if c.condition_id!=INTERFERENCE:continue
            d=c.data
            if any(d.get(k) in required for k in ('destroyed_structure','suppressed_structure') if d.get(k)):return False
            if d.get('ordinary_suppressed') and owns(engine,actor,CORE) and d['source_cl']>=cl+3 and not d.get('outside_structure'):return False


from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def daemonic_subpaths():
    """Canonical access categories; a Forbidden name never supplies this tag."""
    path=Path(__file__).resolve().parents[2]/'non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json'
    doc=json.loads(path.read_text())
    return frozenset(row['canonical_id'] for row in doc['entries'] if (row.get('access') or {}).get('tier')=='daemonic')


def subpath_daemonic(source):
    return source in daemonic_subpaths() if source else False


def consecrated_cl(engine,target):
    """Actual protecting condition/zone Source CL, including full footprints."""
    from ..observer_information import sources
    from ..spatial_areas import zone_contains
    levels=[int(c.data['source_cl']) for c in target.conditions.values()
            if c.condition_id==INTERFERENCE and c.data.get('consecrated')==1]
    for source in sources(engine):
        if 'consecrated' not in source['tags'] or type(source.get('cl')) is not int:continue
        if source.get('holder_id')==target.entity_id or (source.get('zone') and zone_contains(engine,target,source['zone'])):
            levels.append(source['cl'])
    # This existing reviewed native source explicitly creates a Consecrated
    # Boundary. Read its real footprint and sealed numbers; never match names.
    for zone in engine.state.zones.values():
        if zone.active and zone.source_definition_id=='tianxia.talent.radiance.consecrated_boundary' and zone_contains(engine,target,zone):
            from ..observer_information import source_numbers as ongoing_numbers
            nums=zone.trigger_profile.get('numbers') or ongoing_numbers(engine,zone.source_definition_id,zone.owner_id)
            if type(nums.get('cl')) is int:levels.append(nums['cl'])
    return max(levels,default=0)


@hook('activation_accounting')
def causal_payments(engine):
    if any(owns(engine,a) for a in engine.state.actors.values()):return True


@hook('compile_passives')
def family_ownership(rows,info):
    """Ownership persists even for a passive with no active effect payload.

    Existing correct block rows win; this does not register a second consumer.
    The full sealed source numbers follow the owning path at compile_bundle.
    """
    result=list(rows)
    for name in FEATURES:
        source=PREFIX+name
        if source not in info['owned_ids']:continue
        existing=next((r for r in result if r.get('feature_id')==source),None)
        if existing is None:
            result.append({'feature_id':source,'block':'d20_rewrite' if source==COUNTER else 'devil_heart_second_furnace',
                'kind':name,'numbers':dict(info['numbers'])})
        elif not existing.get('numbers'):
            existing['numbers']=dict(info['numbers'])
    return result


@hook('journey_options')
def procedure_options(session,actor_id):
    if session.state['phase']!='travel':return None
    actor=session.state['actors'][actor_id];state=actor.get('source_states',{}).get(PARENT)
    if not state:return None
    result=[]
    for kind,command,required in (('repair','furnace_repair','unstable'),('stabilization','furnace_stabilize','dormant')):
        if not state.get(required):continue
        scopes={r['scope'] for r in session.state.get('fact_consent_admission',[]) if r['source']==PARENT and r['subject']==actor_id and r['kind']==kind}
        for scope in sorted(scopes):
            record=read(session,PARENT,actor_id,kind,scope,actor_id)
            if not record:continue
            p=record['value'];seconds=p.get('duration_seconds',3600)
            specialist=session.state['actors'].get(p.get('specialist'),{}).get('name','the declared specialist')
            result.append({'id':command+':'+scope,'kind':command,'payload':{'scope':scope},'auto_select':0,
                'label':f"{actor['name']}: {kind.title()} the second furnace with {specialist}; {seconds} seconds; no automatic healing or Qi restoration"})
    return result or None


@hook('journey_elapsed',priority=100)
def persist_source_clock(session,actor_id,before,seconds,moving):
    # An inactive Engine still has live source declarations and relative clocks.
    # New journeys cannot reset their remaining lifetime by starting at zero.
    publish(session,actor_id)


def profile_expiry(profile):
    """Exact source deadline after a native journey clock changes epoch."""
    from fractions import Fraction
    return Fraction(profile.get('expires_num',profile.get('expires_at',0)),profile.get('expires_den',1))
