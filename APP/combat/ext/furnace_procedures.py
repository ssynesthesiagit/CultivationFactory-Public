"""Source-owned second-furnace organ procedures and persistent complications.

Native world input supplies the actual procedure, operator, timing and outcome;
controller-owned consent binds the exact receipt. Native state supplies operator
availability, distance, Source CL, existing organ and represented Qi capacity.
No ordinary retraining, rest or reacquisition reconstructs this alteration.
"""
import copy
import json
from . import hook
from . import furnace_runtime as f
from ..fact_consent_admission import read
from ..journey import require,integer
from ..gate2_runtime_models import Position


@hook('fact_admission_schema')
def schema(session,source,subject,kind):
    if source!=f.PARENT or subject not in session.state['actors']:return
    if kind=='organ_procedure':return {'value_type':'document','maximum_seconds':2**53-1,'authority':'table_owner',
        'description':'Actual surgical or conceptual procedure: Source Rule, operator, range, duration, outcome, consent requirement, and any printed complications.'}
    if kind in ('organ_consent','organ_operator_consent'):return {'value_type':'document','maximum_seconds':2**53-1,
        'description':'The patient’s controller accepts this exact organ procedure and operator; sharing permission does not imply consent.'}


def publish_complications(actor,state,*,already_applied=0):
    """Family publication uses the actual represented pool, once per loss delta."""
    total=int(state.get('maximum_qi_loss',0))
    if not total and not already_applied:return
    for pool in actor['bundle']['actor_template']['resources']:
        if pool['resource_id']!=f.QI:continue
        pool['maximum']=max(0,pool['maximum']-(total-already_applied))
        pool['initial']=min(pool['initial'],pool['maximum'])
        actor['resources'][f.QI]=min(actor['resources'].get(f.QI,0),pool['maximum'])
    actor['bundle']['second_furnace_native']['qi_loss_applied']=total


@hook('compile_bundle',priority=50)
def compile_complications(bundle,info):
    entry=(info['owner_sheet'].get('path_and_subpath') or {}).get('subpath_acquisition') or {}
    if not bundle.get('second_furnace_native') or not entry.get('native_maximum_qi_loss'):return bundle
    total=int(entry['native_maximum_qi_loss'])
    for pool in bundle['actor_template']['resources']:
        if pool['resource_id']==f.QI:
            pool['maximum']=max(0,pool['maximum']-total);pool['initial']=min(pool['initial'],pool['maximum'])
    bundle['second_furnace_native']['qi_loss_applied']=total
    return bundle


