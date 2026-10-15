"""Native table collection of admitted clinical protocols.

The same immutable protocol used by journey commands grants source-specific
begin/continue/stop actions to its explicit readers. Actual Actions, resource
payments, rounds, consent and skill checks complete the procedure. No protocol
or missing source grants nothing. These are Medicine/Alchemy/etc. procedures,
not replacement Life/Blood/Poison ability implementations or GM done buttons.
"""
from __future__ import annotations
import json
from . import hook,effect
from .. import clinical_sources as cs
from ..fact_consent_admission import digest

PROTOCOL='condition:typed.clinical_protocol'
PROGRESS='condition:typed.clinical_procedure'


def protocol_record(condition,reader):
    record=json.loads(condition.data['record'])
    if (condition.target_id!=reader or condition.source_actor_id!=reader
            or record.get('source')!='clinical_source' or record.get('authority')!='table_owner' or record.get('kind')!='clinical_protocol'
            or reader not in record.get('readers',[]) or
            record.get('receipt_id')!=digest({k:v for k,v in record.items() if k!='receipt_id'})):
        raise ValueError('Clinical protocol failed its source authority commitment')
    return record


def sources(patient,group):
    return [(key,c) for key,c in patient.conditions.items()
            if cs.source_matches(c.data.get('clinical') or c.data.get('clinical_retained_source') or {},group)]


def skill_value(engine,actor,skill):
    for bundle in getattr(engine,'typed_bundle_documents',()):
        if bundle.get('actor_id')==actor.entity_id and skill in (bundle.get('skills') or {}):
            return int(bundle['skills'][skill])
    return int(actor.skills[skill]) if skill in actor.skills else None


def access(engine,actor,record):
    value=record['value'];method=value['method']
    if skill_value(engine,actor,value['skill']) is None:return False
    if method in ('Life','Poison'):
        sphere='tianxia.sphere.'+method.lower()
        if not any(a.owner_id==actor.entity_id and (a.parameters.get('typed') or {}).get('sphere')==sphere
                   for a in engine.action_catalog.values()):return False
    return True


@hook('fact_admitted')
def collect_protocol(session,record):
    if record['source']!='clinical_source' or record['kind']!='clinical_protocol':return
    from ..gate2_runtime_models import ConditionInstance
    for reader in record['readers']:
        actor=session.state['actors'][reader]
        if 'encounter_snapshot' not in actor:
            hp=actor['bundle']['actor_template']['maximum_hp']
            actor['encounter_snapshot']={'current_hp':hp,'maximum_hp':hp,'temporary_hp':0,'active':1,
                'life_state':'','conditions':{}}
        key='clinical-protocol:'+record['receipt_id']+':'+reader
        condition=ConditionInstance(instance_id=key,condition_id=PROTOCOL,source_definition_id='clinical:protocol',
            source_actor_id=reader,target_id=reader,applied_sequence=len(session.state['events'])+1,
            expires_on='UNTIL_REMOVED',data={'record':json.dumps(record,sort_keys=True),
                'external_expiry':record['expires_at'],'label':'An admitted private clinical protocol'})
        actor['encounter_snapshot']['conditions'][key]=condition.model_dump_json(exclude_none=True)


def action_id(record,stage):
    return 'action:clinical.'+record['receipt_id']+'.'+stage


@hook('match_start')
def protocol_actions(engine):
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    for actor in engine.state.actors.values():
        for c in actor.conditions.values():
            if c.condition_id!=PROTOCOL:continue
            record=protocol_record(c,actor.entity_id);value=record['value']
            for stage in ('begin','continue','stop'):
                source=action_id(record,stage)
                engine.action_catalog[source]=ActionDefinition(source_definition_id=source,owner_id=actor.entity_id,
                    display_name=f"{value['method']}: {'start' if stage=='begin' else stage} {value['operation']}",
                    economy=EconomyKind.NONE if stage=='stop' else EconomyKind.ACTION,
                    resolution_kind='TYPED',target_kind='SELF' if stage=='stop' else 'ANY_CREATURE',
                    range_ft=5,costs=tuple(sorted(value['costs'].items())) if stage=='begin' else (),
                    parameters={'clinical_protocol':record['receipt_id'],'clinical_stage':stage,
                        'typed':{'source':source,'manual_inline_choice':True,'numbers':{},'riders':[],
                            'duration':{'kind':'instant'},'effects':[{'type':'clinical_procedure','receipt':record['receipt_id'],'stage':stage}]},
                        'description':f"{value['method']}: {value['operation']} one admitted source on the named patient. "
                            f"{value['seconds']} seconds of continuous work, one Action each round; actual source DC. "
                            'Pay the recorded resources when starting. Stopping or a failed check does not refund time or resources.'})


