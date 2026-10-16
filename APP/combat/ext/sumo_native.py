"""Sumo Open School acquisition, travel stance and skill procedures.

Uses the source admission owner's public journey contracts, native map geometry,
sealed Body attainment and actual skill provenance. Acquiring grants the full
printed progression through the attained level; no choice grants a feature id.
"""
from copy import deepcopy
import json
from . import hook, effect
from ..journey import require
from ..sumo_state import PREFIX,ROOTED,DECLINED,LEVELS,owns,rooted

PARENT='tianxia.subpath.body.sumo'
BODY='tianxia.path.body_refining'


def attainment(sheet):
    paths=sheet.get('path_and_subpath') or {}
    rows=[row for row in paths.get('paths',[]) if row.get('path_id')==BODY]
    if rows:
        return min(int(sheet['identity']['cultivation_level']),int(next((rows[0][k] for k in ('attained_cl','attainment','owning_path_level') if k in rows[0]),0)))
    return int(sheet['identity'].get('cultivation_level') or 0) if sheet['identity'].get('path')=='Body Refining' else 0


def saved(actor):
    return actor.get('source_states',{}).get(PARENT,{})


def write(actor,values):
    actor.setdefault('source_states',{}).setdefault(PARENT,{}).update(values)


@hook('fact_admission_schema')
def access_schema(session,source,subject,kind):
    if source!=PARENT or subject not in session.state['actors']:return None
    if kind=='lifting_access':return {'value_type':'document','maximum_seconds':86400,'authority':'table_owner','description':'The table owner confirms the identified unattended object is physically free to lift, with its actual Source Rule; mass comes from the native map profile.'}
    if kind!='school_access':return None
    return {'value_type':'document','maximum_seconds':2592000,'authority':'table_owner',
        'description':'The table owner records actual Open School instruction and Body attainment; this does not grant a Sphere or bypass progression.'}


@hook('journey_acquisition')
def acquire(session,actor_id,source,payload,sheet):
    if source!=PARENT:return None
    from ..fact_consent_admission import read,canonical
    require(set(payload)=={'access_scope'},'Choose the recorded Sumo Open School access.')
    actor=session.state['actors'][actor_id]
    require(not actor['incapacitated'],'A conscious practitioner must complete the school instruction.')
    access=read(session,PARENT,actor_id,'school_access',payload['access_scope'],actor_id)
    require(access is not None,'Record actual Open School instruction through the native table-owner input first.')
    value=access['value']
    require(set(value)=={'school','teacher','source_rule'} and value['school']==PARENT and all(type(value[k]) is str and value[k].strip() for k in ('teacher','source_rule')),
        'Name the school, actual teacher or institutional instruction, and governing Source Rule.')
    cl=attainment(sheet)
    require(cl>=3,'Sumo requires Body Refining attainment 3.')
    paths=sheet.setdefault('path_and_subpath',{})
    selected=list(paths.get('subpath_record_ids') or [])
    if paths.get('subpath_record_id'):selected.append(paths['subpath_record_id'])
    require(not any(s!=PARENT and s.startswith('tianxia.subpath.body.') for s in selected), 'A Body practitioner chooses one Subpath; resolve replacement before learning Sumo.')
    require(PARENT not in selected and not saved(actor).get('acquired_sheet'),'Sumo is already acquired; continuation cannot reset its state.')
    paths['subpath_record_id']=PARENT;paths['subpath_record_ids']=[PARENT]
    ids=list(paths.get('path_feature_record_ids') or [])
    require(not any(s.startswith('tianxia.subpath.body.') for s in ids),'Do not combine another Body progression with Sumo.')
    paths['path_feature_record_ids']=ids+[PREFIX+slug for slug,level in LEVELS.items() if cl>=level]
    paths['subpath_acquisition']={'source':PARENT,'access_receipt':access['receipt_id'],'path_level':cl}
    from .path_authority import journey_cl
    current=min(cl,journey_cl(session,actor_id,BODY,cl))
    write(actor,{'acquired_sheet':canonical(sheet),'rooted':int(current>=18),'declined':0,'source_cl':current})
    session.emit('SUMO_ACQUIRED',actor_id,source=PARENT,access_receipt=access['receipt_id'],body_attainment=cl,
        features=[PREFIX+s for s,l in LEVELS.items() if cl>=l])
    return {'sheet':sheet,'acquisition_id':access['receipt_id']}


