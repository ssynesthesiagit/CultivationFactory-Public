"""Typed source-scoped declarations for native journey consumers.

Public contract: declare(session, actor_id, payload) -> receipt_id;
read(session, source, subject, kind, scope, viewer) -> latest live record or None.
Consumers publish fact_admission_schema(session, source, subject, kind) -> dict
with value_type ('text', 'flag', 'document'), maximum_seconds and description.
No schema means rejection. Only the subject's controller may declare their own
subjective state; this is not a GM impersonation or a mechanical-event API.
Mechanical facts must be derived by consumers from committed native state.
Declarations are immutable, replaceable by a new declaration, source/scope bound,
expire on the journey's clock, and retain an audit trail for cold replay.
Private values are returned only to subject and explicit readers. No subscriber
means no menu, grants, conditions, or edits to an unrelated saved journey.
"""
from __future__ import annotations
import copy
import hashlib
import json
from .journey import integer, require
from .ext import query

KEY = 'fact_consent_admission'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def plain(value, depth=0):
    if depth > 12:
        return False
    if type(value) in (str, int):
        return not isinstance(value, str) or len(value) <= 16000
    if isinstance(value, list):
        return len(value) <= 100 and all(plain(v, depth+1) for v in value)
    if isinstance(value, dict):
        return len(value) <= 100 and all(type(k) is str and plain(v, depth+1) for k,v in value.items())
    return False


def declare(session, actor_id, payload):
    return _declare(session,actor_id,payload,world=False)


def declare_world(session,payload):
    """Trusted native table-owner input; never selected by an actor payload."""
    return _declare(session,'table_owner',payload,world=True)


def _declare(session, actor_id, payload, *, world):
    require(set(payload) == {'source', 'subject', 'kind', 'scope', 'value', 'expires_at', 'readers'},
            'Supply source, subject, kind, scope, value, expiry and readers.')
    source, subject, kind, scope = (payload[k] for k in ('source','subject','kind','scope'))
    require(all(type(v) is str and 0 < len(v) <= 240 for v in (source,subject,kind,scope)),
            'Declaration identity must be nonempty text.')
    extra={item for rows in query('fact_admission_subjects',session,source,kind) for item in rows} if world else set()
    require(subject in set(session.state['actors'])|extra and (world or subject == actor_id),
            'Only this creature’s controller may declare its subjective facts or consent.')
    specs = [s for s in query('fact_admission_schema',session,source,subject,kind) if s is not None]
    require(len(specs) == 1, 'That source does not admit this declaration kind.')
    spec=specs[0]; value=payload['value']
    require(spec.get('authority','subject')==('table_owner' if world else 'subject'),
            'This declaration requires the native table-owner input path.' if not world else 'The table owner cannot supply a creature’s private consent.')
    require(plain(value) and len(canonical(value)) <= 32000, 'Declarations use bounded text, integers, lists and documents.')
    require((spec['value_type']=='text' and type(value) is str and bool(value.strip())) or
            (spec['value_type']=='flag' and type(value) is int and value in (0,1)) or
            (spec['value_type']=='document' and isinstance(value,dict)), 'Use the declaration’s required value type.')
    require(False not in query('fact_admission_validate',session,source,subject,kind,value), 'The declaration does not satisfy its source’s typed schema.')
    expires=payload['expires_at']; now=int(session.clock())
    scene_bound=spec.get('lifetime')=='scene' and expires=='scene_end'
    require(scene_bound or integer(expires,now+1) and expires <= now+spec['maximum_seconds'], 'Choose an expiry within this source’s limit.')
    readers=payload['readers']
    require(isinstance(readers,list) and len(readers)==len(set(readers)) and set(readers)<=set(session.state['actors']),
            'Readers must be distinct creatures in this journey.')
    history=session.state.setdefault(KEY,[])
    body={**copy.deepcopy(payload),'authority':actor_id,'created_at':now,'sequence':len(history)+1}
    if scene_bound:body['scene_id']=session.state.get('scene_id',session.state.get('journey_id',''))
    if spec.get('private_to_table'):body['private_to_table']=1
    body['receipt_id']=digest(body)
    history.append(body)
    session.emit('WORLD_FACT_DECLARED' if world else 'FACT_DECLARED',subject,source=source,kind_name=kind,scope=scope,
                 receipt_id=body['receipt_id'],expires_at=expires)
    return body['receipt_id']


