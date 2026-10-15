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
    require(subject in session.state['actors'] and (world or subject == actor_id),
            'Only this creature’s controller may declare its subjective facts or consent.')
    specs = [s for s in query('fact_admission_schema',session,source,subject,kind) if s is not None]
    require(len(specs) == 1, 'That source does not admit this declaration kind.')
    spec=specs[0]; value=payload['value']
    require(not getattr(session, 'is_combat_fact_context', False) or spec.get('combat') is True,
            'That source does not admit declarations during combat.')
    require(spec.get('authority','subject')==('table_owner' if world else 'subject'),
            'This declaration requires the native table-owner input path.' if not world else 'The table owner cannot supply a creature’s private consent.')
    require(plain(value) and len(canonical(value)) <= 32000, 'Declarations use bounded text, integers, lists and documents.')
    require((spec['value_type']=='text' and type(value) is str and bool(value.strip())) or
            (spec['value_type']=='flag' and type(value) is int and value in (0,1)) or
            (spec['value_type']=='document' and isinstance(value,dict)), 'Use the declaration’s required value type.')
    validators = [answer for answer in query('fact_admission_value', session, payload)
                  if answer is not None]
    require(all(type(answer) is bool for answer in validators) and not any(answer is False for answer in validators)
            and (not spec.get('validate_value') or validators == [True]),
            'The declaration does not match its source, subject, scope, or native reference.')
    expires=payload['expires_at']; now=int(session.clock())
    require(integer(expires,now+1) and expires <= now+spec['maximum_seconds'], 'Choose an expiry within this source’s limit.')
    readers=payload['readers']
    require(isinstance(readers,list) and all(type(reader) is str for reader in readers)
            and len(readers)==len(set(readers)) and set(readers)<=set(session.state['actors']),
            'Readers must be distinct creatures in this journey.')
    history=session.state.setdefault(KEY,[])
    sequence = session.next_fact_sequence() if getattr(session, 'is_combat_fact_context', False) else len(history)+1
    body={**copy.deepcopy(payload),'authority':actor_id,'created_at':now,'sequence':sequence}
    body['receipt_id']=digest(body)
    history.append(body)
    # Combat validation uses a temporary adapter, never a mechanical mutation.
    # Its source consumer runs only inside SOURCE_INPUT_V1's actual transaction.
    if not getattr(session, 'is_combat_fact_context', False):
        from .ext import run_strict
        run_strict('fact_admitted', session, copy.deepcopy(body))
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
    expiry = deadline(session, latest)
    if expiry <= session.clock() or viewer not in (subject,*latest['readers']):
        return None
    return copy.deepcopy(latest)


def deadline(session, record):
    """Exact journey deadline; the immutable source receipt is never rewritten."""
    from fractions import Fraction
    value = session.state.get('fact_consent_deadlines', {}).get(record['receipt_id'], record.get('expires_at', 0))
    return Fraction(*value) if isinstance(value, list) else Fraction(value)


CONDITION='condition:typed.fact_consent_admission'
HEAD='condition:typed.fact_consent_head'


def identity(record):
    """The one replaceable source/subject/kind/scope, before reader filtering."""
    return tuple(record[k] for k in ('source', 'subject', 'kind', 'scope'))


def commit_record(engine, subject, record, expires_on):
    """Commit an admission and its durable latest-version marker.

    Used by source intents, controller choices and journey restoration. Keeping
    the latest marker after expiry prevents an older acceptance becoming live
    again when a shorter refusal expires. Neither marker grants a mechanic.
    """
    require(record['receipt_id'] == digest({k:v for k,v in record.items() if k != 'receipt_id'}),
            'The admission failed its replay commitment check.')
    for condition in list(subject.conditions.values()):
        if condition.condition_id in (CONDITION, HEAD) and identity(json.loads(condition.data['record'])) == identity(record):
            engine._remove_condition_instance(subject, condition.instance_id, record['source'],
                payload={'reason':'SOURCE_DECLARATION_SUPERSEDED'})
    engine._apply_condition(subject, HEAD, record['source'], subject.entity_id, expires_on='UNTIL_REMOVED',
        data={'record':canonical(record), 'deadline':expires_on or '', 'label':'Source declaration history'})
    if expires_on is not None:
        engine._apply_condition(subject, CONDITION, record['source'], subject.entity_id, expires_on=expires_on,
            data={'record':canonical(record), 'label':'Source-scoped declaration'})


def latest_conditions(actor):
    """Latest immutable records, including expired heads; no privacy expansion."""
    latest = {}
    for condition in actor.conditions.values():
        if condition.condition_id not in (CONDITION, HEAD):
            continue
        record = json.loads(condition.data['record'])
        key = identity(record)
        if key not in latest or condition.applied_sequence > latest[key].applied_sequence:
            latest[key] = condition
    return list(latest.values())


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
    commit_record(ctx.engine, subject, record, expires_on)
    return copy.deepcopy(record)


def combat_records(engine, viewer, *, source=None, kind=None, scope=None):
    """Latest active record per scope, selected before the privacy filter.

    Revoking a reader must hide an earlier acceptance too, just as read() does
    in journeys. Native condition application order survives cold JSON sorting.
    """
    latest={}
    for actor in engine.state.actors.values():
        for condition in actor.conditions.values():
            if condition.condition_id!=CONDITION:continue
            record=json.loads(condition.data['record'])
            require(record['receipt_id']==digest({k:v for k,v in record.items() if k!='receipt_id'}),
                    'The admission failed its replay commitment check.')
            if source is not None and record['source']!=source:continue
            if kind is not None and record['kind']!=kind:continue
            if scope is not None and record['scope']!=scope:continue
            key=(record['source'],record['subject'],record['kind'],record['scope'])
            if key not in latest or condition.applied_sequence>latest[key][0]:
                latest[key]=(condition.applied_sequence,record)
    return [copy.deepcopy(record) for _,record in sorted(latest.values(),key=lambda pair:pair[0])
            if viewer.entity_id in (record['subject'],*record['readers'])]
