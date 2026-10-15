"""Jigoku's native acquisition and post-scene bodily procedures.

Uses the shared source acquisition, fact admission and exclusive elapsed activity
contracts. No other Subpath is admitted and no caller can supply earned IDs.
"""
from copy import deepcopy
import json
from . import hook
from ..journey import require
from ..fact_consent_admission import read

SOURCE='tianxia.subpath.body.jigoku'
KEY='jigoku:acquisition'
PREFIX=SOURCE+'.feature.'
LEVELS=((3,'hell_tempered'),(6,'pain_eater'),(10,'flame_fist'),(14,'hellwalker'),(18,'asura_s_rage'))
COOL=SOURCE+'.cooling_rite'
SESSION=SOURCE+'.cultivation_session'


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source==SOURCE and kind=='hostility':
        return {'value_type':'document','authority':'table_owner','maximum_seconds':86400,
                'description':'Actual hostile intent and source history; explicitly exclude cooperative, staged, weakened, captured and repeatedly revived sources.'}
    if source==SOURCE and kind=='legal_access':
        return {'value_type':'text','authority':'table_owner','maximum_seconds':31536000,
                'description':'Name the actual Forbidden Method source granting legal access to Jigoku.'}


def overlay(sheet,record):
    sheet=deepcopy(sheet)
    paths=sheet.setdefault('path_and_subpath',{})
    paths['subpath_id']=SOURCE
    ids=paths.setdefault('path_feature_record_ids',[])
    # Re-derive progression from the installed character, never a supplied CL.
    cl=int(sheet['identity']['cultivation_level'])
    for level,name in LEVELS:
        if cl>=level and PREFIX+name not in ids:ids.append(PREFIX+name)
    return sheet


@hook('journey_source_sheet')
def acquired_sheet(sheet,session,aid):
    record=session.state['actors'][aid].get('source_states',{}).get(KEY)
    return overlay(sheet,record) if record else None


@hook('character_source_projection')
def durable_sheet(sheet,record):
    acquired=record.get('source_states',{}).get(KEY)
    return overlay(sheet,acquired) if acquired else None


@hook('journey_acquisition')
def acquire(session,aid,source,payload,sheet):
    if source!=SOURCE:return None
    actor=session.state['actors'][aid]
    require(set(payload)=={'scar_locations','scar_appearance','covered'},'Record the permanent scars, their appearance and physical covering.')
    require(all(type(payload[k]) is str and 0<len(payload[k])<=1000 for k in ('scar_locations','scar_appearance'))
            and type(payload['covered']) is int and payload['covered'] in (0,1),'Supply bounded scar descriptions and physical covering.')
    paths=sheet.get('path_and_subpath',{})
    require(int(sheet['identity']['cultivation_level'])>=3,'Jigoku requires CL3.')
    require('tianxia.path.body_refining' in paths.get('path_record_ids',[]) or sheet['identity'].get('path')=='Body Refining','Jigoku requires Body Refining.')
    require(not paths.get('subpath_id') or paths['subpath_id']==SOURCE,'Choose one Body Subpath; another progression cannot coexist with Jigoku.')
    require(not any(str(i).startswith('tianxia.subpath.body.') and not str(i).startswith(SOURCE+'.') for i in paths.get('path_feature_record_ids',[])), 'Another Body Subpath progression is already recorded.')
    require(KEY not in actor.get('source_states',{}),'Jigoku is already acquired.')
    access=read(session,SOURCE,aid,'legal_access','acquisition',aid)
    require(access is not None,'The table owner must record the actual legal Forbidden Method access first.')
    record={**deepcopy(payload),'access_receipt':access['receipt_id'],'source':access['value'],'acquired_at':int(session.clock())}
    actor.setdefault('source_states',{})[KEY]=record
    session.emit('SOURCE_ACQUIRED',aid,source=SOURCE,access_receipt=access['receipt_id'])
    return {'sheet':overlay(sheet,record),'acquisition_id':access['receipt_id']}


def conditions(session,aid):
    return session.state['actors'][aid].get('encounter_snapshot',{}).get('conditions',{})


def has(session,aid,cid):
    return any(json.loads(row)['condition_id']==cid for row in conditions(session,aid).values())


