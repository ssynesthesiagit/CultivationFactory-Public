"""Typed GM-origin outside-combat afflictions, shared by rest consumers.

A declaration describes an actual external effect. The native world-owner path
commits it; creature commands cannot impersonate this producer. Names never
infer severity. Mechanical encounter effects retain their native save metadata.
"""
from copy import deepcopy
import json
from . import hook
from ..journey import require, integer

SOURCE = 'journey:external_effect'
KEY = 'journey:effects'
CATEGORIES = ('frightened', 'ordinary_nightmare', 'minor_sleep_disturbance', 'minor_mental_stress', 'other')


@hook('fact_admission_schema')
def schema(session, source, subject, kind):
    if source == SOURCE and kind in ('effect','classification','condition_profile'):
        return {'value_type':'document', 'authority':'table_owner', 'maximum_seconds':31536000,
                'description':'Actual externally sourced affliction with explicit severity and original saving throw.'}


@hook('journey_world_fact_committed')
def produce(session, receipt):
    if receipt['source'] != SOURCE:return
    row = receipt['value']
    if receipt['kind']=='classification':
        require(set(row)=={'effect_id','minor_category','evidence'} and row['minor_category'] in ('','ordinary_nightmare','minor_sleep_disturbance','minor_mental_stress')
                and type(row['evidence']) is str and bool(row['evidence'].strip()), 'Classify an actual effect with explicit ordinary/minor evidence.')
        stored=effects(session,receipt['subject'])
        require(row['effect_id'] in stored,'Classification needs an actual active effect identity.')
        stored[row['effect_id']]['minor_category']=row['minor_category']
        stored[row['effect_id']]['classification_receipt']=receipt['receipt_id']
        session.emit('EXTERNAL_EFFECT_CLASSIFIED',receipt['subject'],effect_id=row['effect_id'],receipt_id=receipt['receipt_id'])
        return
    if receipt['kind']!='effect':return
    validate_effect(row)
    stored = session.state['actors'][receipt['subject']].setdefault('source_states',{}).setdefault(KEY,{})
    require(row['id'] not in stored, 'An active effect identity cannot be overwritten.')
    stored[row['id']] = {**deepcopy(row), 'receipt':receipt['receipt_id'],**({'readers':list(dict.fromkeys([receipt['subject'],*receipt['readers']]))} if row['category'] in AFFLICTION_CATEGORIES else {})}
    session.emit('EXTERNAL_EFFECT_APPLIED', receipt['subject'], effect_id=row['id'], source=row['source'])


def effects(session, aid):
    return session.state['actors'][aid].get('source_states',{}).get(KEY,{})


def end(session, aid, effect_id, source):
    require(effect_id in effects(session, aid), 'Choose an active effect.')
    del effects(session, aid)[effect_id]
    # Encounter snapshots remain the native source of imported afflictions.
    snapshot = session.state['actors'][aid].get('encounter_snapshot',{})
    for iid, encoded in list(snapshot.get('conditions',{}).items()):
        row=json.loads(encoded)
        if iid==effect_id or row.get('data',{}).get('journey_effect_id')==effect_id:
            del snapshot['conditions'][iid]
    session.emit('JOURNEY_EFFECT_ENDED', aid, effect_id=effect_id, source=source)


@hook('journey_combat_bundle')
def export(bundle, session, aid):
    if not effects(session,aid): return None
    bundle = deepcopy(bundle); bundle['journey_external_effects'] = deepcopy(effects(session,aid))
    return bundle


@hook('match_initialize')
def setup(engine):
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None: continue
        for iid,row in bundle.get('journey_external_effects',{}).items():
            for name in condition_names(row):
                if any(c.data.get('journey_effect_id')==iid and c.condition_id=='condition:typed.'+name for c in actor.conditions.values()):continue
                data={'label':row['label'],'journey_effect_id':iid}
                if row['save_ability']:data['origin_save']={'ability':row['save_ability'],'dc':row['save_dc']}
                if row['category'] in AFFLICTION_CATEGORIES:
                    data.update(information_profile=validate_affliction(row),save_success=validate_save_success(row['save_success']),source_readers=list(row['readers']),private_label=row['label'],label=name.replace('_',' ').title())
                engine._apply_condition(actor,'condition:typed.'+name,row['source'],
                    'map' if row['category'] in AFFLICTION_CATEGORIES else actor.entity_id,
                    expires_on='UNTIL_REMOVED',data=data)


