"""Trusted table-owner world input on the shared fact/consent contract.

This is a source input, never an actor consent, desired outcome, cost waiver or
GM creature. The versioned binding uses the ordinary native PREPARE/COMMIT and
cold mechanical replay protocol. The protected local HTTP route is the caller;
ordinary combat candidate requests cannot select this binding or supply a role.
"""
import re
from .canonical import canonical_sha256
from .gate2_runtime_models import ActionIntent
from .fact_consent_admission import validate_world_combat,declare_world_combat
from .journey import require

KIND='SOURCE_WORLD_FACT_V1'


def validate(engine,intent,binding):
    if binding.get('kind')!=KIND:return None
    require(set(binding)=={'kind','payload'} and isinstance(binding['payload'],dict),'Use the typed shared world input.')
    require(intent.actor_id==next(iter(engine.state.actors)) and intent.state_version==engine.state.state_version
        and intent.decision_id=='source-world-input:v1' and intent.candidate_id==canonical_sha256(binding)
        and not intent.target_ids and not intent.reaction_decisions,'The native world-input binding does not match.')
    require(engine.state.terminal_result is None,'A completed encounter cannot accept new scene facts.')
    validate_world_combat(engine,binding['payload'])
    return True


def execute(engine,intent,binding):
    if binding.get('kind')!=KIND:return None
    validate(engine,intent,binding)
    with engine._transaction('system:source.world_input',intent.intent_id,intent.actor_id):
        receipt=declare_world_combat(engine,binding['payload'])
        engine._append_event('WORLD_FACT_DECLARED','system:source.world_input',
            payload={'authority':'table_owner','receipt_id':receipt})
    return True


def commit(table,match_id,state_version,request_id,payload):
    require(type(request_id) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',request_id) is not None,'Use a bounded world-input retry identifier.')
    require(type(state_version) is int and state_version>=0,'Use the current native state version.')
    require(not table._pending_action_path(match_id).is_file(),'Finish the open combat question before changing its source facts.')
    session=table.combat._load_session(match_id)
    engine=session.engine
    binding={'kind':KIND,'payload':payload}
    intent_id='world-fact:'+request_id
    previous=next((r for r in session.mechanical._records if r['record_type']=='PREPARE' and r['intent']['intent_id']==intent_id),None)
    if previous:
        require(previous['candidate_binding']==binding,'That retry identifier already names different source input.')
        if any(r['record_type']=='COMMIT' and r['transaction_id']==previous['transaction_id'] for r in session.mechanical._records):
            return {'state_version':engine.state.state_version,'request_id':request_id,'status':'COMMITTED'}
    intent=ActionIntent(intent_id=intent_id,decision_id='source-world-input:v1',candidate_id=canonical_sha256(binding),
        state_version=state_version,actor_id=next(iter(engine.state.actors)))
    validate(engine,intent,binding)
    session.submit_intent(intent,primary_decision_record=None,reaction_provider=None,settings_binding=binding)
    return {'state_version':engine.state.state_version,'request_id':request_id,'status':'COMMITTED'}
