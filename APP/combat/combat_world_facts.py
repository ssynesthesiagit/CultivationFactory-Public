"""Journaled native world-owner input, using the existing fact admission schemas.

This is a typed external-fact transaction, not a creature action, activation or
damage receipt. Party consent schemas reject world authority. Unknown schemas
reject atomically. Native PREPARE/COMMIT, controller audit, version checks,
recovery and reducer replay are shared with the existing no-reaction policy.
The server supplies table_owner; no request can choose its authority.
"""
import copy
import json
from fractions import Fraction
from .journey import require
from .canonical import canonical_sha256
from .fact_consent_admission import declare_world,canonical,digest,KEY

KIND='WORLD_FACT_INPUT_V1'
HISTORY='condition:world.fact_history'


def clock(engine):
    saved=next((b['scene_field_clock'] for b in getattr(engine,'typed_bundle_documents',()) if b.get('scene_field_clock')),None)
    base=Fraction(saved['num'],saved['den']) if saved else Fraction(0)
    slots=max(1,len(engine.state.initiative_order))
    return base+Fraction((max(0,engine.state.round_number-1)*slots+engine.state.current_slot_index)*6,slots)


def records(engine):
    found={}
    for bundle in getattr(engine,'typed_bundle_documents',()):
        for row in bundle.get('scene_field_facts',()):
            plain={k:v for k,v in row.items() if k not in ('remaining_num','remaining_den')}
            require(plain['receipt_id']==digest({k:v for k,v in plain.items() if k!='receipt_id'}),'A sealed world record failed its commitment.')
            found[plain['receipt_id']]=plain
    for actor in engine.state.actors.values():
        for condition in actor.conditions.values():
            if condition.condition_id!=HISTORY:
                continue
            for row in json.loads(condition.data['records']):
                require(row['receipt_id']==digest({k:v for k,v in row.items() if k!='receipt_id'}),'A world input failed its replay commitment.')
                found[row['receipt_id']]=row
    return sorted(found.values(),key=lambda r:r['sequence'])


class Admission:
    """Read-only native encounter adapter for the shared admission validator."""
    def __init__(self,engine):
        bundles={b['actor_id']:b for b in getattr(engine,'typed_bundle_documents',())}
        self.engine=engine
        self.fact_sequence_floor=max((int(b.get('scene_field_sequence_floor',0)) for b in bundles.values()),default=0)
        self.grid=engine.grid
        self.state={'actors':{aid:{'bundle':bundles.get(aid,{}),'position':a.position.model_dump(mode='json')}
                              for aid,a in engine.state.actors.items()},KEY:copy.deepcopy(records(engine))}

    def clock(self):
        return clock(self.engine)

    def emit(self,*args,**kwargs):
        # Validation computes the same proposed record without mutating the
        # engine. Only execute() below publishes the actual native transaction.
        pass


def reconcile_journey_clock(session,engine):
    """Actual elapsed rounds for a journey that sealed the scene-clock seam.

    Old bundles have no marker and remain unchanged. Every source continuation
    shares this clock, so facts and ritual effects cannot each restart time.
    """
    if not any('scene_field_clock' in b for b in getattr(engine,'typed_bundle_documents',())):
        return
    if session.state.get('source_clock_encounter_id')==engine.state.match_id:
        return
    remaining=clock(engine)-session.clock()
    require(remaining>=0,'The encounter cannot rewind its journey clock.')
    session.tick(remaining)
    session.state['source_clock_encounter_id']=engine.state.match_id
    session.emit('ENCOUNTER_TIME_ELAPSED',next(iter(session.state['actors'])),
        elapsed_num=remaining.numerator,elapsed_den=remaining.denominator,match_id=engine.state.match_id)


def validate(engine,intent,binding):
    from .gate2_runtime_models import ActionIntent
    require(set(binding)=={'kind','authority','payload'} and binding['kind']==KIND and binding['authority']=='table_owner',
            'World input requires native table-owner authority.')
    payload=binding['payload']
    require(engine.state.terminal_result is None,'This encounter has ended; record new world facts in its resumed journey.')
    require(isinstance(payload,dict) and payload.get('subject') in engine.state.actors,'Choose a present world-fact subject.')
    require(intent.state_version==engine.state.state_version,'The fight changed; refresh before recording world facts.')
    expected=ActionIntent(intent_id=intent.intent_id,decision_id='world_input:v1',candidate_id=canonical_sha256(binding),
        state_version=engine.state.state_version,actor_id=payload['subject'],target_ids=(payload['subject'],))
    require(expected.model_dump(mode='json')==intent.model_dump(mode='json'),'World input cannot carry a creature action or combat choices.')
    adapter=Admission(engine)
    declare_world(adapter,payload)
    return adapter.state[KEY][-1]


def execute(engine,intent,binding):
    record=validate(engine,intent,binding)
    subject=engine.state.actors[record['subject']]
    with engine._transaction('system:combat.world_input',intent.intent_id,subject.entity_id):
        rows=[r for r in records(engine) if r['source']==record['source'] and r['subject']==record['subject']]
        rows.append(record)
        held=next((c for c in subject.conditions.values() if c.condition_id==HISTORY and c.source_definition_id==record['source']),None)
        data={'records':canonical(rows),'label':'Private world-fact history'}
        if held is None:
            engine._apply_condition(subject,HISTORY,record['source'],subject.entity_id,expires_on='UNTIL_REMOVED',data=data)
        else:
            engine._update_condition_data(subject,held,data,record['source'])
        engine._append_event('WORLD_FACT_DECLARED',record['source'],target_ids=(subject.entity_id,),
            payload={'kind':record['kind'],'scope':record['scope'],'receipt_id':record['receipt_id']})


def apply(table,match_id,state_version,payload,request_id):
    from .gate2_runtime_models import ActionIntent
    require(type(request_id) is str and 0<len(request_id)<=120,'Supply a stable world-input request identifier.')
    require(not table._pending_action_path(match_id).is_file(),'Answer the open combat question before changing world facts.')
    session=table.combat._load_session(match_id)
    binding={'kind':KIND,'authority':'table_owner','payload':copy.deepcopy(payload)}
    intent_id='world-input:'+request_id
    previous=next((r for r in session.mechanical._records if r['record_type']=='PREPARE' and r['intent']['intent_id']==intent_id),None)
    if previous:
        require(previous['candidate_binding']==binding,'That request identifier belongs to a different world input.')
        committed=next((r for r in session.mechanical._records if r['record_type']=='COMMIT' and r['transaction_id']==previous['transaction_id']),None)
        if committed:
            receipt=next(e['payload']['receipt_id'] for e in committed['events'] if e['event_type']=='WORLD_FACT_DECLARED')
            return {'status':'COMMITTED','state_version':session.engine.state.state_version,'receipt_id':receipt}
    intent=ActionIntent(intent_id=intent_id,decision_id='world_input:v1',candidate_id=canonical_sha256(binding),
        state_version=state_version,actor_id=payload.get('subject',''),target_ids=(payload.get('subject',''),))
    proposed=validate(session.engine,intent,binding)
    session.submit_intent(intent,primary_decision_record=None,reaction_provider=None,settings_binding=binding)
    return {'status':'COMMITTED','state_version':session.engine.state.state_version,'receipt_id':proposed['receipt_id']}
