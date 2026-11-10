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
    if source == SOURCE and kind in ('effect','classification'):
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
    require({'id','label','category','source','save_ability','save_dc'} <= set(row)
            <= {'id','label','category','source','save_ability','save_dc','source_actor_id'}
            and type(row.get('source_actor_id','')) is str
            and all(type(row[k]) is str and row[k].strip() for k in ('id','label','source'))
            and row['category'] in CATEGORIES and row['save_ability'] in ('','STR','DEX','CON','INT','WIS','CHA')
            and integer(row['save_dc']), 'Supply an actual named effect, explicit category and original saving throw.')
    require(row['category'] != 'frightened' or row['save_ability'] and integer(row['save_dc'],1), 'Frightened repeat requires its original saving throw.')
    stored = session.state['actors'][receipt['subject']].setdefault('source_states',{}).setdefault(KEY,{})
    require(row['id'] not in stored, 'An active effect identity cannot be overwritten.')
    stored[row['id']] = {**deepcopy(row), 'receipt':receipt['receipt_id']}
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
        # journey_setup restores these native instances after this subscriber.
        # Do not synthesize a second copy while that restoration is still pending.
        snapshot = bundle.get('journey_setup',{}).get('encounter_snapshot',{})
        restored = {iid:json.loads(encoded) for iid,encoded in snapshot.get('conditions',{}).items()}
        for iid,row in bundle.get('journey_external_effects',{}).items():
            if iid in restored or any(c.get('data',{}).get('journey_effect_id') == iid for c in restored.values()):
                continue
            if row['category'] == 'frightened' and not any(c.data.get('journey_effect_id') == iid for c in actor.conditions.values()):
                engine._apply_condition(actor,'condition:typed.frightened',row['source'],row.get('source_actor_id',''),expires_on='UNTIL_REMOVED',
                    data={'label':row['label'],'journey_effect_id':iid,'origin_save':{'ability':row['save_ability'],'dc':row['save_dc']}})


@hook('journey_encounter_settled')
def import_effects(session, aid, engine, creature):
    from .repeat_saves import save_of
    from ..gate2_runtime_models import ConditionInstance
    # Settlement follows snapshot admission, including explicit GM resolution
    # of timed effects. The immutable terminal creature still has those effects
    # and must not be used to recreate them in the next encounter.
    conditions = {iid:ConditionInstance.model_validate(json.loads(encoded))
                  for iid,encoded in session.state['actors'][aid]['encounter_snapshot']['conditions'].items()}
    eligible=[(iid,c,save_of(c)) for iid,c in conditions.items()
              if c.condition_id in ('frightened','condition:typed.frightened') and save_of(c) is not None]
    if not effects(session,aid) and not eligible:return
    stored=session.state['actors'][aid].setdefault('source_states',{}).setdefault(KEY,{})
    active_ids={c.data.get('journey_effect_id') for c in conditions.values()}
    for iid,row in list(stored.items()):
        if row['category']=='frightened' and iid not in active_ids and iid not in conditions:del stored[iid]
    for iid,c,save in eligible:
        key=c.data.get('journey_effect_id',iid)
        stored.setdefault(key,{'id':key,'label':str(c.data.get('label','Frightened')),'category':'frightened',
            'source':c.source_definition_id,'source_actor_id':c.source_actor_id or '',
            'save_ability':str(save['ability']).upper(),'save_dc':int(save['dc']),
            'receipt':str(engine.state.match_id)+':'+str(c.applied_sequence)+':'+iid})
        stored[key]['source_actor_id'] = c.source_actor_id or ''


def minor_eligible(row):
    """Explicit latest GM classification; no severity guessed from effect names."""
    return row.get('minor_category',row['category']) in ('ordinary_nightmare','minor_sleep_disturbance','minor_mental_stress')