@hook('journey_encounter_settled')
def import_effects(session, aid, engine, creature):
    from .repeat_saves import save_of
    eligible=[(iid,c,save_of(c)) for iid,c in creature.conditions.items()
              if c.condition_id in ('frightened','condition:typed.frightened') and save_of(c) is not None]
    if not effects(session,aid) and not eligible:return
    stored=session.state['actors'][aid].setdefault('source_states',{}).setdefault(KEY,{})
    active_ids={c.data.get('journey_effect_id') for c in creature.conditions.values()}
    for iid,row in list(stored.items()):
        if condition_names(row) and iid not in active_ids and iid not in creature.conditions:del stored[iid]
    for iid,c,save in eligible:
        key=c.data.get('journey_effect_id',iid)
        stored.setdefault(key,{'id':key,'label':str(c.data.get('label','Frightened')),'category':'frightened',
            'source':c.source_definition_id,'save_ability':str(save['ability']).upper(),'save_dc':int(save['dc']),
            'receipt':str(engine.state.match_id)+':'+str(c.applied_sequence)+':'+iid})


def minor_eligible(row):
    """Explicit latest GM classification; no severity guessed from effect names."""
    return row.get('minor_category',row['category']) in ('ordinary_nightmare','minor_sleep_disturbance','minor_mental_stress')

# Additional source-qualified afflictions use the same native world-owner
# declaration boundary. They grant no ability and never infer a cause from a name.
AFFLICTION_CATEGORIES=('ordinary_disease','supernatural_disease','poisoned','unknown_blinded','airborne_blinded','injury_blinded')
CATEGORIES=(*CATEGORIES,*AFFLICTION_CATEGORIES)
AFFLICTION_CONDITIONS={'ordinary_disease':'diseased','supernatural_disease':'diseased','poisoned':'poisoned',
                      'unknown_blinded':'blinded','airborne_blinded':'blinded','injury_blinded':'blinded'}


def validate_affliction(row):
    """Validate authored Source CL, ordinary status and actual condition cause."""
    ordinary=row['ordinary'];level=row['source_cl'];tags=row['cause_tags']
    require(type(ordinary) is int and ordinary in (0,1) and integer(level)
            and (ordinary==1 or level>=1), 'An affliction needs its actual ordinary flag and known Source CL.')
    require(row['authority_grade'] in ('ordinary','artifact','secret','immortal','absolute'), 'Choose the Source Rule’s actual authority grade.')
    require(isinstance(tags,list) and all(type(t) is str for t in tags) and len(tags)==len(set(tags)), 'Supply distinct typed cause tags.')
    if row['category']=='ordinary_disease':
        require(ordinary==1 and tags==['disease'], 'An ordinary disease needs its explicit ordinary disease classification.')
    elif row['category']=='supernatural_disease':
        require(ordinary==0 and tags==['disease'], 'A supernatural disease needs its actual supernatural disease classification.')
    elif row['category']=='poisoned':require(tags==['poison'], 'Poisoned requires an actual poison source.')
    elif row['category']=='unknown_blinded':require(tags==[], 'An unknown Blindness cause must remain unclassified.')
    elif row['category']=='airborne_blinded':
        require(bool(tags) and set(tags)<={'dust','smoke','ash','pollen','airborne_irritant'}, 'Airborne Blindness requires its actual irritant cause.')
    else:require(tags==['injury'], 'Injury-based Blindness must retain its injury cause.')
    symptoms=row.get('imposed_conditions',[])
    require(isinstance(symptoms,list) and len(symptoms)==len(set(symptoms))
            and set(symptoms)<={'poisoned','sickened'}, 'Only explicit ordinary disease symptoms are supported.')
    require(row['category'] in ('ordinary_disease','supernatural_disease') or not symptoms, 'Symptoms belong to the recorded disease episode.')
    permissions=validate_counterprocedures(row)
    return {'tags':list(tags),'source_cl':level,'mundane':ordinary,'authority':row['authority_grade'],**permissions}