@hook('journey_source_sheet')
def acquired_sheet(sheet,session,actor_id):
    text=saved(session.state['actors'][actor_id]).get('acquired_sheet')
    if not text:return None
    old=json.loads(text)
    result=deepcopy(sheet);paths=result.setdefault('path_and_subpath',{})
    old_paths=old['path_and_subpath']
    level=attainment(sheet)
    paths['path_feature_record_ids']=list(dict.fromkeys([s for s in paths.get('path_feature_record_ids',[]) if not s.startswith(PREFIX)]+[
        PREFIX+s for s,l in LEVELS.items() if l<=level]))
    for key in ('subpath_record_id','subpath_record_ids','subpath_acquisition'):paths[key]=deepcopy(old_paths[key])
    return result


def bundle_owns(actor,slug):
    bundle=actor['bundle']
    feature=PREFIX+slug
    return int((bundle.get('sumo_profile') or {}).get('body_cl',bundle.get('cl') or 0))>=LEVELS[slug] and (any(r.get('feature_id')==feature for r in bundle.get('typed_passives',[])) or any(
        ((a.get('parameters') or {}).get('typed') or {}).get('source')==feature for a in bundle.get('action_catalog',[])))


def journey_level(session,aid):
    from .path_authority import journey_cl
    actor=session.state['actors'][aid]
    learned=int((actor['bundle'].get('sumo_profile') or {}).get('body_cl',actor['bundle'].get('cl') or 0))
    return min(learned,journey_cl(session,aid,BODY,learned))


def journey_feature(session,aid,slug):
    return bundle_owns(session.state['actors'][aid],slug) and journey_level(session,aid)>=LEVELS[slug]


def journey_conscious(actor):
    snapshot=actor.get('encounter_snapshot') or {}
    if snapshot.get('current_hp',1)<=0:return False
    conditions=[json.loads(c) if isinstance(c,str) else c for c in snapshot.get('conditions',{}).values()]
    return not any(c.get('condition_id') in ('condition:typed.unconscious','condition:core.unconscious','condition:typed.life_unconscious','unconscious')
        for c in conditions)


def journey_touching(session,aid):
    actor=session.state['actors'][aid]
    if actor.get('carried_by') or actor.get('mounted_on'):return False
    from ..gate2_runtime_models import Position
    pos=Position.model_validate(actor['position'])
    return pos.z==0 or session.grid.roof_supported(pos) or session.grid.terrain_at((pos.x,pos.y,pos.z-1),'BLOCKED')


def journey_rooted(session,aid):
    actor=session.state['actors'][aid]
    if not journey_feature(session,aid,'rooted_stance') or not journey_conscious(actor) or not journey_touching(session,aid):return False
    state=saved(actor)
    return bool(state.get('rooted') or (journey_feature(session,aid,'immovable_god') and not state.get('declined')))