def read(session, source, subject, kind, scope, viewer):
    rows=[r for r in session.state.get(KEY,()) if (r['source'],r['subject'],r['kind'],r['scope'])==(source,subject,kind,scope)]
    if not rows:
        return None
    latest=rows[-1]
    world=latest.get('authority')=='table_owner'
    specs=[s for s in query('fact_admission_schema',session,source,subject,kind) if s is not None]
    authority_ok=len(specs)==1 and specs[0].get('authority','subject')==('table_owner' if world else 'subject')
    require(authority_ok and (world or latest.get('authority')==subject) and latest.get('receipt_id')==digest({k:v for k,v in latest.items() if k!='receipt_id'}),
            'The declaration record failed its authority or replay commitment check.')
    expired=(latest.get('scene_id')!=session.state.get('scene_id',session.state.get('journey_id',''))) if latest['expires_at']=='scene_end' else latest['expires_at'] <= session.clock()
    if expired or latest.get('private_to_table') or viewer not in (subject,*latest['readers']):
        return None
    return copy.deepcopy(latest)


CONDITION='condition:typed.fact_consent_admission'


def admit_choice(ctx, subject, source, kind, scope, options, *, labels, prompt,
                 expires_on, readers=(), automatic_options=()):
    """Collect a controller-owned typed fact inside the accepted table intent.

    Callers must gate their Source Rule and supply facts/options actually known
    by that subject. No automatic information means no automatic declaration.
    All manual/Ask turns retain the choice, even on another creature's turn.
    Returns a committed record, or None for refusal; no reaction is spent.
    Only string option values are accepted. Persistence uses the native condition
    and event reducer; cold replay reuses the original accepted choice.
    """
    from .ext.needle import ask,checkpoint_id
    require(ctx.engine.state.actors.get(subject.entity_id) is subject and ctx.intent is not None,
            'Admission requires a live subject and an accepted native intent.')
    require(all(type(s) is str and s for s in (source,kind,scope,expires_on)), 'Admission requires source, kind, scope and expiry.')
    require(isinstance(options,list) and options and all(type(s) is str and s for s in options)
            and len(options)==len(set(options)) and set(automatic_options)<=set(options), 'Supply distinct typed choices and known automatic options.')
    require(set(readers)<=set(ctx.engine.state.actors), 'Name live authorized readers.')
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'fact_admission',source,kind,scope,subject.entity_id),subject,
        'choice:needle.fact_admission.'+kind,options,labels=labels,prompt=prompt,
        minimum=0,maximum=1,allow_decline=True,default='decline',automatic_options=list(automatic_options),
        feature_id=source,name=ctx.action.display_name)
    if not selected:return None
    record={'source':source,'subject':subject.entity_id,'authority':subject.entity_id,'kind':kind,'scope':scope,
        'value':selected[0],'readers':list(readers),'round':ctx.engine.state.round_number,
        'sequence':ctx.engine.state.event_sequence+1,'intent_id':ctx.intent.intent_id,'expires_on':expires_on}
    record['receipt_id']=digest(record)
    ctx.engine._apply_condition(subject,CONDITION,source,subject.entity_id,expires_on=expires_on,
        data={'record':canonical(record),'label':'Source-scoped declaration'})
    return copy.deepcopy(record)


def combat_records(engine, viewer, *, source=None, kind=None, scope=None):
    """Pure authorized view of still-active native admission records."""
    rows=[]
    for actor in engine.state.actors.values():
        for condition in actor.conditions.values():
            if condition.condition_id!=CONDITION:continue
            record=json.loads(condition.data['record'])
            require(record['receipt_id']==digest({k:v for k,v in record.items() if k!='receipt_id'}),
                    'The admission failed its replay commitment check.')
            if record.get('private_to_table') or viewer.entity_id not in (record['subject'],*record['readers']):continue
            if source is not None and record['source']!=source:continue
            if kind is not None and record['kind']!=kind:continue
            if scope is not None and record['scope']!=scope:continue
            rows.append(copy.deepcopy(record))
    return rows


