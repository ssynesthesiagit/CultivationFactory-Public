"""Authored sensory provenance, shared by information providers (currently Bloodsense).

The sealed arena's optional sensory_sources describes actual sources, not
omniscient findings. Each has a medium/kind, optional source_key, and exactly
one entity_id, object_id or position. Attached sources follow live positions;
destroyed objects and off-battlefield creatures are excluded. Integer seconds
are relative to encounter start (negative timestamps describe earlier events).
expires_at_seconds is exclusive. studied_by records historical, observer-owned
sample study; it never implies that an ally also studied that sample.
"""
from .gate2_runtime_models import Position

# Question-sized knowledge inputs share this facade with sensory provenance.
# Neither API grants an observer access before its owned reading resolves.
from copy import deepcopy
import json
from . import ext
from .fact_consent_admission import declare_world, declare_world_combat, world_records, CombatWorldSession

SOURCE = 'system:scene.knowledge'


def validate_fact(key, fact, subject, battlefield, actor_ids):
    if (not isinstance(key, str) or not isinstance(fact, dict)
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


def prepare(battlefield, rows, actor_ids):
    if rows is None:return battlefield
    if not isinstance(rows,list) or len(rows)>256:
        raise ValueError('Scene sources must be a list of at most 256 records.')
    subjects=set(actor_ids)|{'scene'}|{f"object:map.{int(o['id'])}" for o in battlefield.get('map_objects',[])}
    seen=set();result=[]
    for row in rows:
        if not isinstance(row,dict) or not {'subject_id','facts'}<=set(row) or set(row)-{'subject_id','facts','scope'}:
            raise ValueError('A table-owner source needs its native subject and typed facts, not a submitted authority role.')
        subject=row['subject_id']; facts=row['facts']; scope=row.get('scope','scene')
        if type(scope) is not str or not scope or len(scope)>240:raise ValueError('Use a bounded native source scope.')
        if not isinstance(subject,str) or subject not in subjects or (subject,scope) in seen:
            raise ValueError('Choose one distinct, real scene subject.')
        if not isinstance(facts,dict) or not facts or len(facts)>128:raise ValueError('A source needs a bounded set of typed facts.')
        for key,fact in facts.items():validate_fact(key,fact,subject,battlefield,actor_ids)
        seen.add((subject,scope));result.append(deepcopy(row))
    return {**deepcopy(battlefield),'encounter_sources':result}


def payload(subject, key, fact, scope='scene'):
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


def facts(context, subject, scope='scene'):
    """Trusted consumer read from committed admission records, not observations."""
    session=context if isinstance(context.state,dict) else getattr(context,'scene_source_session',None) or CombatWorldSession(context)
    return {key:json.loads(record['value']['fact']) for key,record in world_records(session,SOURCE,subject,scope).items()}


def elapsed_seconds(engine):
    return (engine.state.round_number - 1) * 6


def studied_sources(engine, observer, medium):
    """Historical study survives disappearance/expiry of the physical source."""
    for row in (getattr(engine, 'battlefield_document', None) or {}).get('sensory_sources', []):
        if (isinstance(row, dict) and row.get('medium') == medium
                and isinstance(row.get('studied_by'), list)
                and observer.entity_id in row['studied_by']):
            yield row


def sources(engine, medium):
    now = elapsed_seconds(engine)
    for row in (getattr(engine, 'battlefield_document', None) or {}).get('sensory_sources', []):
        if not isinstance(row, dict) or row.get('medium') != medium:
            continue
        expiry = row.get('expires_at_seconds')
        if expiry is not None and (type(expiry) is not int or now >= expiry):
            continue
        if sum(key in row for key in ('entity_id', 'object_id', 'position')) != 1:
            continue
        actor = engine.state.actors.get(row.get('entity_id'))
        obj = engine.state.objects.get(row.get('object_id'))
        if 'entity_id' in row:
            if actor is None or not engine._on_battlefield(actor):
                continue
            position = actor.position
        elif 'object_id' in row:
            if obj is None or obj.destroyed:
                continue
            position = obj.position
        else:
            try:
                position = Position.model_validate(row['position'])
            except (ValueError, TypeError):
                continue
            if not engine.grid.in_bounds((position.x, position.y)):
                continue
        yield row, position, actor, obj
