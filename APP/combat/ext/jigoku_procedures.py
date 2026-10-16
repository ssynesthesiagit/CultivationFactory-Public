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
    if source==SOURCE and kind=='rite_light_check':
        return {'value_type':'flag','authority':'subject','maximum_seconds':600,
                'description':'Whether this actual requested ordinary check is nonstrenuous during the cooling rite (1 yes, 0 no).'}
    if source==SOURCE and kind=='hazard':
        return {'value_type':'document','authority':'table_owner','maximum_seconds':86400,
                'description':'Actual mapped hazard origin and explicit anti-farming exclusions.'}
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
    selected=[]
    for field in ('subpath_id','subpath_record_id','subpath_record_ids','subpath_ids','chosen_subpath_id'):
        value=paths.get(field,[])
        selected.extend(value if isinstance(value,list) else [value])
    selected.extend(paths.get('path_feature_record_ids',[]))
    selected.extend(row.get('feature_id','') for row in paths.get('earned_feature_occurrences',[]) if isinstance(row,dict))
    selected.extend((sheet.get('spheres_and_talents') or {}).get('learned_talent_record_ids',[]))
    require(not any(str(i).startswith('tianxia.subpath.body.') and i!=SOURCE and not str(i).startswith(SOURCE+'.') for i in selected), 'Another Body Subpath progression is already recorded.')
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
    require(not parameters and session.state['phase']=='travel', 'Perform this uninterrupted rite outside the bound combat.')
    if source==COOL:require(session.state['actors'][aid].get('source_states',{}).get('jigoku:conflict_closed')==1,
            'Begin the cooling rite only after the table owner ends the current immediate conflict.')
    require(KEY in session.state['actors'][aid].get('source_states',{}),'Only a Jigoku practitioner can perform this rite.')
    if source==COOL:require(has(session,aid,COOLED),'There is no cooling aftermath to clear.')
    return {'seconds':600 if source==COOL else 7200,'label':'10-minute cooling rite' if source==COOL else 'full 2-hour Cultivation Session'}


@hook('activity_finished')
def finished(session,aid,row):
    if row['source'] not in (COOL,SESSION):return
    from .jigoku import COOLED
    from .directional_signals import SIGNAL
    remove={COOLED} if row['source']==COOL else {SIGNAL}
    stored=conditions(session,aid)
    for iid,encoded in list(stored.items()):
        c=json.loads(encoded)
        if c['condition_id'] in remove and c['source_definition_id'].removesuffix(':aftermath').removesuffix('.aftermath')==PREFIX+'asura_s_rage':del stored[iid]
    if row['source']==SESSION:
        actor=session.state['actors'][aid]
        ledger=actor.setdefault('source_states',{}).setdefault('jigoku:stamina_recovery',{})
        rest=int(actor.get('long_rests',0))
        if ledger.get('session_rest')!=rest:
            _recover_stamina(session,aid,None,SESSION)
            ledger['session_rest']=rest
    session.emit('JIGOKU_RITE_COMPLETED',aid,source=row['source'])


@hook('activity_command_interrupts')
def interrupts(session,aid,row,who,kind,payload):
    if row['source'] in (COOL,SESSION) and who==aid:
        return kind not in ('activity_work','activity_cancel','declare_fact','jigoku_scar_cover') and not (row['source']==COOL and _light_check(session,aid,kind,payload))


@hook('journey_options')
def options(session,aid):
    if KEY not in session.state['actors'][aid].get('source_states',{}) or session.state['phase']!='travel':return None
    from .jigoku import COOLED
    from .directional_signals import SIGNAL
    return [{'id':source,'kind':'activity_start','auto_select':0,'payload':{'source':source,'parameters':{}},'label':label}
            for source,cid,label in ((COOL,COOLED,'Begin a 10-minute uninterrupted cooling rite to restore Eat the Flame'),
                                    (SESSION,SIGNAL,'Begin a full 2-hour Cultivation Session; end Hell-Signaled and restore Stamina once per Long Rest')) if source==SESSION or has(session,aid,cid) and session.state['actors'][aid]['source_states'].get('jigoku:conflict_closed')==1]


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
        snapshot=(bundle.get('journey_setup') or {}).get('encounter_snapshot') or {}
        if any(json.loads(c)['condition_id']=='condition:typed.jigoku_scars' for c in snapshot.get('conditions',{}).values()):continue
        if record and actor is not None and not any(c.condition_id=='condition:typed.jigoku_scars' for c in actor.conditions.values()):
            engine._apply_condition(actor,'condition:typed.jigoku_scars',PREFIX+'hell_tempered',actor.entity_id,
                expires_on='UNTIL_REMOVED',data={k:record[k] for k in ('scar_locations','scar_appearance','covered')} | {'label':'Permanent Hell Scars: '+record['scar_appearance']})