@hook('activity_spec')
def activity(session,aid,source,parameters):
    if source not in (COOL,SESSION):return None
    from .jigoku import COOLED
    from .directional_signals import SIGNAL
    require(not parameters and session.state['phase']=='travel' and session.state.get('scene_number',0)>0,
            'Begin this uninterrupted rite only after the table owner ends the immediate conflict.')
    require(KEY in session.state['actors'][aid].get('source_states',{}),'Only a Jigoku practitioner can perform this rite.')
    require(has(session,aid,COOLED) if source==COOL else has(session,aid,SIGNAL),'There is no matching aftermath to clear.')
    return {'seconds':600 if source==COOL else 7200,'label':'10-minute cooling rite' if source==COOL else 'full 2-hour Cultivation Session'}


@hook('activity_finished')
def finished(session,aid,row):
    if row['source'] not in (COOL,SESSION):return
    from .jigoku import COOLED
    from .directional_signals import SIGNAL
    remove={COOLED} if row['source']==COOL else {COOLED,SIGNAL}
    stored=conditions(session,aid)
    for iid,encoded in list(stored.items()):
        c=json.loads(encoded)
        if c['condition_id'] in remove and c['source_definition_id']==PREFIX+'asura_s_rage':del stored[iid]
    session.emit('JIGOKU_RITE_COMPLETED',aid,source=row['source'])


@hook('activity_command_interrupts')
def interrupts(session,aid,row,who,kind,payload):
    if row['source'] in (COOL,SESSION) and who==aid:
        return kind not in ('activity_work','activity_cancel','declare_fact')


@hook('journey_options')
def options(session,aid):
    if KEY not in session.state['actors'][aid].get('source_states',{}) or session.state['phase']!='travel':return None
    from .jigoku import COOLED
    from .directional_signals import SIGNAL
    if not session.state.get('scene_number',0):return None
    return [{'id':source,'kind':'activity_start','auto_select':0,'payload':{'source':source,'parameters':{}},'label':label}
            for source,cid,label in ((COOL,COOLED,'Begin a 10-minute uninterrupted cooling rite to restore Eat the Flame'),
                                    (SESSION,SIGNAL,'Begin a full 2-hour Cultivation Session to end Hell-Signaled')) if has(session,aid,cid)]


@hook('journey_combat_bundle')
def export_scars(bundle,session,aid):
    record=session.state['actors'][aid].get('source_states',{}).get(KEY)
    if record:
        bundle=deepcopy(bundle);bundle['jigoku_scars']=deepcopy(record)
        return bundle


@hook('match_initialize')
def scars_initialize(engine):
    for bundle in engine.typed_bundle_documents:
        record=bundle.get('jigoku_scars');actor=engine.state.actors.get(bundle['actor_id'])
        if record and actor is not None and not any(c.condition_id=='condition:typed.jigoku_scars' for c in actor.conditions.values()):
            engine._apply_condition(actor,'condition:typed.jigoku_scars',PREFIX+'hell_tempered',actor.entity_id,
                expires_on='UNTIL_REMOVED',data={k:record[k] for k in ('scar_locations','scar_appearance','covered')} | {'label':'Permanent Hell Scars: '+record['scar_appearance']})


@hook('observer_information_rows')
def information(engine,viewer):
    from .directional_signals import readings
    from ..senses import ordinary_sight_perceives
    rows=[{'kind':'direction','details':{'reading':reading},'label':'Hell-Signaled direction and relative Realm'} for reading in readings(engine,viewer)]
    # A direct line of sight to physically uncovered scars is needed. Creature
    # Spheres/proficiencies are sealed compiler facts, never inferred from names.
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==viewer.entity_id),{})
    qualified=any(str(t).lower() in ('infernal','daemonic','exorcist','purification') for t in viewer.creature_types)
    qualified=qualified or any(int(rank)>0 and str(skill).lower() in ('arcana','medicine','religion') for skill,rank in bundle.get('skill_proficiency',{}).items())
    spheres={(a.get('parameters',{}).get('typed') or {}).get('sphere') for a in bundle.get('action_catalog',[])}
    qualified=qualified or bool(spheres.intersection({'tianxia.sphere.'+name for name in ('ash','daemonic_cultivation','fire','magma')}))
    for actor in engine.state.actors.values():
        scar=next((c for c in actor.conditions.values() if c.condition_id=='condition:typed.jigoku_scars' and not c.data.get('covered')),None)
        if scar is not None and qualified and engine._distance_actor_to_actor(viewer,actor)<=30 and ordinary_sight_perceives(engine,viewer,actor):
            rows.append({'kind':'declaration','details':{'creature':actor.display_name,'recognition':'Forbidden bodily cultivation'},'label':'Recognize visible Hell Scars'})
    return rows or None