class CombatWorldSession:
    """Native builder adapter for table-owner facts, not creature declarations.

    This adapter reads actual engine actors and committed admission conditions;
    its only write is the normal native condition event. Public actor readers
    cannot retrieve these table-private records.
    """
    def __init__(self,engine):
        self.engine=engine
        rows=[]
        for actor in engine.state.actors.values():
            for held in actor.conditions.values():
                if held.condition_id==CONDITION and held.data.get('record'):
                    rows.append(json.loads(held.data['record']))
        self.state={'actors':engine.state.actors,KEY:rows,'scene_id':'native:'+engine.state.match_seed,
                    'battlefield':engine.battlefield_document}
    def clock(self):
        return max(0,(self.engine.state.round_number-1)*6)
    def emit(self,kind,subject,**metadata):
        record=self.state[KEY][-1]
        holder=next(iter(self.engine.state.actors.values()))
        self.engine._apply_condition(holder,CONDITION,record['source'],holder.entity_id,
            expires_on='UNTIL_REMOVED',data={'record':canonical(record),'label':'Private world-source declaration'})


def declare_world_combat(engine,payload):
    """Trusted native setup input, using the same schema and receipt producer."""
    return declare_world(CombatWorldSession(engine),payload)


def world_records(session,source,subject):
    """Trusted consumer query; never returned by an actor observation endpoint."""
    latest={}
    for record in session.state.get(KEY,()):
        if record['source']==source and record['subject']==subject:
            latest[record['kind']]=record
    rows={}
    for key,record in latest.items():
        require(record.get('authority')=='table_owner' and record['receipt_id']==digest({k:v for k,v in record.items() if k!='receipt_id'}),
                'The world input failed its authority or replay commitment check.')
        if record['expires_at']=='scene_end':
            if record.get('scene_id')!=session.state.get('scene_id',session.state.get('journey_id','')):continue
        elif record['expires_at']<=session.clock():continue
        rows[key]=copy.deepcopy(record)
    return rows

def map_object_declarations(value, object_number, *, subject_prefix="map-object"):
    """Validate GM-authored intrinsic object facts before a map is saved.

    Source schemas use the same fact_admission_schema contract with session=None
    and subject='map-object:<number>'. They must explicitly declare authority
    'gm:map'. Facts cannot supply actor willingness or mechanical event receipts.
    Each saved map and its native object genesis retain the exact declaration.
    This pure function returns [] without declarations; no old map is modified.
    """
    require(isinstance(value,list) and len(value)<=16,'An object admits at most sixteen source declarations.')
    result=[]
    for payload in value:
        if isinstance(payload,dict) and 'receipt_id' in payload:
            require(set(payload)=={'source','kind','value','subject','authority','receipt_id'}
                    and payload['authority']=='gm:map' and payload['subject']==f'{subject_prefix}:{object_number}'
                    and payload['receipt_id']==digest({k:v for k,v in payload.items() if k!='receipt_id'}),
                    'The saved object fact failed its authority or commitment check.')
            payload={k:payload[k] for k in ('source','kind','value')}
        require(isinstance(payload,dict) and set(payload)=={'source','kind','value'},
                'Object declarations require source, kind and typed value.')
        source,kind=payload['source'],payload['kind']
        require(all(type(v) is str and 0<len(v)<=240 for v in (source,kind)), 'Use bounded declaration names.')
        subject=f'{subject_prefix}:{object_number}'
        specs=[s for s in query('fact_admission_schema',None,source,subject,kind) if s is not None]
        require(len(specs)==1 and specs[0].get('authority')=='gm:map', 'This source does not admit a GM object declaration.')
        spec=specs[0];typed=payload['value']
        require(spec.get('value_type')=='document' and isinstance(typed,dict) and plain(typed) and len(canonical(typed))<=32000, 'Use the source’s typed object document.')
        validate=spec.get('validate')
        require(callable(validate) and validate(typed), 'The source rejected the object declaration fields.')
        body={**copy.deepcopy(payload),'subject':subject,'authority':'gm:map'}
        body['receipt_id']=digest(body)
        result.append(body)
    require(len({(r['source'],r['kind']) for r in result})==len(result), 'Declare each object fact once.')
    return result


def object_fact(obj, source, kind):
    """Read one committed map-authored fact, checking authority and commitment."""
    rows=[r for r in (obj.component or {}).get(KEY,[]) if r['source']==source and r['kind']==kind]
    if not rows:
        return None
    require(len(rows)==1,'Object fact identity is ambiguous.')
    record=rows[0]
    expected='map-object:'+obj.object_id.removeprefix('object:map.')
    require(obj.object_id.startswith('object:map.') and record.get('subject')==expected,
            'The object fact belongs to a different native object.')
    require(record.get('authority')=='gm:map' and record.get('receipt_id')==digest({k:v for k,v in record.items() if k!='receipt_id'}),
            'The object declaration failed its authority or replay commitment check.')
    return copy.deepcopy(record['value'])