@hook('observer_information_rows')
def information(engine,viewer):
    from .directional_signals import readings
    from ..senses import ordinary_sight_perceives
    rows=[{'kind':'direction','details':{'reading':reading},'label':'Hell-Signaled direction and relative Realm'} for reading in readings(engine,viewer)]
    from .jigoku import COOLED
    from .directional_signals import SIGNAL
    for held in viewer.conditions.values():
        if not _private_bodily_state(held):continue
        if held.condition_id=='condition:typed.jigoku_scars':
            details={'state':'Permanent Hell Scars','locations':held.data['scar_locations'],'appearance':held.data['scar_appearance'],
                     'coverage':'covered by clothing or armor' if held.data.get('covered') else 'visible'}
        elif held.condition_id==SIGNAL:details={'state':'Hell-Signaled','ends':'A full two-hour Cultivation Session'}
        elif held.condition_id==COOLED:details={'state':'Eat the Flame is unavailable','restores':'A ten-minute uninterrupted cooling rite after the conflict'}
        else:continue
        rows.append({'kind':'declaration','details':details,'label':details['state']})
    # A direct line of sight to physically uncovered scars is needed. Creature
    # Spheres/proficiencies are sealed compiler facts, never inferred from names.
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==viewer.entity_id),{})
    qualified=any(str(t).lower() in ('infernal','daemonic','exorcist','purification') for t in viewer.creature_types)
    qualified=qualified or any(int(rank)>0 and str(skill).lower() in ('arcana','medicine','religion') for skill,rank in bundle.get('skill_proficiency',{}).items())
    spheres={(a.get('parameters',{}).get('typed') or {}).get('sphere') for a in bundle.get('action_catalog',[])}
    qualified=qualified or bool(spheres.intersection({'tianxia.sphere.'+name for name in ('ash','daemonic_cultivation','fire','magma')}))
    for actor in engine.state.actors.values():
        if actor is viewer:continue
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
        snapshot=(bundle.get('journey_setup') or {}).get('encounter_snapshot') or {}
        if any(json.loads(c)['condition_id']==SCENE_CONDITION for c in snapshot.get('conditions',{}).values()):continue
        if scene and actor is not None:
            engine._apply_condition(actor,SCENE_CONDITION,SOURCE+'.scene_allowance',actor.entity_id,
                expires_on='UNTIL_REMOVED',data={**scene,'label':"Asura's Rage: scene allowance"})


@hook('state_event')
def spend_scene(engine,event):
    if event.event_type!='CONDITION_APPLIED' or event.payload.get('condition_id')!='condition:typed.state.asura_s_rage':return
    for aid in event.target_ids:
        actor=engine.state.actors[aid]
        state=actor.conditions.get(event.payload.get('instance_id'))
        captured=int((state.data.get('numbers') or {}).get('cl',0)) if state else 0
        if state is not None and captured>0 and state.data.get('source_cl')!=captured:
            engine._update_condition_data(actor,state,{**state.data,'source_cl':captured},state.source_definition_id)
        held=next((c for c in actor.conditions.values() if c.condition_id==SCENE_CONDITION),None)
        if held is not None and not held.data.get('rage_spent'):
            data={**held.data,'rage_spent':1,**({'rage_source_cl':captured} if captured>0 else {})}
            from .condition_events import drop_condition
            drop_condition(engine,actor,held.instance_id,PREFIX+'asura_s_rage')
            engine._apply_condition(actor,SCENE_CONDITION,SOURCE+'.scene_allowance',aid,expires_on='UNTIL_REMOVED',data=data)


@hook('candidate_allowed')
def rage_scene_allowed(engine,actor,candidate,action):
    if action is not None and ((action.parameters.get('typed') or {}).get('source')==PREFIX+'asura_s_rage' or action.source_definition_id==PREFIX+'asura_s_rage'):
        if any(c.condition_id==SCENE_CONDITION and c.data.get('rage_spent') for c in actor.conditions.values()):return False
    return None


@hook('journey_encounter_settled')
def import_scene(session,aid,engine,creature):
    if KEY not in session.state['actors'][aid].get('source_states',{}):return
    scar=next((c for c in creature.conditions.values() if c.condition_id=='condition:typed.jigoku_scars'),None)
    if scar is not None:session.state['actors'][aid]['source_states'][KEY]['covered']=int(scar.data['covered'])
    held=next((c for c in creature.conditions.values() if c.condition_id==SCENE_CONDITION),None)
    if held is not None:session.state['actors'][aid]['source_states'][SCENE]=deepcopy(held.data)


@hook('journey_scene_end')
def reset_scene(session,old,new):
    for aid,actor in session.state['actors'].items():
        if KEY not in actor.get('source_states',{}):continue
        actor['source_states'][SCENE]={'scene_id':new,'rage_spent':0}
        actor['source_states']['jigoku:conflict_closed']=1
        # The compiled paid action also owns a generic finite-use resource.
        # Reset only this source's scene use, never other abilities or pools.
        maxima={r['resource_id']:r['maximum'] for r in actor['bundle']['actor_template']['resources']}
        for action in actor['bundle'].get('action_catalog',[]):
            if (action.get('parameters',{}).get('typed') or {}).get('source')!=PREFIX+'asura_s_rage':continue
            for rid,amount in action.get('costs',[]):
                if rid.startswith('resource:uses.') and rid in maxima:
                    actor['resources'][rid]=maxima[rid]
                    session.emit('SOURCE_SCENE_USE_RESTORED',aid,source=PREFIX+'asura_s_rage',resource=rid,after=maxima[rid])
        for iid,encoded in list(conditions(session,aid).items()):
            if json.loads(encoded)['condition_id']==SCENE_CONDITION:del conditions(session,aid)[iid]

