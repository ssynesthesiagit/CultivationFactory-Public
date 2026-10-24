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
from .ext import query, run_strict

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
    require(subject in session.state['actors'] and (world or subject == actor_id),
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
    from .ext import run_strict
    for reply in run_strict('fact_admission_validate',session,source,subject,kind,scope,value):
        require(reply is True, 'The source rejected that declaration value.')
    expires=payload['expires_at']; now=int(session.clock())
    require(integer(expires,now+1) and expires <= now+spec['maximum_seconds'], 'Choose an expiry within this source’s limit.')
    readers=payload['readers']
    require(isinstance(readers,list) and all(type(r) is str for r in readers) and len(readers)==len(set(readers)) and set(readers)<=set(session.state['actors']),
            'Readers must be distinct creatures in this journey.')
    for reply in run_strict('fact_admission_readers_validate',session,source,subject,kind,readers):
        require(reply is True,'The source rejected that reader policy.')
    history=session.state.setdefault(KEY,[])
    body={**copy.deepcopy(payload),'authority':actor_id,'created_at':now,
          'sequence':max(int(getattr(session,'fact_sequence_floor',0)),max((int(r['sequence']) for r in history),default=0))+1}
    body['receipt_id']=digest(body)
    history.append(body)
    run_strict('fact_admitted', session, body)
    session.emit('WORLD_FACT_DECLARED' if world else 'FACT_DECLARED',subject,source=source,kind_name=kind,scope=scope,
                 receipt_id=body['receipt_id'],expires_at=expires)
    return body['receipt_id']


def read(session, source, subject, kind, scope, viewer):
    rows=[r for r in session.state.get(KEY,()) if (r['source'],r['subject'],r['kind'],r['scope'])==(source,subject,kind,scope)]
    if not rows:
        return None
    # Chronology is the committed integer sequence, never list or dictionary
    # order: canonical snapshots sort condition keys, whose unpadded event
    # numbers ("...:98" vs "...:102") would otherwise reverse approval and
    # revocation on reload.
    latest=max(rows,key=lambda r:int(r['sequence']))
    world=latest.get('authority')=='table_owner'
    specs=[s for s in query('fact_admission_schema',session,source,subject,kind) if s is not None]
    authority_ok=len(specs)==1 and specs[0].get('authority','subject')==('table_owner' if world else 'subject')
    require(authority_ok and (world or latest.get('authority')==subject) and latest.get('receipt_id')==digest({k:v for k,v in latest.items() if k!='receipt_id'}),
            'The declaration record failed its authority or replay commitment check.')
    allowed = latest['readers'] if world and not specs[0].get('subject_access',True) else (subject,*latest['readers'])
    if latest['expires_at'] <= session.clock() or viewer not in allowed:
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
            allowed=(record['subject'],*record['readers'])
            if record.get('authority')=='table_owner':
                session=NativeFactSession(engine)
                specs=query('fact_admission_schema',session,record['source'],record['subject'],record['kind'])
                require(len(specs)==1 and specs[0].get('authority')=='table_owner','The world declaration has no source authority.')
                allowed=record['readers'] if not specs[0].get('subject_access',True) else allowed
                if record['expires_at']<=session.clock():continue
            if viewer.entity_id not in allowed:continue
            if source is not None and record['source']!=source:continue
            if kind is not None and record['kind']!=kind:continue
            if scope is not None and record['scope']!=scope:continue
            rows.append(copy.deepcopy(record))
    return rows


WORLD_KIND = 'WORLD_FACT_V1'


class NativeFactSession:
    """Detached adapter for the same typed GM admission contract during combat.

    Collectors may update existing condition data only. New conditions, HP,
    resources, acquisition, consent and roll results cannot be supplied here.
    The versioned Gate3 binding is the durable GM input; fighter intents cannot
    select this policy through the ordinary candidate API.
    """
    def __init__(self,engine):
        self.engine=engine
        bundles={b['actor_id']:b for b in getattr(engine,'typed_bundle_documents',())}
        self.state={'actors':{},'events':[],'fact_consent_admission':[]}
        for aid,actor in engine.state.actors.items():
            self.state['actors'][aid]={'bundle':copy.deepcopy(bundles.get(aid,{})),
                'encounter_snapshot':{'conditions':{key:c.model_dump_json(exclude_none=True) for key,c in actor.conditions.items()},
                                      'modifiers':{key:m.model_dump_json(exclude_none=True) for key,m in actor.modifiers.items()}}}
            for c in actor.conditions.values():
                if c.condition_id==CONDITION:
                    record=json.loads(c.data['record'])
                    if record.get('authority')=='table_owner':self.state[KEY].append(record)
        self.original=copy.deepcopy(self.state['actors'])
        self.emitted=[]

    def clock(self):
        return max(0,int(self.engine.state.round_number)-1)*6

    def emit(self,kind,subject,**data):
        self.emitted.append((kind,subject,data))


def prepare_world(engine,payload):
    session=NativeFactSession(engine)
    allowed=query('combat_fact_admission_allowed',session,payload.get('source'),payload.get('subject'),payload.get('kind'))
    require(allowed and all(value is True for value in allowed),'This source does not admit a GM declaration during combat.')
    declare_world(session,payload)
    specs=query('fact_admission_schema',session,payload['source'],payload['subject'],payload['kind'])
    paths=specs[0].get('combat_condition_data_paths',[])
    require(all(isinstance(path,list) and path and all(type(key) is str for key in path) for path in paths),
            'Combat annotation schemas declare exact condition-data paths.')
    def changes(before,after,path=()):
        if before==after:return []
        if isinstance(before,dict) and isinstance(after,dict):
            result=[]
            for key in set(before)|set(after):
                if key not in before or key not in after:result.append((*path,key))
                else:result.extend(changes(before[key],after[key],(*path,key)))
            return result
        return [path]
    for aid,actor in session.state['actors'].items():
        previous=session.original[aid]
        require(actor['bundle']==previous['bundle'] and set(actor)==set(previous),
                'Combat declarations cannot change a build or physiology; record those before combat.')
        require(set(actor['encounter_snapshot'])=={'conditions','modifiers'} and
                actor['encounter_snapshot']['modifiers']==previous['encounter_snapshot']['modifiers'] and
                set(actor['encounter_snapshot']['conditions'])==set(previous['encounter_snapshot']['conditions']),
                'Combat declarations annotate actual existing sources; they cannot create or delete conditions.')
        for key,encoded in actor['encounter_snapshot']['conditions'].items():
            before=json.loads(previous['encounter_snapshot']['conditions'][key]);after=json.loads(encoded)
            require({k:v for k,v in before.items() if k!='data'}=={k:v for k,v in after.items() if k!='data'},
                    'A source declaration cannot change identity, ownership, expiry or mechanical conditions.')
            require(all(any(tuple(path[:len(prefix)])==tuple(prefix) for prefix in paths)
                        for path in changes(before.get('data',{}),after.get('data',{}))),
                    'Source facts cannot write penalties, rules, damage or other mechanical condition data.')
    return session


def validate_world_binding(engine,intent,binding):
    from .canonical import canonical_sha256
    require(set(binding)=={'kind','payload'} and binding['kind']==WORLD_KIND and isinstance(binding['payload'],dict),
            'Invalid world-fact input policy.')
    require(engine.state.terminal_result is None and engine.state.pending_resolution is None
            and intent.state_version==engine.state.state_version and intent.decision_id=='world-fact:v1'
            and intent.candidate_id==canonical_sha256(binding) and intent.actor_id==engine.state.current_actor_id
            and not any((intent.target_ids,intent.option_ids,intent.reaction_decisions,intent.object_ids,
                         intent.destination,intent.placement_destination,intent.movement_path,intent.movement_mode,
                         intent.relation_change,intent.condition_instance_id,intent.penalty_id,intent.source_effect_dc)),
            'Refresh the fight; a GM declaration cannot carry a fighter action or consent.')
    return prepare_world(engine,binding['payload'])


def execute_world_binding(engine,intent,binding):
    session=validate_world_binding(engine,intent,binding)
    record=session.state[KEY][-1]
    source='system:table.world_fact'
    with engine._transaction(source,intent.intent_id,intent.actor_id):
        for aid,actor in session.state['actors'].items():
            holder=engine.state.actors[aid]
            for key,encoded in actor['encounter_snapshot']['conditions'].items():
                if encoded==session.original[aid]['encounter_snapshot']['conditions'][key]:continue
                engine._update_condition_data(holder,holder.conditions[key],json.loads(encoded)['data'],source)
        subject=engine.state.actors[record['subject']]
        engine._apply_condition(subject,CONDITION,source,'table_owner',expires_on='UNTIL_REMOVED',
            data={'record':canonical(record),'world_fact':1,'label':'A private source declaration was recorded'})
        require(any(c.condition_id==CONDITION and json.loads(c.data['record']).get('receipt_id')==record['receipt_id']
                    for c in subject.conditions.values()),'The source declaration could not be durably recorded.')
        engine._append_event('PASSIVE_TRIGGERED',source,target_ids=(subject.entity_id,),
            payload={'receipt_id':record['receipt_id'],'log':'The table owner recorded source facts. No action, time or resource was spent.'})