def condition_names(row):
    if row['category']=='frightened':return ['frightened']
    if row['category'] not in AFFLICTION_CATEGORIES:return []
    return [AFFLICTION_CONDITIONS[row['category']],*row.get('imposed_conditions',[])]


def end_combat_effect(engine,subject,effect_id,source):
    """End exactly one native disease/affliction episode and its imposed states."""
    from .condition_ownership import remove_instance
    for c in list(subject.conditions.values()):
        if c.data.get('journey_effect_id')==effect_id:
            remove_instance(engine,subject,c.instance_id,source)


def validate_effect(row):
    required={'id','label','category','source','save_ability','save_dc'}
    extra={'source_cl','ordinary','cause_tags','authority_grade','save_success'} if row.get('category') in AFFLICTION_CATEGORIES else set()
    require(required|extra<=set(row)<=required|extra|({'imposed_conditions','counterprocedures','authority_basis'} if extra else set())
            and all(type(row[k]) is str and row[k].strip() for k in ('id','label','source'))
            and row['category'] in CATEGORIES and row['save_ability'] in ('','STR','DEX','CON','INT','WIS','CHA')
            and integer(row['save_dc']), 'Supply an actual named effect, explicit category and original saving throw.')
    require(row['category'] != 'frightened' or row['save_ability'] and integer(row['save_dc'],1), 'Frightened repeat requires its original saving throw.')
    if extra:
        require(bool(row['save_ability'])==(row['save_dc']>0), 'An originating save needs both its actual ability and DC.')
        validate_affliction(row)
        validate_save_success(row['save_success'])


@hook('fact_admission_validate')
def validate_input(session,source,subject,kind,scope,value):
    if source!=SOURCE:return None
    if kind=='effect':
        validate_effect(value)
        # The same identity must not reapply a cured or replaced episode.
        for prior in session.state.get('fact_consent_admission',()):
            if prior['source']==SOURCE and prior['subject']==subject and prior['kind']=='effect':
                require(prior['value']['id']!=value['id'],'An affliction episode identity cannot be replayed as a new effect.')
        return True
    return None


@hook('combat_world_fact_committed')
def combat_input(engine,receipt):
    if receipt['source']!=SOURCE or receipt['kind']!='effect':return
    row=receipt['value'];validate_effect(row)
    subject=engine.state.actors[receipt['subject']]
    for name in condition_names(row):
        data={'label':row['label'],'journey_effect_id':row['id']}
        if row['save_ability']:data['origin_save']={'ability':row['save_ability'],'dc':row['save_dc']}
        if row['category'] in AFFLICTION_CATEGORIES:
            data.update(information_profile=validate_affliction(row),save_success=validate_save_success(row['save_success']),source_readers=[subject.entity_id,*receipt['readers']],private_label=row['label'],label=name.replace('_',' ').title())
        engine._apply_condition(subject,'condition:typed.'+name,row['source'],'map',expires_on='UNTIL_REMOVED',data=data)


def validate_save_success(value):
    require(isinstance(value,dict) and value.get('kind') in ('end_condition','end_episode','none','progress'),
            'Record the originating save’s actual success procedure.')
    if value['kind']=='progress':
        require(set(value)=={'kind','required','progress'} and integer(value['required'],1)
                and integer(value['progress']) and value['progress']<value['required'],
                'A progressive recovery needs its actual required and already completed successful saves.')
    else:require(set(value)=={'kind'},'Use the exact originating success procedure.')
    return deepcopy(value)


def resolve_combat_save_success(engine,subject,condition,source):
    """Apply the recorded original save result, never invent an automatic cure."""
    from .condition_ownership import remove_instance
    rule=condition.data.get('save_success')
    if rule is None:
        # A native repeat_save is the engine's ordinary end-on-success contract.
        # An originating ability/DC by itself is not an ending procedure.
        if condition.data.get('repeat_save'):
            remove_instance(engine,subject,condition.instance_id,source)
        return
    rule=validate_save_success(rule);kind=rule['kind']
    episode=condition.data.get('journey_effect_id')
    if kind=='progress':
        rule['progress']+=1
        if rule['progress']<rule['required']:
            for held in list(subject.conditions.values()):
                if held is condition or episode and held.data.get('journey_effect_id')==episode:
                    engine._update_condition_data(subject,held,{**held.data,'save_success':deepcopy(rule)},source)
            return
        kind='end_episode'
    if kind=='end_episode' and episode:end_combat_effect(engine,subject,episode,source)
    elif kind=='end_condition':remove_instance(engine,subject,condition.instance_id,source)