COVER='system:combat.jigoku_scar_cover'


@hook('match_start')
def cover_action(engine):
    from ..gate2_runtime_models import ActionDefinition
    if not any(b.get('jigoku_scars') for b in engine.typed_bundle_documents):return
    engine.action_catalog[COVER]=ActionDefinition(source_definition_id=COVER,display_name='Record physical covering of Hell Scars',
        owner_id='*',economy='NONE',resolution_kind='TYPED',target_kind='SELF',
        parameters={'free_primary':True,'typed':{'effects':[{'type':'jigoku_scar_cover'}],'numbers':{},'riders':[]},
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
    require(set(value)=={'hostile_to','cooperative','staged','weakened','captured','revived','controlled'}
            and isinstance(value['hostile_to'],list) and value['hostile_to']
            and len(value['hostile_to'])==len(set(value['hostile_to']))
            and set(value['hostile_to'])<=set(session.state['actors'])
            and all(type(value[k]) is int and value[k] in (0,1) for k in ('cooperative','staged','weakened','captured','revived','controlled')),
            'Record actual hostile recipients and every exclusion explicitly; names and damage types do not establish source history.')


@hook('journey_combat_bundle')
def export_hostility(bundle,session,aid):
    record=read(session,SOURCE,aid,'hostility','combat',aid)
    if record is None:return None
    bundle=deepcopy(bundle)
    bundle['jigoku_hostility_fact']={'value':record['value'],'receipt':record['receipt_id'],
        'authority':record['authority'],'expires_at':record['expires_at'],
        'remaining_seconds':record['expires_at']-int(session.clock()),
        'scene_id':session.state.get('scene_id',session.state['journey_id'])}
    return bundle


def hostility_fact(engine,actor):
    found,value=_current_world_fact(engine,actor.entity_id,'hostility','combat')
    if found:return value
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    record=bundle.get('jigoku_hostility_fact',{})
    # Combat uses its ordinary six-second round clock. Legacy snapshots with no
    # deadline/authority do not establish automatic source-history knowledge.
    if record.get('authority')!='table_owner' or type(record.get('remaining_seconds')) is not int:return {}
    if 6*max(0,int(engine.state.round_number)-1)>=record['remaining_seconds']:return {}
    return deepcopy(record.get('value',{}))


def known_hostility(engine,attacker,target):
    """AI can use only the GM's live native source-history declaration."""
    record=hostility_fact(engine,attacker)
    return target.entity_id in record.get('hostile_to',[]) and not any(record.get(k,1) for k in ('cooperative','staged','weakened','captured','revived','controlled'))


@hook('ai_candidate_allowed')
def ai_cover_allowed(engine,actor,candidate,action):
    if action is not None and action.source_definition_id==COVER:return False
    return None


@hook('journey_properties')
def journey_signals(session,aid):
    """Coarse, same-scene Hell-Signaled information outside initiative."""
    from ..observer_information import direction
    from ..gate2_runtime_models import Position
    from ..table_advance import realm_of
    from .directional_signals import SIGNAL
    viewer=session.state['actors'][aid]
    audience={str(t).lower() for t in viewer['bundle']['actor_template'].get('creature_types',[])}
    if not audience.intersection({'infernal','daemonic'}):return None
    readings=set();own_cl=viewer['bundle'].get('cl')
    if type(own_cl) is not int:return None
    from .scene_fields import journey_plane
    own_plane=journey_plane(session,aid)
    if own_plane is None:return None
    for subject_id,subject in session.state['actors'].items():
        if subject_id==aid:continue
        target_plane=journey_plane(session,subject_id)
        if target_plane is None or target_plane!=own_plane:continue
        if not any(json.loads(c)['condition_id']==SIGNAL and json.loads(c)['source_definition_id'].removesuffix(':aftermath').removesuffix('.aftermath')==PREFIX+'asura_s_rage' for c in conditions(session,subject_id).values()):continue
        source_cl=subject['bundle'].get('cl')
        if type(source_cl) is not int:continue
        start=Position.model_validate(viewer['position']);end=Position.model_validate(subject['position'])
        if session.grid.distance_ft(start,end)>5280:continue
        from .weather_signs import BANDS
        own=BANDS.index(realm_of(own_cl));other=BANDS.index(realm_of(source_cl))
        relative='higher Realm' if other>own else 'lower Realm' if other<own else 'same Realm'
        readings.add(direction(start,end)+': '+relative)
    return {'hell_signaled_directions':sorted(readings)} if readings else None


@hook('presentation_hidden_conditions')
def bookkeeping_hidden(engine,actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id in
            (SCENE_CONDITION,'condition:typed.jigoku_fire_exposure') or _private_bodily_state(c)]


@hook('journey_command')
def journey_cover(session,aid,kind,payload):
    if kind!='jigoku_scar_cover':return None
    record=session.state['actors'][aid].get('source_states',{}).get(KEY)
    require(record is not None and set(payload)=={'covered'} and type(payload['covered']) is int and payload['covered'] in (0,1),
            'Record whether clothing or armor physically covers your permanent Hell Scars; cosmetics cannot remove them.')
    record['covered']=payload['covered']
    for iid,encoded in list(conditions(session,aid).items()):
        c=json.loads(encoded)
        if c['condition_id']=='condition:typed.jigoku_scars':
            c['data']['covered']=payload['covered'];conditions(session,aid)[iid]=json.dumps(c,sort_keys=True)
    session.emit('JIGOKU_SCAR_COVERING_RECORDED',aid,covered=payload['covered'])
    return True


@hook('journey_options')
def journey_cover_options(session,aid):
    if KEY not in session.state['actors'][aid].get('source_states',{}) or session.state['phase']!='travel':return None
    return [{'id':'jigoku:scars:'+str(value),'kind':'jigoku_scar_cover','auto_select':0,'payload':{'covered':value},'label':label}
        for value,label in ((0,'Record that your Hell Scars are visible'),(1,'Record that clothing or armor covers your Hell Scars'))]


@hook('journey_check_profile')
def journey_scar_social(session,aid,spec):
    record=session.state['actors'][aid].get('source_states',{}).get(KEY)
    observer=session.state['actors'].get(spec.get('person'))
    if not record or record.get('covered') or observer is None or spec.get('person')==aid:return None
    from ..gate2_runtime_models import Position
    if not session.grid.line_of_sight(Position.model_validate(observer['position']),Position.model_validate(session.state['actors'][aid]['position'])):return None
    if any(json.loads(c)['condition_id'] in ('condition:typed.blinded','blinded') for c in conditions(session,spec['person']).values()):return None
    subject_conditions=[json.loads(c) for c in conditions(session,aid).values()]
    if any(c['condition_id'] in ('condition:typed.invisible','invisible') for c in subject_conditions):return None
    if spec['skill']=='Intimidation':return {'advantage':True}
    if spec['skill']=='Persuasion' and spec.get('problem') in ('harmless','orthodox','free_of_forbidden_cultivation'):
        return {'disadvantage':True}
    return None

HAZARDS='jigoku:hazard_scopes'
HAZARD_FLAGS=('staged','weakened','harmless','cosmetic','cooperative')


@hook('journey_world_fact_committed')
def validate_hazard(session,receipt,*,store=True):
    if receipt['source']!=SOURCE or receipt['kind']!='hazard':return
    value=receipt['value'];scope=receipt['scope']
    require(set(value)=={'created_by',*HAZARD_FLAGS} and type(value['created_by']) is str
            and (not value['created_by'] or value['created_by'] in session.state['actors'])
            and all(type(value[k]) is int and value[k] in (0,1) for k in HAZARD_FLAGS),
            'Record the actual creator and explicit staged, weakened, harmless, cosmetic and cooperative exclusions.')
    board=getattr(getattr(session,'engine',None),'battlefield_document',None) or session.state.get('battlefield',{})
    areas=board.get('map_terrain',[])
    mapped=(scope.startswith('zone:map:') and scope.removeprefix('zone:map:').isdigit()
            and 1<=int(scope.removeprefix('zone:map:'))<=len(areas))
    canonical=scope.removeprefix('source:') if scope.startswith('source:') else ''
    source_owned=(canonical and value['created_by']==receipt['subject'] and any(
        (a.get('parameters',{}).get('typed') or {}).get('source')==canonical
        for a in session.state['actors'][receipt['subject']]['bundle'].get('action_catalog',[])))
    require(mapped or source_owned,'Choose an actual mapped area or an installed creator-owned source.')
    if not store:return
    scopes=session.state['actors'][receipt['subject']].setdefault('source_states',{}).setdefault(HAZARDS,[])
    if scope not in scopes:scopes.append(scope)


@hook('journey_combat_bundle')
def export_hazards(bundle,session,aid):
    facts={}
    for scope in session.state['actors'][aid].get('source_states',{}).get(HAZARDS,[]):
        record=read(session,SOURCE,aid,'hazard',scope,aid)
        if record is not None:
            facts[scope]={'value':record['value'],'authority':record['authority'],'receipt':record['receipt_id'],
                          'remaining_seconds':record['expires_at']-int(session.clock())}
    if facts:
        bundle=deepcopy(bundle);bundle['jigoku_hazard_facts']=facts
        return bundle


def hazard_fact(engine,owner,area):
    found,value=_current_world_fact(engine,owner.entity_id,'hazard',area)
    if found:return value
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==owner.entity_id),{})
    record=bundle.get('jigoku_hazard_facts',{}).get(area,{})
    if record.get('authority')!='table_owner' or type(record.get('remaining_seconds')) is not int:return {}
    if 6*max(0,int(engine.state.round_number)-1)>=record['remaining_seconds']:return {}
    return deepcopy(record.get('value',{}))