@hook('journey_command')
def operate(session,aid,kind,payload):
    if kind!='furnace_organ':return
    actor=session.state['actors'][aid];state=actor.get('source_states',{}).get(f.PARENT)
    require(state is not None and set(payload)=={'scope'},'Choose an acquired furnace and its actual organ procedure.')
    receipt=read(session,f.PARENT,aid,'organ_procedure',payload['scope'],aid)
    require(receipt is not None,'The native world owner must supply the actual surgical or conceptual procedure.')
    require(receipt['receipt_id'] not in state.get('consumed_procedures',[]),'This exact procedure has already been completed.')
    p=receipt['value'];required={'source_rule','quotation','method','operator','source_cl','range_ft','duration_seconds','outcome','requires_consent','complications'}
    require(set(p)==required|({'consent_scope'} if p.get('requires_consent')==1 else set())|({'operator_consent_scope'} if p.get('operator')!=aid else set()),'Supply the complete typed organ procedure and explicit consent requirement.')
    require(p['method'] in ('surgical','conceptual') and p['outcome'] in ('removed','reconstructed','replaced','failed'),
        'Ordinary retraining is not an organ procedure; choose its actual surgical or conceptual outcome.')
    require(all(type(p[k]) is str and p[k].strip() for k in ('source_rule','quotation')) and len(p['source_rule'])<=240,
        'Identify and quote the actual procedure’s controlling Source Rule.')
    require(p['operator'] in session.state['actors'] and integer(p['source_cl'],1) and integer(p['range_ft'])
        and integer(p['duration_seconds']) and type(p['requires_consent']) is int and p['requires_consent'] in (0,1),
        'Supply an actual operator, positive Source CL, whole-foot range, elapsed seconds and explicit consent requirement.')
    operator=session.state['actors'][p['operator']]
    require(not operator['incapacitated'] and int(operator['bundle']['cl'])==p['source_cl'],
        'The procedure’s operator must be available and use their committed Source CL.')
    require(session.grid.distance_ft(Position.model_validate(actor['position']),Position.model_validate(operator['position']))<=p['range_ft'],
        'The actual patient must be within the procedure’s printed range.')
    consent=None
    if p['requires_consent']:
        consent=read(session,f.PARENT,aid,'organ_consent',p['consent_scope'],aid)
        require(consent is not None and consent['value']=={'procedure_receipt':receipt['receipt_id'],'operator':p['operator'],'accepted':1},
            'The patient’s own controller must accept this exact procedure and operator.')
    operator_consent=None
    if p['operator']!=aid:
        operator_consent=read(session,f.PARENT,p['operator'],'organ_operator_consent',p['operator_consent_scope'],aid)
        require(operator_consent is not None and operator_consent['value']=={'procedure_receipt':receipt['receipt_id'],'patient':aid,'accepted':1},
            'The operator’s own controller must accept this exact procedure and patient and share that consent.')
    complications=p['complications']
    require(isinstance(complications,list) and len(complications)<=3 and (p['outcome']=='failed' or not complications),
        'Only a failed removal applies its procedure’s stated complications.')
    maximum=next(pool['maximum'] for pool in actor['bundle']['actor_template']['resources'] if pool['resource_id']==f.QI)
    loss=0
    for c in complications:
        require(isinstance(c,dict) and c.get('kind') in ('hidden_injury','maximum_qi_loss','core_damage'), 'Choose only the printed organ complications.')
        require(set(c)=={'kind','details'}|({'amount'} if c['kind']=='maximum_qi_loss' else set()) and type(c['details']) is str and c['details'].strip(),
            'Describe the actual procedure’s complication; maximum-Qi loss also needs its positive amount.')
        if c['kind']=='maximum_qi_loss':
            require(integer(c['amount'],1),'Maximum-Qi loss must be the actual positive procedure amount.');loss+=c['amount']
    require(loss<=maximum,'The procedure cannot remove more maximum Qi than the actual reservoir has.')
    session.tick(p['duration_seconds'])
    require(read(session,f.PARENT,aid,'organ_procedure',payload['scope'],aid) is not None and not operator['incapacitated'],
        'The procedure’s source and operator must remain available through completion.')
    if consent:require(read(session,f.PARENT,aid,'organ_consent',p['consent_scope'],aid) is not None,'The patient’s consent expired during the procedure.')
    if operator_consent:require(read(session,f.PARENT,p['operator'],'organ_operator_consent',p['operator_consent_scope'],aid) is not None,'The operator’s consent expired during the procedure.')
    if p['outcome']!='failed':state['organ_removed']=int(p['outcome']=='removed')
    state['maximum_qi_loss']=int(state.get('maximum_qi_loss',0))+loss
    for c in complications:state.setdefault('organ_complications',[]).append({**copy.deepcopy(c),'procedure_receipt':receipt['receipt_id'],
        'source_rule':p['source_rule'],'source_cl':p['source_cl'],'operator':p['operator']})
    state.setdefault('consumed_procedures',[]).append(receipt['receipt_id'])
    snapshot=actor.get('encounter_snapshot')
    if snapshot:snapshot['conditions']={k:v for k,v in snapshot['conditions'].items() if json.loads(v)['condition_id']!=f.ORGAN}
    session.emit('SECOND_FURNACE_ORGAN_PROCEDURE',aid,receipt=receipt['receipt_id'],operator=p['operator'],method=p['method'],
        outcome=p['outcome'],seconds=p['duration_seconds'],maximum_qi_lost=loss,complications=complications)
    f.publish(session,aid)
    return True


@hook('match_initialize',priority=10)
def complications(engine):
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id']);native=bundle.get('second_furnace_native') or {}
        if actor is None or not f.acquired(actor):continue
        for c in native.get('organ_complications',[]):
            if c['kind']=='maximum_qi_loss':continue  # represented maximum, never an ordinary restoreable pool
            key='condition:typed.second_furnace_'+c['kind']
            if any(held.condition_id==key and held.data.get('procedure_receipt')==c['procedure_receipt'] for held in actor.conditions.values()):continue
            engine._apply_condition(actor,key,c['source_rule'],c['operator'],expires_on='UNTIL_REMOVED',
                data={'label':('Hidden Injury' if c['kind']=='hidden_injury' else 'Core damage')+': '+c['details'],
                    'procedure_receipt':c['procedure_receipt'],'permanent':1,
                    'information_profile':{'visibility':'owner','tags':[c['kind'],'cultivated_organ'],'source_cl':c['source_cl']}})


@hook('journey_options')
def options(session,aid):
    if session.state['phase']!='travel':return None
    actor=session.state['actors'][aid];state=actor.get('source_states',{}).get(f.PARENT)
    if not state:return None
    scopes=sorted({r['scope'] for r in session.state.get('fact_consent_admission',[])
        if r['source']==f.PARENT and r['subject']==aid and r['kind']=='organ_procedure'})
    result=[]
    for scope in scopes:
        receipt=read(session,f.PARENT,aid,'organ_procedure',scope,aid)
        if not receipt or receipt['receipt_id'] in state.get('consumed_procedures',[]):continue
        p=receipt['value']
        if p.get('outcome') not in ('removed','reconstructed','replaced','failed'):continue
        result.append({'id':'second_furnace_organ:'+receipt['receipt_id'],'kind':'furnace_organ','payload':{'scope':scope},
            'auto_select':0,'label':f"{actor['name']}: second-furnace organ procedure — {p['outcome']}; {p.get('duration_seconds',0)} seconds; {p.get('source_rule','')}"})
    return result or None
