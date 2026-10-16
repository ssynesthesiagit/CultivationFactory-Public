"""Knowledge-source facade over the shared fact/consent admission contract.

Factory and journey setup are trusted table-owner inputs, not submitted actor
roles. This module validates question-sized source facts; the common admission
producer owns authority, privacy, source clocks and immutable native replay.
Source consumers never read raw submitted facts as an observation permission.
"""
from copy import deepcopy
import json
from . import ext
from .fact_consent_admission import declare_world,declare_world_combat,world_records,CombatWorldSession

SOURCE='system:scene.knowledge'


def validate_fact(key,fact,subject,battlefield,actor_ids):
    if (not isinstance(key,str) or not isinstance(fact,dict)
            or set(fact)-{'value','access','cl','dc','creator_id'} or 'value' not in fact
            or fact.get('access','surface') not in ('surface','internal','concealed')
            or ('cl' in fact and (type(fact['cl']) is not int or fact['cl']<1))
            or ('dc' in fact and (type(fact['dc']) is not int or fact['dc']<0))
            or ('creator_id' in fact and (not isinstance(fact['creator_id'],str) or fact['creator_id'] not in actor_ids))):
        raise ValueError('Facts need a typed value, access and whole-number authority/DC.')
    from .observer_information import primitives
    if not primitives(fact) or not any(v is True for v in ext.run_strict('source_fact_validate',key,fact['value'],'gm')):
        raise ValueError('Unknown or unauthorized scene fact: '+key)
    row={'subject_id':subject,'facts':{key:fact}}
    if any(v is False for v in ext.run_strict('source_fact_context_validate',key,fact,row,battlefield,tuple(actor_ids))):
        raise ValueError('This scene fact conflicts with its native subject or map: '+key)


def prepare(battlefield,rows,actor_ids):
    if rows is None:
        return battlefield
    if not isinstance(rows,list) or len(rows)>256:
        raise ValueError('Scene sources must be a list of at most 256 records.')
    subjects=set(actor_ids)|{'scene'}|{f"object:map.{int(o['id'])}" for o in battlefield.get('map_objects',[])}
    seen=set();result=[]
    for row in rows:
        if not isinstance(row,dict) or not {'subject_id','facts'}<=set(row) or set(row)-{'subject_id','facts','scope'}:
            raise ValueError('A table-owner source needs its native subject and typed facts, not a submitted authority role.')
        subject=row['subject_id'];facts=row['facts'];scope=row.get('scope','scene')
        if type(scope) is not str or not scope or len(scope)>240:raise ValueError('Use a bounded native source scope.')
        if not isinstance(subject,str) or subject not in subjects or (subject,scope) in seen:
            raise ValueError('Choose one distinct, real scene subject.')
        if not isinstance(facts,dict) or not facts or len(facts)>128:
            raise ValueError('A source needs a bounded set of typed facts.')
        for key,fact in facts.items():
            validate_fact(key,fact,subject,battlefield,actor_ids)
        seen.add((subject,scope));result.append(deepcopy(row))
    return {**deepcopy(battlefield),'encounter_sources':result}


def payload(subject,key,fact,scope='scene'):
    return {'source':SOURCE,'subject':subject,'kind':key,'scope':scope,
        'value':{'fact':json.dumps(fact,sort_keys=True,separators=(',',':'))},
        'expires_at':'scene_end','readers':[]}


def admit_setup(context):
    native=not isinstance(context.state,dict)
    battlefield=context.battlefield_document if native else context.state['battlefield']
    for row in battlefield.get('encounter_sources',[]):
        for key in sorted(row['facts']):
            body=payload(row['subject_id'],key,row['facts'][key],row.get('scope','scene'))
            declare_world_combat(context,body) if native else declare_world(context,body)


def facts(context,subject,scope='scene'):
    """Trusted consumer read from actual committed shared admission records."""
    session=context if isinstance(context.state,dict) else getattr(context,'scene_source_session',None) or CombatWorldSession(context)
    rows=world_records(session,SOURCE,subject,scope)
    return {key:json.loads(record['value']['fact']) for key,record in rows.items()}