@hook('additional_actions')
def offered_protocols(engine,actor):
    result=[]
    for c in actor.conditions.values():
        if c.condition_id==PROTOCOL:
            record=protocol_record(c,actor.entity_id)
            result.extend(action_id(record,s) for s in ('begin','continue','stop'))
    return tuple(result) or None


def live_record(actor,receipt):
    for c in actor.conditions.values():
        if c.condition_id==PROTOCOL:
            record=protocol_record(c,actor.entity_id)
            if record['receipt_id']==receipt:return record
    return None


def pending(actor,receipt):
    return next((c for c in actor.conditions.values() if c.condition_id==PROGRESS and c.data.get('receipt')==receipt),None)


@hook('candidate_allowed')
def protocol_allowed(engine,actor,candidate,action):
    if action is None:return None
    receipt=action.parameters.get('clinical_protocol')
    if not receipt:return None
    record=live_record(actor,receipt)
    if record is None or not access(engine,actor,record):return False
    progress=pending(actor,receipt);stage=action.parameters['clinical_stage']
    if stage=='stop':return progress is not None
    if tuple(candidate.target_ids)!=(record['subject'],):return False
    patient=engine.state.actors.get(record['subject'])
    if patient is None or not engine.grid.line_of_physical_transmission(actor.position,patient.position):return False
    current=sources(patient,progress.data['source_instance'] if progress else record['value']['source_instance'])
    if not current:return False
    eligible=[facts for _,c in current if (facts:=cs.metadata(engine,patient,c,retained=True)) and not facts.get('excluded') and type(facts.get('dc')) is int and facts['dc']>0
              and (record['value']['operation']=='identify' or not facts.get('private') or actor.entity_id in facts.get('readers',[]))]
    if not eligible:return False
    if stage=='begin':return not any(c.condition_id==PROGRESS for c in actor.conditions.values())
    return progress is not None and engine.state.round_number>progress.data['last_round']