@hook('fact_admission_validate')
def validate_native_profile(session,source,subject,kind,scope,value):
    if source!=SOURCE or kind!='condition_profile':return None
    require(hasattr(session,'engine'),'Condition profiles require a present native encounter instance.')
    native_profile(session.engine,subject,value)
    return True


def native_profile(engine,subject,value):
    """Fill unknown origin facts, while retaining all committed known facts."""
    required={'instance_id','source','source_actor_id','source_cl','ordinary','cause_tags','authority_grade'}
    require(required<=set(value)<=required|{'counterprocedures','authority_basis'},
            'Bind the exact native condition and its actual source profile.')
    require(all(type(value[k]) is str and value[k] for k in ('instance_id','source','source_actor_id')),'Bind actual native source identities.')
    condition=engine.state.actors[subject].conditions.get(value['instance_id'])
    require(condition is not None and condition.source_definition_id==value['source']
            and condition.source_actor_id==value['source_actor_id'],'The condition or its source changed; refresh the actual instance.')
    name=condition.condition_id.removeprefix('condition:typed.')
    require(name in ('poisoned','blinded','diseased','disease'),'This source accepts only actual rain-cleansable condition profiles.')
    tags=value['cause_tags']
    require(isinstance(tags,list) and bool(tags) and all(type(t) is str for t in tags) and len(tags)==len(set(tags))
            and set(tags)<={'poison','disease','dust','smoke','ash','pollen','airborne_irritant','injury'},'Use explicit actual cause tags.')
    require(name!='blinded' or 'injury' in tags or set(tags)<={'dust','smoke','ash','pollen','airborne_irritant'},'Blindness needs its actual injury or airborne cause.')
    require(name!='poisoned' or bool(set(tags)&{'poison','disease'}),'Poisoned needs its actual poison or disease source.')
    require(name not in ('diseased','disease') or tags==['disease'],'Disease needs its actual disease source.')
    require(integer(value['source_cl']) and type(value['ordinary']) is int and value['ordinary'] in (0,1)
            and (value['ordinary']==1 or value['source_cl']>=1)
            and value['authority_grade'] in ('ordinary','artifact','secret','immortal','absolute'),'Supply known source authority and ordinary status.')
    known=condition.data.get('information_profile') or {}
    for key,proposed in (('source_cl',value['source_cl']),('mundane',value['ordinary']),('tags',tags),('authority',value['authority_grade'])):
        if key in known and known[key] not in ('unknown',[],None):
            require(known[key]==proposed,'A declaration cannot contradict committed native source facts.')
    permissions=validate_counterprocedures(value)
    for key,proposed in permissions.items():
        require(key not in known or known[key]==proposed,'A declaration cannot contradict committed source counterprocedures.')
    return condition,{**known,'source_cl':value['source_cl'],'mundane':value['ordinary'],'tags':list(tags),'authority':value['authority_grade'],**permissions}


@hook('combat_world_fact_committed')
def apply_native_profile(engine,receipt):
    if receipt['source']!=SOURCE or receipt['kind']!='condition_profile':return
    condition,profile=native_profile(engine,receipt['subject'],receipt['value'])
    subject=engine.state.actors[receipt['subject']]
    engine._update_condition_data(subject,condition,{**condition.data,'information_profile':profile,
        'source_profile_receipt':receipt['receipt_id'],'source_readers':[subject.entity_id,*receipt['readers']]},SOURCE)



def validate_counterprocedures(row):
    if 'counterprocedures' not in row:
        require('authority_basis' not in row,'A printed authority basis needs its exact counterprocedures.')
        return {}
    permissions=row['counterprocedures']
    require(isinstance(permissions,list) and all(type(s) is str and 0<len(s)<=240 for s in permissions)
            and len(permissions)==len(set(permissions)), 'Name the exact source-authorized counterprocedures.')
    require(type(row.get('authority_basis')) is str and bool(row['authority_basis'].strip()),
            'Record the actual Source Rule authorizing or prohibiting these counterprocedures.')
    return {'counterprocedures':list(permissions),'authority_basis':row['authority_basis']}