@hook('journey_options')
def options(session,actor_id):
    actor=session.state['actors'][actor_id]
    if not bundle_owns(actor,'rooted_stance') or not journey_conscious(actor):return None
    out=[]
    active=journey_rooted(session,actor_id)
    if active or saved(actor).get('rooted'):
        out.append({'id':'sumo:end','kind':'sumo_stance','payload':{'operation':'end'},'auto_select':0,
            'label':'End Rooted Stance freely; automatic rooting stays declined, including while the stance is dormant.'})
    if not journey_feature(session,actor_id,'rooted_stance') or actor['incapacitated']:return out or None
    if not active and journey_touching(session,actor_id) and (journey_feature(session,actor_id,'immovable_god') or saved(actor).get('bonus_window')!=int(session.clock()//6)):
        cost='free with Immovable God' if journey_feature(session,actor_id,'immovable_god') else 'Bonus Action'
        out.append({'id':'sumo:enter','kind':'sumo_stance','payload':{'operation':'enter'},'auto_select':0,
            'label':'Enter Rooted Stance ('+cost+'; no Stamina); requires supporting surface contact and lasts until its printed ending.'})
    if active and journey_feature(session,actor_id,'yokozuna_presence'):
        for ability in ('CON','CHA'):
            out.append({'id':'sumo:intimidate:'+ability,'kind':'sumo_intimidate','payload':{'ability':ability},'auto_select':0,
                'label':'Yokozuna Presence: roll '+('Constitution' if ability=='CON' else 'Charisma')+' (Intimidation); no printed action or Stamina cost; report the total to the table.'})
    for obj in session.state['battlefield'].get('map_objects',[]):
        if type(obj.get('weight_lb')) is int and obj.get('unattended') is True:
            out.append({'id':'sumo:lift:'+str(obj['id']),'kind':'sumo_lift_check','payload':{'object_id':obj['id']},'auto_select':0,
                'label':'Check the lifting limit for '+str(obj.get('name') or obj.get('label') or obj.get('kind') or 'object')+'; uses its native weight and table-owner physical-access declaration; this does not move or acquire the object.'})
    return out


@hook('journey_command')
def command(session,actor_id,kind,payload):
    if kind=='sumo_lift_check':return lift_check(session,actor_id,payload)
    if kind not in ('sumo_stance','sumo_intimidate'):return None
    actor=session.state['actors'][actor_id]
    ending=kind=='sumo_stance' and payload=={'operation':'end'}
    require(bundle_owns(actor,'rooted_stance') and journey_conscious(actor) and
        (ending or journey_feature(session,actor_id,'rooted_stance') and not actor['incapacitated']),
        'This conscious creature must own Rooted Stance; entry and checks require its active feature.')
    if kind=='sumo_stance':
        require(set(payload)=={'operation'} and payload['operation'] in ('enter','end'),'Choose enter or end Rooted Stance.')
        operation=payload['operation']
        if operation=='enter':
            require(journey_feature(session,actor_id,'immovable_god') or saved(actor).get('bonus_window')!=int(session.clock()//6),'Rooted Stance requires another Bonus Action; wait for the next six-second turn window.')
            # Validate support independently of an already active stance.
            write(actor,{'rooted':1,'declined':0,'source_cl':journey_level(session,actor_id)})
            require(journey_rooted(session,actor_id),'Rooting requires actual supporting surface contact.')
            if not journey_feature(session,actor_id,'immovable_god'):
                write(actor,{'bonus_window':int(session.clock()//6)})
                if travel_distance(session,actor_id)>journey_speed(session,actor_id)/2:write(actor,{'rooted':0})
        else:write(actor,{'rooted':0,'declined':1})
        session.emit('SUMO_STANCE_CHANGED',actor_id,rooted=int(saved(actor).get('rooted',0)),declined=int(operation=='end'))
    else:
        require(set(payload)=={'ability'} and payload['ability'] in ('CON','CHA') and journey_rooted(session,actor_id) and journey_feature(session,actor_id,'yokozuna_presence'),
            'While Rooted, choose Constitution or Charisma for Intimidation.')
        from ..gate2_rolls import DeterministicRollAuthority
        count=int(saved(actor).get('check_counter',0))
        roller=DeterministicRollAuthority(session.state['journey_id']+':sumo:'+actor_id+':'+str(count))
        bonus=intimidation_bonus(actor['bundle'],payload['ability'])
        roll=roller.d20(modifier=bonus,actor_id=actor_id,reason='CHECK:'+PREFIX+'yokozuna_presence:Intimidation')
        write(actor,{'check_counter':count+1})
        session.emit('SUMO_INTIMIDATION_ROLLED',actor_id,ability=payload['ability'],roll=roll.model_dump(mode='json'),
            log=actor['name']+' rolls '+payload['ability']+' (Intimidation): '+str(roll.total)+'. The table adjudicates the result.')
    return True


def intimidation_bonus(bundle,ability):
    numbers=next(((a.get('parameters',{}).get('typed') or {}).get('numbers') for a in bundle.get('action_catalog',[]) if (a.get('parameters',{}).get('typed') or {}).get('numbers')), {})
    profile=bundle['sumo_profile']
    base=profile['cha_mod'];chosen=profile['con_mod'] if ability=='CON' else profile['cha_mod']
    ranks=bundle.get('skill_proficiency',{})
    skills=bundle.get('skills',{})
    rank=next((v for k,v in ranks.items() if k.casefold()=='intimidation'),None)
    total=next((v for k,v in skills.items() if k.casefold()=='intimidation'),None)
    require(total is None or rank is not None,'Record Intimidation proficiency explicitly; a total cannot establish proficiency.')
    return (int(total) if total is not None else base)+chosen-base+(2 if rank else int(bundle.get('proficiency_bonus') or numbers.get('pb') or 0))


@hook('journey_properties')
def properties(session,actor_id):
    actor=session.state['actors'][actor_id]
    if not bundle_owns(actor,'rooted_stance'):return None
    active=journey_rooted(session,actor_id)
    solid=journey_touching(session,actor_id)
    steps=(1 if active else 0)+(2 if solid and journey_feature(session,actor_id,'immovable_god') else 0)
    capacity=int((actor['bundle'].get('carrying') or {}).get('capacity_lb') or 0)
    return {'sumo_rooted':int(active),'sumo_carrying_capacity_lb':capacity*(2**steps),
        'sumo_lifting_capacity_lb':2*capacity*(2**(1 if active else 0))}


@hook('journey_state_changed')
def journey_state(session,actor_id):
    actor=session.state['actors'][actor_id]
    if not bundle_owns(actor,'rooted_stance'):return
    if not journey_conscious(actor) or not journey_touching(session,actor_id):write(actor,{'rooted':0})
    elif journey_feature(session,actor_id,'immovable_god') and not saved(actor).get('declined') and not saved(actor).get('rooted'):
        write(actor,{'rooted':1,'source_cl':journey_level(session,actor_id)})


@hook('journey_snapshot_actor')
def export_snapshot(actor,session,actor_id,engine):
    from ..sumo_state import acquired
    if not acquired(engine,actor,'rooted_stance'):return None
    copy=actor.model_copy(deep=True)
    copy.conditions={key:c for key,c in copy.conditions.items() if c.condition_id not in (ROOTED,DECLINED)}
    return copy


@hook('journey_encounter_settled')
def export_stance(session,actor_id,engine,actor):
    from ..sumo_state import acquired
    if not acquired(engine,actor,'rooted_stance'):return
    condition=next((c for c in actor.conditions.values() if c.condition_id==ROOTED),None)
    write(session.state['actors'][actor_id],{'rooted':int(condition is not None),'source_cl':int((condition.data if condition else {}).get('source_cl',0)),
        'declined':int(any(c.condition_id==DECLINED for c in actor.conditions.values()))})


@hook('match_initialize')
def import_stance(engine):
    # journey_setup carries a source-owned sealed document on the bundle.
    for bundle in getattr(engine,'typed_bundle_documents',()):
        data=bundle.get('sumo_continuation')
        actor=engine.state.actors.get(bundle['actor_id'])
        from ..sumo_state import acquired,conscious,touching
        if not data or actor is None or not acquired(engine,actor,'rooted_stance'):continue
        if data['declined']:
            engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')
            engine._apply_condition(actor,DECLINED,PREFIX+'rooted_stance',actor.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Automatic rooting declined'})
        elif data['rooted'] and conscious(actor) and touching(engine,actor):
            engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')
            engine._apply_condition(actor,ROOTED,PREFIX+'rooted_stance',actor.entity_id,expires_on='UNTIL_REMOVED',
                data={'label':'Rooted Stance','source_cl':data['source_cl']})


@hook('journey_encounter_bundle')
def encounter_bundle(bundle,session,actor_id):
    actor=session.state['actors'][actor_id]
    if not bundle_owns(actor,'rooted_stance'):return None
    result=deepcopy(bundle)
    result['sumo_continuation']={'rooted':int(saved(actor).get('rooted',journey_rooted(session,actor_id))),'declined':int(saved(actor).get('declined',0)),'source_cl':int(saved(actor).get('source_cl',actor['bundle']['sumo_profile']['body_cl']))}
    return result


@hook('compile_actions')
def intimidation_actions(info):
    if PREFIX+'yokozuna_presence' not in info['owned_ids']:return None
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    out=[]
    for ability in ('CON','CHA'):
        out.append(ActionDefinition(source_definition_id='action:typed.'+info['short']+'.sumo_intimidate.'+ability,
            display_name='Yokozuna Presence: '+('Constitution' if ability=='CON' else 'Charisma')+' (Intimidation) check (Influence Action; no Stamina)',
            owner_id=info['actor_id'],economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='SELF',
            parameters={'player_only':True,'sumo_intimidate':ability,'typed':{'source':PREFIX+'yokozuna_presence',
                'numbers':{**info['numbers'],'ability_mods':dict(info['mods'])},'effects':[{'type':'sumo_intimidate','ability':ability}],'riders':[],'duration':{'kind':'instant'}}}))
    return out


@hook('candidate_allowed')
def intimidation_gate(engine,actor,candidate,action):
    if action is None:return None
    if action.parameters.get('sumo_intimidate') and not (owns(engine,actor,'yokozuna_presence') and rooted(engine,actor)):return False
    return None


@effect('sumo_intimidate')
def intimidation(ctx,row):
    if not owns(ctx.engine,ctx.actor,'yokozuna_presence') or not rooted(ctx.engine,ctx.actor):return
    bundle=next(b for b in ctx.engine.typed_bundle_documents if b['actor_id']==ctx.actor.entity_id)
    from . import run,floored
    bonus=intimidation_bonus(bundle,row['ability'])+sum(int(v) for v in run('check_bonus',ctx,ctx.actor) if type(v) is int)
    modes=run('skill_check_mode',ctx,ctx.actor,row['ability'],'Intimidation')
    with ctx.engine.d20_scope({'kind':'check','actor_id':ctx.actor.entity_id,'source_id':ctx.source,
        'source_actor_id':ctx.actor.entity_id,'ability':row['ability'],'skill':'Intimidation'}):
        roll=ctx.engine.roll_check(modifier=bonus,actor_id=ctx.actor.entity_id,reason='CHECK:'+PREFIX+'yokozuna_presence:Intimidation',
            ability=row['ability'],skill='Intimidation',modes=modes)
        roll=floored(ctx.engine,ctx.actor,roll,ability=row['ability'],skill='Intimidation')
    ctx.engine._record_roll(roll)
    ctx.engine._append_event('CHECK_ROLLED',ctx.source,actor_id=ctx.actor.entity_id,payload={'roll_id':roll.roll_id,'total':roll.total,
        'ability':row['ability'],'skill':'Intimidation','log':ctx.actor.display_name+' rolls Intimidation: '+str(roll.total)+'. The table adjudicates this total.'})


@hook('carrying_capacity')
def carrying_capacity(engine,actor,capacity):
    from .surface_contact import solid_contact
    from ..sumo_state import touching
    steps=(1 if rooted(engine,actor) else 0)+(2 if owns(engine,actor,'immovable_god') and touching(engine,actor) and solid_contact(engine,actor) else 0)
    return capacity*2**steps if steps else None


@hook('compile_bundle')
def seal_sumo_profile(bundle,info):
    sheet=info['owner_sheet'];paths=sheet.get('path_and_subpath') or {}
    if not any(s.startswith(PREFIX) for s in paths.get('path_feature_record_ids',[])):return None
    result=deepcopy(bundle)
    modifiers=next((a['parameters']['typed']['numbers']['ability_mods'] for a in bundle['action_catalog']
        if a.get('parameters',{}).get('sumo_intimidate')), {})
    result['sumo_profile']={'body_cl':attainment(sheet),'con_mod':modifiers.get('CON',0),'cha_mod':modifiers.get('CHA',0)}
    for row in result.get('typed_passives',[]):
        if str(row.get('feature_id') or '').startswith(PREFIX):row['cl']=attainment(sheet)
    return result


@hook('compile_action')
def body_action_authority(action,info):
    typed=action.parameters.get('typed') or {}
    if not str(typed.get('option_of') or typed.get('source') or '').startswith(PREFIX):return None
    level=attainment(info['owner_sheet'])
    parameters={**action.parameters,'typed':{**typed,'numbers':{**typed.get('numbers',{}),'cl':level}}}
    updates={'parameters':parameters}
    return action.model_copy(update=updates)


@hook('before_d20_bonus')
def intimidation_other_checks(engine,request,intent):
    """The normalized permission replaces only the ability modifier. Existing
    check modes, Expertise and unrelated contributions remain with the caller.
    Native explicit check scopes and documented legacy skill-suffixed reasons
    identify the skill; an attack/save or descriptive label never qualifies.
    """
    reason=str(request.get('reason') or '')
    if not reason.startswith('CHECK:') or reason.startswith('CHECK:'+PREFIX+'yokozuna_presence:'):return None
    actor=engine.state.actors.get(request.get('actor_id'))
    if actor is None or not (owns(engine,actor,'yokozuna_presence') and rooted(engine,actor)):return None
    context=engine.d20_context() or {}
    if context.get('kind')=='check' and context.get('actor_id')==actor.entity_id:
        skill=context.get('skill');ability=str(context.get('ability') or '').upper()
    else:
        skill=reason.rpartition(':')[2];ability='CHA'
    if str(skill or '').casefold()!='intimidation':return None
    bundle=next(b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id)
    profile=bundle['sumo_profile']
    base=next((int(v) for k,v in bundle.get('skills',{}).items() if k.casefold()=='intimidation'),profile['cha_mod'])
    proficiency=intimidation_bonus(bundle,'CHA')-base
    adjustment=0
    if ability=='CHA':
        from .needle import ask,checkpoint_id
        modifiers={'CHA':int(request['modifier'])+proficiency,
                   'CON':int(request['modifier'])+proficiency+profile['con_mod']-profile['cha_mod']}
        chosen=ask(engine,intent,checkpoint_id(engine,'sumo_intimidation_ability',actor.entity_id,reason,engine.roller.counter),
            actor,'choice:needle.sumo_intimidation_ability',list(modifiers),
            preferred=[max(modifiers,key=modifiers.get)],
            labels={a:('Charisma' if a=='CHA' else 'Constitution')+f' (Intimidation): {value:+d}' for a,value in modifiers.items()},
            name='Yokozuna Presence',target_id=actor.entity_id,
            prompt=f'Yokozuna Presence: while Rooted, {actor.display_name} may use Constitution instead of Charisma for this Intimidation check. No action, Reaction or Stamina cost.')
        if chosen and chosen[0]=='CON':adjustment=profile['con_mod']-profile['cha_mod']
    return proficiency+adjustment



def journey_speed(session,aid):
    actor=session.state['actors'][aid];bundle=actor['bundle'];carrying=bundle.get('carrying') or {}
    speed=int(carrying.get('speed_ft') or bundle['actor_template'].get('speed_ft') or 30)
    capacity=properties(session,aid)['sumo_carrying_capacity_lb']
    if float(carrying.get('weight_lb') or 0)>capacity:speed=min(speed,5)
    snapshot=actor.get('encounter_snapshot') or {}
    for text in snapshot.get('conditions',{}).values():
        condition=json.loads(text) if isinstance(text,str) else text
        if condition.get('condition_id') not in ('condition:typed.encumbered','condition:typed.unburdened','condition:typed.exhaustion'):
            speed+=int((condition.get('data') or {}).get('speed_delta') or 0)
    return max(0,speed-5*int(actor.get('exhaustion',0)))


def travel_distance(session,aid):
    from fractions import Fraction
    state=saved(session.state['actors'][aid])
    return Fraction(state.get('travel_num',0),state.get('travel_den',1)) if state.get('travel_window')==int(session.clock()//6) else Fraction(0)


@hook('journey_movement_progress')
def travel_progress(session,aid,started,ended,distance):
    from fractions import Fraction
    actor=session.state['actors'][aid]
    if not bundle_owns(actor,'rooted_stance') or actor.get('carried_by') or actor['incapacitated'] or ended<=started:return
    state=saved(actor);now=started
    while now<ended:
        window=int(now//6);until=min(ended,Fraction(6*(window+1)))
        prior=Fraction(state.get('travel_num',0),state.get('travel_den',1)) if state.get('travel_window')==window else Fraction(0)
        total=prior+distance*(until-now)/(ended-started)
        write(actor,{'travel_window':window,'travel_num':total.numerator,'travel_den':total.denominator})
        if saved(actor).get('rooted') and not journey_feature(session,aid,'immovable_god') and total>Fraction(journey_speed(session,aid),2):
            write(actor,{'rooted':0})
            session.emit('SUMO_STANCE_ENDED',aid,source=PARENT,reason='voluntary_distance',text=actor['name']+' ends Rooted Stance: willing travel exceeded half current Speed in a six-second turn window.')
        state=saved(actor);now=until


def lift_check(session,aid,payload):
    actor=session.state['actors'][aid]
    require(bundle_owns(actor,'rooted_stance') and not actor['incapacitated'] and journey_conscious(actor),'This conscious practitioner must own Sumo to use its lifting-limit procedure.')
    require(set(payload)=={'object_id'},'Choose the native map object.')
    obj=next((o for o in session.state['battlefield'].get('map_objects',[]) if str(o.get('id'))==str(payload['object_id'])),None)
    require(obj is not None and type(obj.get('weight_lb')) is int and obj['weight_lb']>=0 and obj.get('unattended') is True,'Record the actual unattended object and explicit weight in the native map editor first; names and size do not establish mass or access.')
    from ..gate2_runtime_models import Position
    require(session.grid.distance_ft(Position.model_validate(actor['position']),Position(x=obj['x'],y=obj['y'],z=int(obj.get('z',0))))<=5,'The object must be within physical reach.')
    from ..fact_consent_admission import read
    receipt=read(session,PARENT,aid,'lifting_access','object:'+str(obj['id']),aid)
    require(receipt is not None and set(receipt['value'])=={'object_id','movable','source_rule'} and receipt['value']['object_id']==obj['id'] and receipt['value']['movable']==1 and type(receipt['value']['source_rule']) is str and bool(receipt['value']['source_rule'].strip()),'The native table owner must confirm this object is physically free to lift; lifting does not uproot, acquire or move an attached object.')
    maximum=properties(session,aid)['sumo_lifting_capacity_lb'];allowed=int(obj['weight_lb']<=maximum)
    result={'object_id':obj['id'],'weight_lb':obj['weight_lb'],'maximum_lb':maximum,'allowed':allowed,'declaration_receipt':receipt['receipt_id'],'seconds':session.state['seconds']}
    write(actor,{'last_lift_check':result})
    session.emit('LIFTING_LIMIT_RESOLVED',aid,source=PARENT,**result,text=actor['name']+(' can' if allowed else ' cannot')+' lift the '+str(obj.get('name') or obj.get('label') or obj.get('kind') or 'object')+f" ({obj['weight_lb']} lb.; lifting limit {maximum} lb.). This checks permission; it does not move or acquire the object.")
    return True