@effect('clinical_procedure',harmful=False)
def procedure(ctx,row):
    from .willing_targets import asks_consent
    record=live_record(ctx.actor,row['receipt'])
    if record is None:raise ValueError('The admitted protocol is no longer available')
    value=record['value'];progress=pending(ctx.actor,row['receipt'])
    if row['stage']=='stop':
        if progress:ctx.engine._remove_condition_instance(ctx.actor,progress.instance_id,ctx.source,expected=progress)
        return
    patient=ctx.engine.state.actors.get(record['subject'])
    current=sources(patient,progress.data['source_instance'] if progress else value['source_instance']) if patient is not None else []
    if not current:raise ValueError('The clinical source has ended')
    groups={}
    for key,c in current:
        facts=cs.metadata(ctx.engine,patient,c,retained=True)
        if facts and not facts.get('excluded') and type(facts.get('dc')) is int and (value['operation']=='identify' or not facts.get('private') or ctx.actor.entity_id in facts.get('readers',[])):
            groups.setdefault(facts['source_instance'],(c,facts))
    if not groups:raise ValueError('No eligible source remains for this protocol')
    from .needle import ask,checkpoint_id,CHOICE
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'clinical_protocol_source',row['receipt'],patient.entity_id),ctx.actor,
        CHOICE+'clinical_protocol_source',list(groups),labels={k:f['label'] if not f.get('private') or ctx.actor.entity_id in f.get('readers',[]) else 'An unidentified ailment' for k,(c,f) in groups.items()},
        preferred=list(groups)[:1],prompt=f"{value['method']}: choose the actual source on {patient.display_name} for {value['operation']}. This does not identify or cure it before the check.")
    group=(selected or list(groups)[:1])[0]
    current=sources(patient,group)
    consent=patient is ctx.actor or asks_consent(ctx.engine,ctx.intent,patient,ctx.action.display_name,
        f"{patient.display_name}: accept {value['method']} {value['operation']} from {ctx.actor.display_name}? "
        f"It requires contact and {value['seconds']} seconds of work; the practitioner pays its recorded costs. You spend no action or resource.",
        prefer_accept=patient.team_id==ctx.actor.team_id,asker=ctx.actor)
    if not consent:
        if progress:ctx.engine._remove_condition_instance(ctx.actor,progress.instance_id,ctx.source,expected=progress)
        return
    if row['stage']=='begin':
        left=(value['seconds']+5)//6-1
    else:
        if progress is None:raise ValueError('Start the clinical procedure first')
        left=progress.data['remaining_steps']-1
        ctx.engine._remove_condition_instance(ctx.actor,progress.instance_id,ctx.source,expected=progress)
    if left>0:
        ctx.engine._apply_condition(ctx.actor,PROGRESS,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'receipt':row['receipt'],'source_instance':group,'remaining_steps':left,'last_round':ctx.engine.state.round_number,
                'label':f"{value['method']} {value['operation']}: {left} Actions of work remain; keep contact"})
        return
    facts=cs.metadata(ctx.engine,patient,current[0][1],retained=True)
    with ctx.engine.d20_scope({'kind':'check','actor_id':ctx.actor.entity_id,'ability':value['ability'],
                              'skill':value['skill'],'source_id':ctx.source}):
        roll=ctx.engine.roll_check(modifier=skill_value(ctx.engine,ctx.actor,value['skill']),actor_id=ctx.actor.entity_id,
            reason='CHECK:'+ctx.source+':'+value['skill'],ability=value['ability'],skill=value['skill'])
    ctx.engine._record_roll(roll)
    success=roll.total>=facts['dc']
    ctx.engine._append_event('CHECK_ROLLED',ctx.source,actor_id=ctx.actor.entity_id,target_ids=(patient.entity_id,),
        payload={'check':value['skill'],'success':success,'actor':roll.model_dump(mode='json')})
    if not success:return
    if value['operation']=='treat':cs.end(ctx.engine,patient,facts,ctx.source)
    else:
        for _,c in current:
            saved=cs.metadata(ctx.engine,patient,c,retained=True)
            known={**saved,'readers':sorted(set([*saved.get('readers',[]),ctx.actor.entity_id]))}
            key='clinical_retained_source' if c.data.get('clinical_retained_source') else 'clinical'
            data={**c.data,key:known}
            if key=='clinical_retained_source' and isinstance(c.data.get('model'),dict):
                from copy import deepcopy
                model=deepcopy(c.data['model'])
                model['data']={**(model.get('data') or {}),'clinical':known}
                data['model']=model
            ctx.engine._update_condition_data(patient,c,data,ctx.source)


@hook('turn_end')
def interrupt_unworked_procedure(engine,actor):
    for c in list(actor.conditions.values()):
        if c.condition_id==PROGRESS and c.data['last_round']<engine.state.round_number:
            engine._remove_condition_instance(actor,c.instance_id,c.source_definition_id,expected=c)
            engine._append_event('PASSIVE_TRIGGERED',c.source_definition_id,actor_id=actor.entity_id,
                payload={'log':'Clinical procedure interrupted: a round passed without an Action of work. No resource refund.'})


@hook('presentation_hidden_conditions')
def hidden_protocols(engine,target):
    return tuple(c.instance_id for c in target.conditions.values() if c.condition_id==PROTOCOL)


@hook('choice_reactors')
def protocol_choice_reactors(engine):
    if any(c.condition_id==PROTOCOL for actor in engine.state.actors.values() for c in actor.conditions.values()):
        return tuple(engine.state.actors)
    return None



@hook('state_event')
def contact_interruption(engine,event):
    if event.event_type not in ('MOVEMENT_COMMITTED','CONDITION_REMOVED','DAMAGE_COMMITTED'):return
    for actor in engine.state.actors.values():
        for c in list(actor.conditions.values()):
            if c.condition_id!=PROGRESS:continue
            record=live_record(actor,c.data['receipt'])
            patient=engine.state.actors.get(record['subject']) if record else None
            if (patient is None or not actor.active or actor.current_hp<=0 or not sources(patient,c.data['source_instance']) or engine.grid.distance_ft(actor.position,patient.position)>5
                    or not engine.grid.line_of_physical_transmission(actor.position,patient.position)):
                engine._remove_condition_instance(actor,c.instance_id,c.source_definition_id,expected=c)
                engine._append_event('PASSIVE_TRIGGERED',c.source_definition_id,actor_id=actor.entity_id,
                    payload={'log':'Clinical procedure interrupted: contact was lost. No resource refund.'})