SCENE='jigoku:scene'
SCENE_CONDITION='condition:typed.jigoku_scene'


@hook('journey_combat_bundle')
def export_scene(bundle,session,aid):
    if KEY not in session.state['actors'][aid].get('source_states',{}):return None
    state=session.state['actors'][aid].get('source_states',{}).get(SCENE,{})
    bundle=deepcopy(bundle)
    bundle['jigoku_scene']={'scene_id':session.state.get('scene_id',session.state['journey_id']),
                           'rage_spent':int(state.get('rage_spent',0))}
    return bundle


@hook('match_initialize')
def scene_initialize(engine):
    for bundle in engine.typed_bundle_documents:
        scene=bundle.get('jigoku_scene');actor=engine.state.actors.get(bundle['actor_id'])
        if scene and actor is not None:
            engine._apply_condition(actor,SCENE_CONDITION,PREFIX+'asura_s_rage',actor.entity_id,
                expires_on='UNTIL_REMOVED',data={**scene,'label':"Asura's Rage: scene allowance"})


@hook('state_event')
def spend_scene(engine,event):
    if event.event_type!='CONDITION_APPLIED' or event.payload.get('condition_id')!='condition:typed.state.asura_s_rage':return
    for aid in event.target_ids:
        actor=engine.state.actors[aid]
        held=next((c for c in actor.conditions.values() if c.condition_id==SCENE_CONDITION),None)
        if held is not None and not held.data.get('rage_spent'):
            data={**held.data,'rage_spent':1}
            from .condition_events import drop_condition
            drop_condition(engine,actor,held.instance_id,PREFIX+'asura_s_rage')
            engine._apply_condition(actor,SCENE_CONDITION,PREFIX+'asura_s_rage',aid,expires_on='UNTIL_REMOVED',data=data)


@hook('candidate_allowed')
def rage_scene_allowed(engine,actor,candidate,action):
    if action is not None and action.source_definition_id==PREFIX+'asura_s_rage':
        if any(c.condition_id==SCENE_CONDITION and c.data.get('rage_spent') for c in actor.conditions.values()):return False
    return None


@hook('journey_encounter_settled')
def import_scene(session,aid,engine,creature):
    if KEY not in session.state['actors'][aid].get('source_states',{}):return
    held=next((c for c in creature.conditions.values() if c.condition_id==SCENE_CONDITION),None)
    if held is not None:session.state['actors'][aid]['source_states'][SCENE]=deepcopy(held.data)


@hook('journey_scene_end')
def reset_scene(session,old,new):
    for aid,actor in session.state['actors'].items():
        if KEY not in actor.get('source_states',{}):continue
        actor['source_states'][SCENE]={'scene_id':new,'rage_spent':0}
        for iid,encoded in list(conditions(session,aid).items()):
            if json.loads(encoded)['condition_id']==SCENE_CONDITION:del conditions(session,aid)[iid]

COVER=SOURCE+'.record_scar_covering'


@hook('match_start')
def cover_action(engine):
    from ..gate2_runtime_models import ActionDefinition
    if not any(c.condition_id=='condition:typed.jigoku_scars' for a in engine.state.actors.values() for c in a.conditions.values()):return
    engine.action_catalog[COVER]=ActionDefinition(source_definition_id=COVER,display_name='Record physical covering of Hell Scars',
        owner_id='*',economy='NONE',resolution_kind='TYPED',target_kind='SELF',
        parameters={'setting_only':True,'typed':{'effects':[{'type':'jigoku_scar_cover'}],'numbers':{},'riders':[]},
                    'description':'Record whether clothing or armor physically covers your permanent Hell Scars. Mundane cosmetics cannot hide them.'})


@hook('additional_actions')
def offer_cover(engine,actor):
    return [COVER] if COVER in engine.action_catalog and any(c.condition_id=='condition:typed.jigoku_scars' for c in actor.conditions.values()) else None


@hook('candidate_allowed')
def cover_allowed(engine,actor,candidate,action):
    if action is not None and action.source_definition_id==COVER:
        return any(c.condition_id=='condition:typed.jigoku_scars' for c in actor.conditions.values())
    return None


from . import effect