GM_CONTEXT='condition:typed.gm_context_fact'


def map_context_declarations(value):
    """GM-authored, source-scoped context documents using the same schema path."""
    require(isinstance(value,list) and len(value)<=100,'Use at most one hundred context declarations.')
    return [record for index,payload in enumerate(value,1)
            for record in map_object_declarations([payload],index,subject_prefix='map-context')]


def commit_context_facts(engine,actor,action):
    """Bind a GM declaration to the actual owned action inside its native intent.

    Maps name an exact actor/action, never an event which did not happen.
    The producer records use only after that action is accepted. Its facts are
    private to the subject and explicit readers. No declarations is inert.
    """
    intent=getattr(engine,'_active_intent',None)
    if intent is None or action.owner_id not in {actor.entity_id,'*'}:
        return
    for record in (getattr(engine,'battlefield_document',None) or {}).get('context_declarations') or []:
        require(record.get('receipt_id')==digest({k:v for k,v in record.items() if k!='receipt_id'})
                and record.get('authority')=='gm:map','The GM context fact failed its commitment check.')
        value=record['value']
        if value.get('actor_id')!=actor.entity_id or value.get('action_source')!=action.source_definition_id:
            continue
        readers=value.get('readers') or []
        require(isinstance(readers,list) and set(readers)<=set(engine.state.actors), 'Context readers must be native creatures in this encounter.')
        used={'record':copy.deepcopy(record),'subject':actor.entity_id,'intent_id':intent.intent_id,
              'action_source':action.source_definition_id,'readers':list(readers)}
        specs=[spec for spec in query('fact_admission_schema',None,record['source'],record['subject'],record['kind']) if spec is not None]
        retain=len(specs)==1 and specs[0].get('retention')=='source'
        clock='UNTIL_REMOVED' if retain else 'END_OF_CURRENT_TURN'
        identity={'action':action.source_definition_id,**({} if retain else {'intent':intent.intent_id})}
        engine._apply_condition(actor,GM_CONTEXT,record['source']+'#context:'+digest(identity),actor.entity_id,
            expires_on=clock,data={'record':canonical(used),'label':'Private source context'})


def context_fact(engine,viewer,subject,source,kind,*,action_source=None):
    """Authorized facts bound to the active committed activation, or None."""
    intent=getattr(engine,'_active_intent',None)
    if intent is None:
        return None
    for held in subject.conditions.values():
        if held.condition_id!=GM_CONTEXT:
            continue
        used=json.loads(held.data['record']);record=used['record']
        require(used.get('readers')==record['value'].get('readers')
                and used.get('subject')==record['value'].get('actor_id')
                and used.get('action_source')==record['value'].get('action_source'),
                'The source context binding failed its authority check.')
        require(record['receipt_id']==digest({k:v for k,v in record.items() if k!='receipt_id'}), 'The source context failed its replay commitment check.')
        if (used['intent_id']==intent.intent_id and used['subject']==subject.entity_id
                and record['source']==source and record['kind']==kind
                and (action_source is None or used['action_source']==action_source)
                and viewer.entity_id in (subject.entity_id,*used['readers'])):
            return copy.deepcopy(record['value'])
    return None


def retained_context_fact(engine,viewer,subject,source,kind,action_source):
    """Intrinsic source facts from a real committed activation, not transient intent facts."""
    for held in subject.conditions.values():
        if held.condition_id!=GM_CONTEXT or held.expires_on!='UNTIL_REMOVED':
            continue
        used=json.loads(held.data['record']);record=used['record'];value=record['value']
        require(record.get('authority')=='gm:map' and record['receipt_id']==digest({k:v for k,v in record.items() if k!='receipt_id'})
                and used['subject']==value.get('actor_id') and used['readers']==value.get('readers')
                and used['action_source']==value.get('action_source'),'The retained source fact failed its commitment check.')
        if (record['source']==source and record['kind']==kind and used['subject']==subject.entity_id
                and used['action_source']==action_source and viewer.entity_id in (subject.entity_id,*used['readers'])):
            return copy.deepcopy(value)
    return None