def qualifying_map_hazard(engine,owner):
    from .damage_delivery import frame
    from ..zones import typed_zones, MAP_OWNER
    delivery=frame(engine)
    if delivery['hazard'] not in ('area','trap') or not delivery['area']:return False
    zone=next((z for z in typed_zones(engine) if z.zone_id==delivery['area'] and z.owner_id==MAP_OWNER),None)
    if zone is None:return False
    fact=hazard_fact(engine,owner,zone.zone_id)
    return bool(fact) and fact['created_by']!=owner.entity_id and not any(fact[k] for k in HAZARD_FLAGS)


def _recover_stamina(session,aid,amount,source):
    """Source consumer of native rest/activity clocks; no new rest schema."""
    actor=session.state['actors'][aid]
    pool=next((r for r in actor['bundle']['actor_template']['resources'] if r['resource_id']=='resource:core.stamina'),None)
    if pool is None:return
    maximum=int(pool['maximum']);before=int(actor['resources'].get('resource:core.stamina',0))
    after=min(maximum,before+(maximum if amount is None else amount))
    actor['resources']['resource:core.stamina']=after
    session.emit('JIGOKU_STAMINA_RECOVERED',aid,source=source,before=before,after=after)


@hook('journey_short_rest')
def short_rest_stamina(session,aid):
    actor=session.state['actors'][aid]
    if KEY not in actor.get('source_states',{}):return
    ledger=actor['source_states'].setdefault('jigoku:stamina_recovery',{})
    rest=int(actor.get('long_rests',0))
    if ledger.get('short_rest')!=rest:ledger.update(short_rest=rest,short_uses=0)
    if ledger.get('short_uses',0)>=2:return
    pool=next((r for r in actor['bundle']['actor_template']['resources'] if r['resource_id']=='resource:core.stamina'),None)
    if pool is None or actor['resources'].get('resource:core.stamina',0)>=int(pool['maximum']):return
    actor['source_states']['jigoku:short_rest_choice']={'amount':int(pool['maximum'])//2,
        'short_rest':int(actor['short_rests']),'long_rest':rest}
    session.emit('JIGOKU_SHORT_REST_RECOVERY_OFFERED',aid,amount=int(pool['maximum'])//2)


@hook('journey_rest')
def long_rest_stamina(session,aid):
    if KEY in session.state['actors'][aid].get('source_states',{}):_recover_stamina(session,aid,None,'long_rest')


RAGE_CLOCK='jigoku:rage_continuation'
RAGE_SOURCE=PREFIX+'asura_s_rage'
RAGE_STATE='condition:typed.state.asura_s_rage'


def _native_rage_state(engine,actor):
    for c in actor.conditions.values():
        if c.condition_id!=RAGE_STATE or c.source_actor_id!=actor.entity_id:continue
        action=engine.action_catalog.get(c.source_definition_id)
        if c.source_definition_id==RAGE_SOURCE or action is not None and (action.parameters.get('typed') or {}).get('source')==RAGE_SOURCE:return c
    return None


def _rage_remaining(engine,row):
    from .effect_durations import parse_round
    deadline=parse_round(row.expires_on)
    if deadline is None:return 0
    # A combat round and an outside-combat turn are both six seconds. Slot
    # ordering is retained on encounter re-entry; travel never grants a round.
    return max(0,(deadline[0]-int(engine.state.round_number))*6)


@hook('journey_snapshot_actor')
def rage_snapshot(actor,session,aid,engine):
    state=_native_rage_state(engine,actor)
    if state is None:return None
    copy=actor.model_copy(deep=True)
    copy.conditions={k:c for k,c in copy.conditions.items() if c.instance_id!=state.instance_id}
    copy.modifiers={k:m for k,m in copy.modifiers.items() if m.source_definition_id!=state.source_definition_id}
    return copy


@hook('journey_encounter_settled')
def rage_export(session,aid,engine,actor):
    states=session.state['actors'][aid].setdefault('source_states',{})
    state=_native_rage_state(engine,actor)
    if state is None:
        states.pop(RAGE_CLOCK,None)
        return
    seconds=_rage_remaining(engine,state)
    require(seconds>0,'An ended Rage must resolve its native ending before travel.')
    states[RAGE_CLOCK]={'remaining_seconds':seconds,'state':state.model_dump_json(),
        'modifiers':[m.model_dump_json() for m in actor.modifiers.values() if m.source_definition_id==state.source_definition_id],
        'source_cl':int(state.data['numbers']['cl'])}
    session.emit('JIGOKU_RAGE_CONTINUED',aid,remaining_seconds=seconds,source_cl=states[RAGE_CLOCK]['source_cl'])


@hook('journey_combat_bundle')
def rage_bundle(bundle,session,aid):
    clock=session.state['actors'][aid].get('source_states',{}).get(RAGE_CLOCK)
    if clock:
        bundle=deepcopy(bundle);bundle['jigoku_rage_continuation']=deepcopy(clock)
        return bundle


@hook('match_initialize')
def rage_import(engine):
    from .effect_durations import round_token
    from ..gate2_runtime_models import ConditionInstance,ModifierInstance
    for bundle in engine.typed_bundle_documents:
        clock=bundle.get('jigoku_rage_continuation');actor=engine.state.actors.get(bundle['actor_id'])
        if not clock or actor is None:continue
        from fractions import Fraction
        import math
        expiry=round_token(engine,math.ceil(Fraction(clock['remaining_seconds'])/6))
        state=ConditionInstance.model_validate_json(clock['state'])
        engine._apply_condition(actor,state.condition_id,state.source_definition_id,state.source_actor_id,expires_on=expiry,data=deepcopy(state.data))
        for encoded in clock['modifiers']:
            m=ModifierInstance.model_validate_json(encoded)
            engine._add_modifier(actor,m.source_definition_id,m.target_field,m.operation,m.value,m.applies_to,
                expires_on=expiry,source_actor_id=m.source_actor_id,application_id=m.application_id)


@hook('journey_elapsed')
def rage_elapsed(session,aid,before,seconds,moving):
    if session.state['phase']=='combat':return  # terminal native combat owns its own expiry/aftermath
    actor=session.state['actors'][aid];states=actor.get('source_states',{})
    clock=states.get(RAGE_CLOCK)
    if not clock:return
    from fractions import Fraction
    remaining=Fraction(clock['remaining_seconds'])-seconds
    if remaining>0:
        # Preserve subsecond progress without rounding it away on cold reload.
        clock['remaining_seconds']=str(remaining)
        return
    del states[RAGE_CLOCK]
    from .journey_path_resources import add_exhaustion
    from .jigoku import COOLED
    from .directional_signals import SIGNAL
    from ..gate2_runtime_models import ConditionInstance
    add_exhaustion(session,aid,1,RAGE_SOURCE)
    stored=conditions(session,aid)
    for cid,data in ((COOLED,{'label':'Eat the Flame is unavailable until a cooling rite after the scene'}),
                     (SIGNAL,{'label':'Hell-Signaled','audience':['infernal','daemonic']})):
        if any(json.loads(c)['condition_id']==cid and json.loads(c)['source_definition_id'].removesuffix(':aftermath').removesuffix('.aftermath')==RAGE_SOURCE for c in stored.values()):continue
        iid='journey:jigoku:'+cid+':'+str(len(session.state['events']))
        stored[iid]=ConditionInstance(instance_id=iid,condition_id=cid,source_definition_id=RAGE_SOURCE+':aftermath',source_actor_id=aid,target_id=aid,
            applied_sequence=len(session.state['events']),expires_on='UNTIL_REMOVED',data={**data,'source_cl':clock['source_cl']}).model_dump_json()
    session.emit('JIGOKU_RAGE_ENDED',aid,source=RAGE_SOURCE,source_cl=clock['source_cl'])


@hook('journey_properties')
def rage_properties(session,aid):
    clock=session.state['actors'][aid].get('source_states',{}).get(RAGE_CLOCK)
    return {'asura_rage_remaining_seconds':clock['remaining_seconds']} if clock else None


@hook('journey_snapshot_actor')
def ended_turn_bookkeeping(actor,session,aid,engine):
    """Per-turn Brand payment bookkeeping cannot block a later encounter turn."""
    if KEY not in session.state['actors'][aid].get('source_states',{}):return None
    cid='condition:typed.path_hit_limit.'+PREFIX+'flame_fist'
    ids={k for k,c in actor.conditions.items() if c.condition_id==cid and c.source_actor_id==aid}
    if not ids:return None
    copy=actor.model_copy(deep=True)
    for iid in ids:del copy.conditions[iid]
    return copy


@hook('journey_command')
def short_recovery_choice(session,aid,kind,payload):
    if kind!='jigoku_short_rest_recovery':return None
    require(set(payload)=={'recover'} and type(payload['recover']) is int and payload['recover'] in (0,1),'Choose whether to recover Stamina during this Short Rest.')
    actor=session.state['actors'][aid];states=actor.get('source_states',{})
    require(KEY in states,'Only the acquired practitioner owns this recovery choice.')
    pending=states.get('jigoku:short_rest_choice')
    require(pending is not None and pending['short_rest']==int(actor.get('short_rests',0))
            and pending['long_rest']==int(actor.get('long_rests',0)),'There is no current Short Rest recovery choice.')
    ledger=states['jigoku:stamina_recovery']
    if payload['recover']:
        require(ledger.get('short_uses',0)<2,'Both recoveries before the next Long Rest have been used.')
        _recover_stamina(session,aid,pending['amount'],'short_rest')
        ledger['short_uses']=ledger.get('short_uses',0)+1
    del states['jigoku:short_rest_choice']
    session.emit('JIGOKU_SHORT_REST_RECOVERY_CHOSEN',aid,recover=payload['recover'])
    return True


@hook('journey_options')
def short_recovery_options(session,aid):
    actor=session.state['actors'][aid];pending=actor.get('source_states',{}).get('jigoku:short_rest_choice')
    if KEY not in actor.get('source_states',{}) or pending is None or session.state['phase']!='travel':return None
    return [{'id':'jigoku:short_rest:'+str(value),'kind':'jigoku_short_rest_recovery','auto_select':0,
        'payload':{'recover':value},'label':label} for value,label in (
        (1,f"Recover up to {pending['amount']} Stamina from this Short Rest (twice per Long Rest)"),
        (0,'Decline Stamina recovery from this Short Rest'))]


@hook('journey_before_command')
def close_short_recovery(session,aid,kind,payload):
    actor=session.state['actors'][aid];states=actor.get('source_states',{})
    if KEY not in states or 'jigoku:short_rest_choice' not in states or kind in ('jigoku_short_rest_recovery','declare_fact','jigoku_scar_cover'):return
    # Automatic actors use only their own missing resource and available uses.
    # Explicitly choosing Decline remains available on human and AI turns.
    if actor.get('control_mode')=='LOCAL_AUTO':short_recovery_choice(session,aid,'jigoku_short_rest_recovery',{'recover':1})
    else:
        del states['jigoku:short_rest_choice']
        session.emit('JIGOKU_SHORT_REST_RECOVERY_CHOSEN',aid,recover=0)


@hook('journey_before_command')
def conflict_reopens(session,aid,kind,payload):
    if kind=='enter_combat':
        for actor in session.state['actors'].values():
            if KEY in actor.get('source_states',{}):actor['source_states'].pop('jigoku:conflict_closed',None)


BRAND_CLOCK = 'jigoku:brand_clock'


@hook('journey_tick_limit')
def brand_tick_limit(session, remaining):
    if session.state['phase'] != 'travel': return None
    from fractions import Fraction
    limits = [Fraction(a.get('source_states', {}).get(BRAND_CLOCK, {}).get('remaining_seconds', '6'))
              for aid, a in session.state['actors'].items() if journey_brands(session, aid)]
    return min(limits) if limits else None


def journey_brands(session, aid):
    """Exact persistent Brands, including bearers who do not practice Jigoku."""
    return {iid: json.loads(row) for iid, row in conditions(session, aid).items()
            if json.loads(row)['condition_id'] == 'condition:typed.burning'
            and json.loads(row).get('data', {}).get('brand_dice')}


@hook('journey_before_command')
def finish_brand_continuation(session, aid, kind, payload):
    if kind == 'finish':
        require(not any(journey_brands(session, who) for who in session.state['actors']),
                'Resolve the ongoing Burning Brand before finishing this journey: extinguish it with an Action '
                'or continue its damage and repeated saves. Other travel and combat choices remain available.')


@hook('journey_encounter_settled')
def brand_export(session, aid, engine, actor):
    states = session.state['actors'][aid].setdefault('source_states', {})
    if not journey_brands(session, aid):
        states.pop(BRAND_CLOCK, None)
    else:
        states[BRAND_CLOCK] = {'remaining_seconds': '6'}
    from ..journey_native import capture, KEY as NATIVE
    if NATIVE not in session.state and not any(c.data.get('brand_dice')
            for who in session.state['actors'] for c in engine.state.actors[who].conditions.values()): return
    exported = session.__dict__.setdefault('_jigoku_exported_actors', set())
    exported.add(aid)
    if exported == set(session.state['actors']):
        # Every actor's GM-resolved snapshot is now imported. Capturing during
        # the first actor callback could resurrect a later actor's ended effects.
        capture(session, engine)
        del session.__dict__['_jigoku_exported_actors']


@hook('journey_elapsed')
def brand_elapsed(session, aid, before, seconds, moving):
    if session.state['phase'] != 'travel' or not journey_brands(session, aid): return
    from fractions import Fraction
    from ..journey_native import load, commit, KEY as NATIVE
    from .jigoku import brand_burns
    from .effect_durations import sweep
    actor = session.state['actors'][aid]
    clock = actor.setdefault('source_states', {}).setdefault(BRAND_CLOCK, {'remaining_seconds':'6'})
    remaining = Fraction(clock['remaining_seconds']) - seconds
    while remaining <= 0 and journey_brands(session, aid):
        engine = load(session, aid)
        pulse_at = before + seconds + remaining
        saved = session.state[NATIVE]
        engine.state.round_number = int(saved['round']) + int((pulse_at-Fraction(saved['seconds']))//6)
        target = engine.state.actors[aid]
        target.turns_started += 1
        target.turn_flags['_round_journey_expiry'] = engine.state.round_number
        target.reaction_available = target.active and not actor['incapacitated']
        engine._expire_for_checkpoint('START_OF_TURN', aid)
        sweep(engine, target, 'START_OF_TURN')
        brand_burns(engine, target)
        engine._expire_for_checkpoint('END_OF_TURN', aid)
        sweep(engine, target, 'END_OF_TURN', ending_id=aid)
        commit(session, engine)
        session.emit('JIGOKU_BRAND_TURN', aid, pulse_seconds=str(pulse_at))
        remaining += 6
    if journey_brands(session, aid): clock['remaining_seconds'] = str(remaining)
    else: actor['source_states'].pop(BRAND_CLOCK, None)


def can_extinguish(session, aid, target):
    actor = session.state['actors'][aid]
    if actor['incapacitated'] or not journey_brands(session, target): return False
    if aid == target: return True
    from ..gate2_runtime_models import Position
    left = Position.model_validate(actor['position'])
    right = Position.model_validate(session.state['actors'][target]['position'])
    return session.grid.distance_cells(left, right) <= 1 and session.grid.line_of_sight(left, right)


@hook('journey_command')
def extinguish_brand(session, aid, kind, payload):
    if kind != 'jigoku_extinguish': return None
    require(set(payload) == {'target','instance'} and payload['target'] in session.state['actors'],
            'Choose a creature and one Burning Brand to extinguish.')
    target, iid = payload['target'], payload['instance']
    require(can_extinguish(session, aid, target) and iid in journey_brands(session, target),
            'Use an Action while able to act, on yourself or an adjacent burning creature.')
    del conditions(session, target)[iid]
    session.emit('JIGOKU_BRAND_EXTINGUISHED', aid, target=target, instance=iid,
                 text=f"{session.state['actors'][aid]['name']} uses an Action to extinguish one Burning Brand on {session.state['actors'][target]['name']}.")
    session.tick(6)
    return True


@hook('journey_options')
def extinguish_options(session, aid):
    if session.state['phase'] != 'travel': return None
    return [{'id':'jigoku:extinguish:'+iid,'kind':'jigoku_extinguish','auto_select':0,
             'payload':{'target':target,'instance':iid},
             'label':f"Use one Action (6 seconds) to extinguish one Burning Brand on {record['name']}; no check or equipment."}
            for target, record in session.state['actors'].items() if can_extinguish(session, aid, target)
            for iid in journey_brands(session, target)]


@hook('journey_native_damage')
def brand_interrupts_rite(session, aid, event):
    if event.source_definition_id != PREFIX+'flame_fist' or not event.payload.get('reduced_to', 0): return
    from .journey_activities import KEY as ACTIVITY
    from . import run_strict
    states = session.state['actors'][aid].get('source_states', {})
    row = states.pop(ACTIVITY, None)
    if row:
        run_strict('activity_interrupted', session, aid, row)
        session.emit('ACTIVITY_INTERRUPTED', aid, source=row['source'])


@hook('journey_native_loaded')
def native_rage_defenses(session, engine):
    """The same captured Rage defenses apply during a travel damage packet."""
    from ..gate2_runtime_models import ConditionInstance, ModifierInstance
    for aid, record in session.state['actors'].items():
        actor = engine.state.actors[aid]
        clock = record.get('source_states', {}).get(RAGE_CLOCK)
        # The journey continuation owns Rage's elapsed ending, not an old
        # encounter round token stored in the native damage context.
        actor.conditions = {i:c for i,c in actor.conditions.items() if c.condition_id != RAGE_STATE}
        actor.modifiers = {i:m for i,m in actor.modifiers.items() if m.source_definition_id != RAGE_SOURCE}
        if clock:
            c = ConditionInstance.model_validate_json(clock['state'])
            c.expires_on = 'UNTIL_REMOVED'
            actor.conditions[c.instance_id] = c
            for encoded in clock['modifiers']:
                m = ModifierInstance.model_validate_json(encoded)
                m.expires_on = 'UNTIL_REMOVED'
                actor.modifiers[m.modifier_id] = m


def _light_check(session,aid,kind,payload):
    """Allow actual nonstrenuous ordinary checks with the actor's scoped input."""
    if kind not in ('check_start','check_settle') or payload.get('merit')!=0:return False
    if kind=='check_start':
        scope=payload.get('scope')
        if not isinstance(scope,str):return False
        request=read(session,'journey:noncombat_check',aid,'request',scope,aid)
        if request is None or request['value'].get('check_kind','ability')!='ability':return False
    else:
        pending=session.state['actors'][aid].get('source_states',{}).get('journey:check',{})
        scope=pending.get('scope')
        if not isinstance(scope,str) or pending.get('spec',{}).get('check_kind','ability')!='ability':return False
    declaration=read(session,SOURCE,aid,'rite_light_check',scope,aid)
    return bool(declaration and declaration['value']==1)


@hook('fact_admission_validate')
def validate_native_world_input(session,source,subject,kind,scope,value):
    if source!=SOURCE:return None
    receipt={'source':source,'subject':subject,'kind':kind,'scope':scope,'value':value}
    if kind=='hostility':validate_hostility(session,receipt)
    elif kind=='hazard':validate_hazard(session,receipt,store=False)
    else:return None
    return True


def _current_world_fact(engine,subject,kind,scope):
    """Latest native world input supersedes the original sealed source snapshot."""
    from ..combat_world_facts import records,clock
    rows=[r for r in records(engine) if (r['source'],r['subject'],r['kind'],r['scope'])==(SOURCE,subject,kind,scope)]
    if not rows:return False,{}
    row=rows[-1]
    valid=row['authority']=='table_owner' and row['expires_at']>clock(engine)
    return True,deepcopy(row['value']) if valid else {}


def _private_bodily_state(condition):
    from .jigoku import COOLED
    from .directional_signals import SIGNAL
    return condition.condition_id in ('condition:typed.jigoku_scars',SIGNAL,COOLED) and condition.source_definition_id.startswith(PREFIX)


@hook('presentation_hidden_history_conditions')
def private_bodily_history(events):
    """Ordinary condition prose cannot identify a privately signaled creature."""
    from .directional_signals import SIGNAL
    from .jigoku import COOLED
    ids=[]
    for event in events:
        payload=event.get('payload',{}) if isinstance(event,dict) else event.payload
        source=event.get('source_definition_id','') if isinstance(event,dict) else event.source_definition_id
        retained=payload.get('gate3_condition_after') or payload.get('removed_condition') or {}
        cid=payload.get('condition_id') or retained.get('condition_id')
        if cid in ('condition:typed.jigoku_scars',COOLED) or cid==SIGNAL and str(retained.get('source_definition_id') or source).startswith(PREFIX):
            if payload.get('instance_id'):ids.append(payload['instance_id'])
    return ids or None
