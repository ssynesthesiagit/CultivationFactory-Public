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
    if source == SOURCE and kind == 'effect':
        return {'value_type':'document', 'authority':'table_owner', 'maximum_seconds':31536000,
                'description':'Actual externally sourced affliction with explicit severity and original saving throw.'}


@hook('journey_world_fact_committed')
def produce(session, receipt):
    if receipt['source'] != SOURCE or receipt['kind'] != 'effect': return
    row = receipt['value']
    require(set(row) == {'id','label','category','source','save_ability','save_dc'}
            and all(type(row[k]) is str and row[k].strip() for k in ('id','label','source'))
            and row['category'] in CATEGORIES and row['save_ability'] in ('','STR','DEX','CON','INT','WIS','CHA')
            and integer(row['save_dc']), 'Supply an actual named effect, explicit category and original saving throw.')
    require(row['category'] != 'frightened' or row['save_ability'], 'Frightened repeat requires its original saving throw.')
    effects = session.state['actors'][receipt['subject']].setdefault('source_states',{}).setdefault(KEY,{})
    require(row['id'] not in effects, 'An active effect identity cannot be overwritten.')
    effects[row['id']] = {**deepcopy(row), 'receipt':receipt['receipt_id']}
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
            if row['category'] == 'frightened' and not any(c.data.get('journey_effect_id') == iid for c in actor.conditions.values()):
                engine._apply_condition(actor,'condition:typed.frightened',row['source'],actor.entity_id,expires_on='UNTIL_REMOVED',
                    data={'label':row['label'],'journey_effect_id':iid,'origin_save':{'ability':row['save_ability'],'dc':row['save_dc']}})


@hook('journey_encounter_settled')
def import_effects(session, aid, engine, creature):
    if not effects(session,aid) and not any(c.condition_id in ('frightened','condition:typed.frightened') and ('origin_save' in c.data or 'repeat_save' in c.data) for c in creature.conditions.values()): return
    stored = session.state['actors'][aid].setdefault('source_states',{}).setdefault(KEY,{})
    active_ids = {c.data.get('journey_effect_id') for c in creature.conditions.values()}
    for iid,row in list(stored.items()):
        if row['category'] == 'frightened' and iid not in active_ids:
            del stored[iid]
    for iid,c in creature.conditions.items():
        if c.condition_id in ('frightened','condition:typed.frightened') and ('origin_save' in c.data or 'repeat_save' in c.data):
            key = c.data.get('journey_effect_id',iid)
            stored.setdefault(key,{'id':key,'label':str(c.data.get('label','Frightened')),'category':'frightened',
                                  'source':c.source_definition_id if hasattr(c,'source_definition_id') else str(c.source_id),
                                  'save_ability':str((c.data.get('origin_save') or c.data['repeat_save'])['ability']).upper(),'save_dc':(c.data.get('origin_save') or c.data['repeat_save'])['dc'],'receipt':str(engine.state.match_id)+':'+str(c.applied_sequence)+':'+iid})
