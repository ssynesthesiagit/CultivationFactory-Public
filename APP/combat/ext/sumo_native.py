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
        return min(int(sheet['identity']['cultivation_level']),int(rows[0].get('attainment',0)))
    return int(sheet['identity'].get('cultivation_level') or 0) if sheet['identity'].get('path')=='Body Refining' else 0


def saved(actor):
    return actor.get('source_states',{}).get(PARENT,{})


def write(actor,values):
    actor.setdefault('source_states',{}).setdefault(PARENT,{}).update(values)


@hook('fact_admission_schema')
def access_schema(session,source,subject,kind):
    if source!=PARENT or subject not in session.state['actors'] or kind!='school_access':return None
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
    write(actor,{'acquired_sheet':canonical(sheet),'rooted':int(cl>=18),'declined':0})
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
    return int(bundle.get('cl') or 0)>=LEVELS[slug] and (any(r.get('feature_id')==feature for r in bundle.get('typed_passives',[])) or any(
        ((a.get('parameters') or {}).get('typed') or {}).get('source')==feature for a in bundle.get('action_catalog',[])))


def journey_rooted(session,aid):
    actor=session.state['actors'][aid]
    if actor['incapacitated'] or actor.get('carried_by') or actor.get('mounted_on'):return False
    # Travel has native support geometry. Explicit physical roof holds are
    # handled in combat; no narration invents a travel support surface.
    from ..gate2_runtime_models import Position
    from ..gate2_grid import SquareGrid
    pos=Position.model_validate(actor['position'])
    support=pos.z==0 or session.grid.roof_supported(pos) or session.grid.terrain_at((pos.x,pos.y,pos.z-1),'BLOCKED')
    state=saved(actor)
    return bool(support and (state.get('rooted') or (bundle_owns(actor,'immovable_god') and not state.get('declined'))))


@hook('journey_options')
def options(session,actor_id):
    actor=session.state['actors'][actor_id]
    if not bundle_owns(actor,'rooted_stance') or actor['incapacitated']:return None
    out=[]
    active=journey_rooted(session,actor_id)
    operation='end' if active else 'enter'
    out.append({'id':'sumo:'+operation,'kind':'sumo_stance','payload':{'operation':operation},'auto_select':0,
        'label':('End Rooted Stance freely; automatic rooting stays declined.' if active else 'Enter Rooted Stance (Bonus Action; no Stamina); ends on unsupported flight, willing teleport, excess voluntary movement or Unconsciousness.')})
    if active and bundle_owns(actor,'yokozuna_presence'):
        for ability in ('CON','CHA'):
            out.append({'id':'sumo:intimidate:'+ability,'kind':'sumo_intimidate','payload':{'ability':ability},'auto_select':0,
                'label':'Yokozuna Presence: roll '+('Constitution' if ability=='CON' else 'Charisma')+' (Intimidation); no printed action or Stamina cost; report the total to the table.'})
    return out