@effect('jigoku_scar_cover')
def record_cover(ctx,row):
    from .needle import ask,checkpoint_id
    from .condition_events import drop_condition
    held=next((c for c in ctx.actor.conditions.values() if c.condition_id=='condition:typed.jigoku_scars'),None)
    if held is None:return
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'jigoku_cover',ctx.actor.entity_id),ctx.actor,
        'choice:needle.jigoku_cover',['covered','visible'],labels={'covered':'Clothing or armor covers the scars','visible':'The scars are visible'},
        prompt=f'{ctx.actor.display_name}: record physical coverage of your permanent Hell Scars. Cosmetics cannot remove them.',
        automatic_options=['covered'] if held.data.get('covered') else ['visible'])
    if not picked:return
    data={**held.data,'covered':int(picked[0]=='covered')}
    drop_condition(ctx.engine,ctx.actor,held.instance_id,PREFIX+'hell_tempered')
    ctx.engine._apply_condition(ctx.actor,held.condition_id,PREFIX+'hell_tempered',ctx.actor.entity_id,expires_on='UNTIL_REMOVED',data=data)


def sees_scars(engine,observer,subject):
    from ..senses import ordinary_sight_perceives
    return engine.state.actors.get(getattr(observer,'entity_id',None)) is observer and observer is not subject and any(c.condition_id=='condition:typed.jigoku_scars' and not c.data.get('covered')
        for c in subject.conditions.values()) and ordinary_sight_perceives(engine,observer,subject)


@hook('ability_check_mode')
def scar_intimidation(engine,actor,ability,skill,against):
    if skill=='Intimidation' and sees_scars(engine,against,actor):return 'ADVANTAGE'
    return None


@hook('skill_check_mode')
def scar_persuasion(ctx,subject,ability,skill):
    if skill!='Persuasion' or subject is not ctx.actor or not sees_scars(ctx.engine,ctx.target,subject):return None
    from ..fact_consent_admission import admit_choice,combat_records
    scope=ctx.intent.intent_id+':persuasion:'+ctx.target.entity_id
    records=combat_records(ctx.engine,subject,source=PREFIX+'hell_tempered',kind='persuasion_purpose',scope=scope)
    record=records[-1] if records else admit_choice(ctx,subject,PREFIX+'hell_tempered','persuasion_purpose',scope,
        ['harmless','orthodox','free','other'],labels={'harmless':'Convince the creature you are harmless',
            'orthodox':'Convince the creature you are orthodox','free':'Convince the creature you are free of forbidden cultivation','other':'Another purpose'},
        prompt=f'{subject.display_name}: what are you trying to persuade {ctx.target.display_name} of? Your visible Hell Scars hinder only the three printed purposes.',
        expires_on='END_OF_CURRENT_TURN',readers=(ctx.target.entity_id,),automatic_options=['other'])
    return 'DISADVANTAGE' if record and record['value'] in ('harmless','orthodox','free') else None


@hook('journey_world_fact_committed')
def validate_hostility(session,receipt):
    if receipt['source']!=SOURCE or receipt['kind']!='hostility':return
    value=receipt['value']
    require(set(value)=={'hostile_to','cooperative','staged','weakened','captured','revived'}
            and isinstance(value['hostile_to'],list) and value['hostile_to']
            and len(value['hostile_to'])==len(set(value['hostile_to']))
            and set(value['hostile_to'])<=set(session.state['actors'])
            and all(type(value[k]) is int and value[k] in (0,1) for k in ('cooperative','staged','weakened','captured','revived')),
            'Record actual hostile recipients and every exclusion explicitly; names and damage types do not establish source history.')


@hook('journey_combat_bundle')
def export_hostility(bundle,session,aid):
    record=read(session,SOURCE,aid,'hostility','combat',aid)
    if record is None:return None
    bundle=deepcopy(bundle)
    bundle['jigoku_hostility_fact']={'value':record['value'],'receipt':record['receipt_id'],
        'scene_id':session.state.get('scene_id',session.state['journey_id'])}
    return bundle


def known_hostility(engine,attacker,target):
    """AI can use only the GM's explicit native source-history declaration."""
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==attacker.entity_id),{})
    record=bundle.get('jigoku_hostility_fact',{}).get('value',{})
    return target.entity_id in record.get('hostile_to',[]) and not any(record.get(k,1) for k in ('cooperative','staged','weakened','captured','revived'))


def hostility_fact(engine,actor):
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    return deepcopy(bundle.get('jigoku_hostility_fact',{}).get('value',{}))


@hook('ai_candidate_allowed')
def ai_cover_allowed(engine,actor,candidate,action):
    if action is not None and action.source_definition_id==COVER:return False
    return None