@hook('journey_command')
def command(session,actor_id,kind,payload):
    if kind not in ('sumo_stance','sumo_intimidate'):return None
    actor=session.state['actors'][actor_id]
    require(bundle_owns(actor,'rooted_stance') and not actor['incapacitated'],'This conscious creature must own Rooted Stance.')
    if kind=='sumo_stance':
        require(set(payload)=={'operation'} and payload['operation'] in ('enter','end'),'Choose enter or end Rooted Stance.')
        operation=payload['operation']
        if operation=='enter':
            # Validate support independently of an already active stance.
            write(actor,{'rooted':1,'declined':0})
            require(journey_rooted(session,actor_id),'Rooting requires actual supporting surface contact.')
        else:write(actor,{'rooted':0,'declined':1})
        session.emit('SUMO_STANCE_CHANGED',actor_id,rooted=int(operation=='enter'),declined=int(operation=='end'))
    else:
        require(set(payload)=={'ability'} and payload['ability'] in ('CON','CHA') and journey_rooted(session,actor_id) and bundle_owns(actor,'yokozuna_presence'),
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
    mods=numbers.get('ability_mods',{})
    base=int(mods.get('CHA',0));chosen=int(mods.get(ability,0))
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
    steps=(1 if active else 0)+(2 if active and bundle_owns(actor,'immovable_god') else 0)
    capacity=int((actor['bundle'].get('carrying') or {}).get('capacity_lb') or 0)
    return {'sumo_rooted':int(active),'sumo_carrying_capacity_lb':capacity*(2**steps),
        'sumo_lifting_capacity_lb':2*capacity*(2**(1 if active else 0))}


@hook('journey_state_changed')
def journey_state(session,actor_id):
    actor=session.state['actors'][actor_id]
    if bundle_owns(actor,'rooted_stance') and actor['incapacitated']:write(actor,{'rooted':0})


@hook('journey_snapshot_actor')
def export_snapshot(actor,session,actor_id,engine):
    if not owns(engine,actor,'rooted_stance'):return None
    copy=actor.model_copy(deep=True)
    copy.conditions={key:c for key,c in copy.conditions.items() if c.condition_id not in (ROOTED,DECLINED)}
    return copy


@hook('journey_encounter_settled')
def export_stance(session,actor_id,engine,actor):
    if not owns(engine,actor,'rooted_stance'):return
    write(session.state['actors'][actor_id],{'rooted':int(rooted(engine,actor)),
        'declined':int(any(c.condition_id==DECLINED for c in actor.conditions.values()))})


@hook('match_initialize')
def import_stance(engine):
    # journey_setup carries a source-owned sealed document on the bundle.
    for bundle in getattr(engine,'typed_bundle_documents',()):
        data=bundle.get('sumo_continuation')
        actor=engine.state.actors.get(bundle['actor_id'])
        if not data or actor is None or not owns(engine,actor,'rooted_stance'):continue
        if data['declined']:
            engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')
            engine._apply_condition(actor,DECLINED,PREFIX+'rooted_stance',actor.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Automatic rooting declined'})
        elif data['rooted']:
            from .sumo import enter_root
            from ..typed_executor import Context
            action=next(a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id and (a.parameters.get('typed') or {}).get('source')==PREFIX+'rooted_stance')
            enter_root(Context(engine,actor,action,None,action.parameters['typed'],[actor],actor,{}),{})


@hook('journey_encounter_bundle')
def encounter_bundle(bundle,session,actor_id):
    actor=session.state['actors'][actor_id]
    if not bundle_owns(actor,'rooted_stance'):return None
    result=deepcopy(bundle)
    result['sumo_continuation']={'rooted':int(journey_rooted(session,actor_id)),'declined':int(saved(actor).get('declined',0))}
    return result


@hook('compile_actions')
def intimidation_actions(info):
    if PREFIX+'yokozuna_presence' not in info['owned_ids']:return None
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    out=[]
    for ability in ('CON','CHA'):
        out.append(ActionDefinition(source_definition_id='action:typed.'+info['short']+'.sumo_intimidate.'+ability,
            display_name='Yokozuna Presence: '+('Constitution' if ability=='CON' else 'Charisma')+' (Intimidation) check',
            owner_id=info['actor_id'],economy=EconomyKind.NONE,resolution_kind='TYPED',target_kind='SELF',
            parameters={'player_only':True,'free_primary':True,'sumo_intimidate':ability,'typed':{'source':PREFIX+'yokozuna_presence',
                'numbers':info['numbers'],'effects':[{'type':'sumo_intimidate','ability':ability}],'riders':[],'duration':{'kind':'instant'}}}))
    return out


@hook('candidate_allowed')
def intimidation_gate(engine,actor,candidate,action):
    if action.parameters.get('sumo_intimidate') and not (owns(engine,actor,'yokozuna_presence') and rooted(engine,actor)):return False
    return None


@effect('sumo_intimidate')
def intimidation(ctx,row):
    if not owns(ctx.engine,ctx.actor,'yokozuna_presence') or not rooted(ctx.engine,ctx.actor):return
    bundle=next(b for b in ctx.engine.typed_bundle_documents if b['actor_id']==ctx.actor.entity_id)
    bonus=intimidation_bonus(bundle,row['ability'])
    from ..typed_executor import check_mode
    with ctx.engine.d20_scope({'kind':'check','actor_id':ctx.actor.entity_id,'source_id':ctx.source,
        'source_actor_id':ctx.actor.entity_id,'ability':row['ability'],'skill':'Intimidation'}):
        roll=ctx.engine.roll_check(modifier=bonus,actor_id=ctx.actor.entity_id,reason='CHECK:'+ctx.source+':Intimidation',
            mode=check_mode(ctx.actor,row['ability'],'Intimidation',engine=ctx.engine))
    ctx.engine._record_roll(roll)
    ctx.engine._append_event('CHECK_ROLLED',ctx.source,actor_id=ctx.actor.entity_id,payload={'roll_id':roll.roll_id,'total':roll.total,
        'ability':row['ability'],'skill':'Intimidation','log':ctx.actor.display_name+' rolls Intimidation: '+str(roll.total)+'. The table adjudicates this total.'})


@hook('carrying_capacity')
def carrying_capacity(engine,actor,capacity):
    if not rooted(engine,actor):return None
    extra=2 if owns(engine,actor,'immovable_god') else 0
    return capacity*2**(1+extra)
