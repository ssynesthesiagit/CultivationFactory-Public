"""Gōruden's source-specific journey collection and scene continuation.

Uses the fact/consent owner's world input and source_states contracts. No owned
Gōruden source and no admitted world fact means no state or bundle changes.
Unknown daemonic corruption is supplied by the native world owner; classification
never comes from a name, damage type, resource balance or creature consent.
"""
from copy import deepcopy
from fractions import Fraction
import json
from . import hook
from .goruden import PREFIX, SHEEN_HIDDEN
from ..canonical import canonical_sha256
from ..resource_costs import parts
from ..journey import require

FAMILY = PREFIX.removesuffix('.feature.')
FIST = PREFIX+'radiant_fist'
KIND = 'active_daemonic_corruption'
SCOPE = 'ongoing_source'
FACT = 'condition:typed.goruden_world_source'


def owned(actor, feature=None):
    bundle=actor['bundle']
    sources={r.get('feature_id') for r in bundle.get('typed_passives',())}
    sources.update((r.get('parameters',{}).get('typed') or {}).get('source') for r in bundle.get('action_catalog',()))
    return feature in sources if feature else any(isinstance(s,str) and s.startswith(PREFIX) for s in sources)


def scene_resources(actor):
    """Actual acquired costs, never a parallel scene-use counter."""
    bundle=actor['bundle'];ids=set()
    for row in bundle.get('action_catalog',()):
        if (row.get('parameters',{}).get('typed') or {}).get('source')==PREFIX+'golden_aura':
            ids.update(rid for raw in row.get('costs',()) if (rid:=parts(raw)[0]) and rid.startswith('resource:uses.'))
    for row in bundle.get('typed_reactions',()):
        if row.get('feature_id')==PREFIX+'immortal_gold':
            ids.update(rid for raw in row.get('costs',()) if (rid:=parts(raw)[0]) and rid.startswith('resource:uses.'))
    return {r['resource_id']:r['maximum'] for r in bundle['actor_template']['resources'] if r['resource_id'] in ids}


def continuation_values(session, aid):
    actor=session.state['actors'][aid]
    # A subject with a world fact may lack the family; it receives only that
    # admitted source, never family ownership, costs, commands or bonuses.
    from ..fact_consent_admission import read,KEY,digest,canonical
    readable=any(owned(a,FIST) for a in session.state['actors'].values())
    record=read(session,FIST,aid,KIND,SCOPE,aid) if readable else None
    present=any((r['source'],r['subject'],r['kind'],r['scope'])==(FIST,aid,KIND,SCOPE)
                for r in session.state.get(KEY,()))
    state=deepcopy(actor.get('source_states',{}).get(FAMILY))
    if not owned(actor) and record is None and state is None:return
    if state is None:state={}
    state.setdefault('scene',session.state.get('scene_id') or session.state['journey_id'])
    state.setdefault('hidden_sheen',0)
    cached=json.loads(state['fact_record']) if state.get('fact_record') else None
    if cached:
        require(cached.get('authority')=='table_owner' and cached.get('source')==FIST
                and cached.get('subject')==aid and cached.get('kind')==KIND and cached.get('scope')==SCOPE
                and cached['receipt_id']==digest({k:v for k,v in cached.items() if k!='receipt_id'}),
                'The carried Gōruden world fact failed its native commitment.')
    if record is not None and (cached is None or cached['receipt_id']!=record['receipt_id']):
        state['fact_record']=canonical(record);cached=record
        state['fact_epoch']=session.state['journey_id']
        state['fact_deadline_num']=record['expires_at'];state['fact_deadline_den']=1
        state['fact_spent_num']=0;state['fact_spent_den']=1
    elif record is None and present and readable:
        # A latest expired/refused declaration never falls back to older input.
        cached=None;state.pop('fact_record',None)
    if cached and state.get('fact_epoch')!=session.state['journey_id']:
        remaining=Fraction(state.get('fact_remaining_num',0),state.get('fact_remaining_den',1))
        deadline=session.clock()+remaining
        state['fact_epoch']=session.state['journey_id']
        state['fact_deadline_num']=deadline.numerator;state['fact_deadline_den']=deadline.denominator
        state['fact_spent_num']=0;state['fact_spent_den']=1
    payload={'scene':state['scene'],'hidden_sheen':state['hidden_sheen']}
    if cached:
        remaining=max(Fraction(0),Fraction(state['fact_deadline_num'],state['fact_deadline_den'])
                      -session.clock()-Fraction(state['fact_spent_num'],state['fact_spent_den']))
        state['fact_remaining_num']=remaining.numerator;state['fact_remaining_den']=remaining.denominator
        if cached['value']==1 and remaining>0:
            payload['corruption']={'record':deepcopy(cached),'remaining_num':remaining.numerator,'remaining_den':remaining.denominator}
    return state,payload


def bind(session, aid):
    projected=continuation_values(session,aid)
    if projected is None:return
    state,payload=projected;actor=session.state['actors'][aid]
    actor.setdefault('source_states',{})[FAMILY]=state
    bundle=actor['bundle'];bundle['goruden_continuation']=payload
    bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)


@hook('journey_combat_bundle')
def combat_bundle(bundle,session,aid):
    """Pure owner-provided pre-genesis export, including just-recorded facts."""
    projected=continuation_values(session,aid)
    if projected is None:return None
    result=deepcopy(bundle);result['goruden_continuation']=projected[1]
    return result


@hook('fact_admission_schema')
def corruption_schema(session, source, subject, kind):
    if (source!=FIST or kind!=KIND or subject not in session.state['actors']
            or not any(owned(a,FIST) for a in session.state['actors'].values())):return None
    return {'authority':'table_owner','value_type':'flag','maximum_seconds':86400,
            'description':'World owner records whether this creature currently bears active daemonic corruption; no creature type, injury, damage or ownership is inferred.'}


@hook('journey_initialize')
def initialize(session,aid):
    bind(session,aid)


@hook('journey_options')
def options(session,aid):
    actor=session.state['actors'][aid]
    if session.state['phase']!='travel' or not owned(actor):return None
    out=[]
    if owned(actor,PREFIX+'golden_sheen'):
        for hidden,word in ((0,'Reveal'),(1,'Suppress')):
            out.append({'id':'goruden.sheen.'+str(hidden),'kind':'goruden_sheen','payload':{'hidden':hidden},
                        'auto_select':0,'label':f"Golden Sheen: {word} {actor['name']}’s visible gold; no action or Stamina cost; defenses remain."})
    if owned(actor,FIST):
        out.append({'id':'goruden.collect','kind':'goruden_collect','payload':{},'auto_select':0,
                    'label':'Radiant Fist: collect current source-scoped world-owner declarations for this scene; no action or Stamina cost.'})
    return out


@hook('journey_command')
def command(session,aid,kind,payload):
    if kind not in ('goruden_sheen','goruden_collect'):return None
    actor=session.state['actors'][aid]
    require(owned(actor,PREFIX+('golden_sheen' if kind=='goruden_sheen' else 'radiant_fist')),'That creature has not acquired this Gōruden feature.')
    if kind=='goruden_sheen':
        require(set(payload)=={'hidden'} and type(payload['hidden']) is int and payload['hidden'] in (0,1),'Choose reveal or suppress.')
        actor.setdefault('source_states',{}).setdefault(FAMILY,{})['hidden_sheen']=payload['hidden']
        session.emit('GORUDEN_SHEEN_CHOSEN',aid,hidden=payload['hidden'],source=PREFIX+'golden_sheen')
    else:
        require(not payload,'Source collection takes no invented fact payload; use the native world-owner input path.')
        session.emit('GORUDEN_SOURCES_COLLECTED',aid,source=FIST)
    for subject in session.state['actors']:bind(session,subject)
    return True


@hook('journey_state_changed')
def state_changed(session,aid):
    bind(session,aid)


@hook('journey_encounter_settled')
def settled(session,aid,engine,creature):
    actor=session.state['actors'][aid]
    if not owned(actor) and FAMILY not in actor.get('source_states',{}):return
    state=actor.setdefault('source_states',{}).setdefault(FAMILY,{})
    captured=next((b.get('goruden_continuation',{}).get('corruption') for b in engine.typed_bundle_documents if b['actor_id']==aid),None)
    if captured:
        condition=next((c for c in creature.conditions.values() if c.condition_id==FACT and c.data['receipt_id']==captured['record']['receipt_id']),None)
        remaining=max(Fraction(0),Fraction(condition.data['deadline_num'],condition.data['deadline_den'])-engine.state.round_number*6) if condition else Fraction(0)
        spent=Fraction(captured['remaining_num'],captured['remaining_den'])-remaining
        total=Fraction(state.get('fact_spent_num',0),state.get('fact_spent_den',1))+spent
        state['fact_spent_num']=total.numerator;state['fact_spent_den']=total.denominator
    state['hidden_sheen']=int(any(c.condition_id==SHEEN_HIDDEN for c in creature.conditions.values()))
    bind(session,aid)


@hook('journey_scene_end')
def scene_end(session,previous,current):
    for aid,actor in session.state['actors'].items():
        if not owned(actor):continue
        state=actor.setdefault('source_states',{}).setdefault(FAMILY,{})
        state['scene']=current
        for rid,maximum in scene_resources(actor).items():actor['resources'][rid]=maximum
        session.emit('GORUDEN_SCENE_SETTLED',aid,source=FAMILY,scene=current)
        bind(session,aid)


@hook('match_initialize', priority=50)
def restore(engine):
    from ..fact_consent_admission import digest
    for bundle in engine.typed_bundle_documents:
        saved=bundle.get('goruden_continuation');actor=engine.state.actors.get(bundle['actor_id'])
        if saved is None or actor is None:continue
        if owned({'bundle':bundle},PREFIX+'golden_sheen'):
            engine._remove_condition(actor,SHEEN_HIDDEN,PREFIX+'golden_sheen')
            if saved['hidden_sheen']:
                engine._apply_condition(actor,SHEEN_HIDDEN,PREFIX+'golden_sheen',actor.entity_id,
                                        expires_on='UNTIL_REMOVED',data={'label':'Golden Sheen: visible gold suppressed; defenses remain'})
        fact=saved.get('corruption')
        if not fact:continue
        record=fact['record']
        require(record.get('authority')=='table_owner' and record.get('source')==FIST and record.get('subject')==actor.entity_id
                and record.get('kind')==KIND and record.get('scope')==SCOPE and record.get('value')==1
                and record['receipt_id']==digest({k:v for k,v in record.items() if k!='receipt_id'}),'Gōruden source declaration failed its native commitment.')
        remaining=Fraction(fact['remaining_num'],fact['remaining_den'])
        if remaining<=0:continue
        deadline=Fraction(engine.state.round_number*6)+remaining
        engine._apply_condition(actor,FACT,FIST,None,expires_on='UNTIL_REMOVED',
            data={'information_profile':{'tags':['daemonic_corruption'],'authority':'table_owner'},
                  'authority_actor_id':'table_owner','subject_id':actor.entity_id,
                  'receipt_id':record['receipt_id'],'deadline_num':deadline.numerator,'deadline_den':deadline.denominator,
                  'label':'World-owner source classification'})


@hook('turn_start', priority=-100)
def expire_world_sources(engine,actor):
    from .condition_ownership import remove_instance
    for subject in engine.state.actors.values():
        for condition in list(subject.conditions.values()):
            if condition.condition_id==FACT and Fraction(engine.state.round_number*6)>=Fraction(condition.data['deadline_num'],condition.data['deadline_den']):
                remove_instance(engine,subject,condition.instance_id,FIST)


@hook('presentation_hidden_conditions')
def private_world_sources(engine,actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id==FACT]


@hook('journey_elapsed')
def elapsed(session,aid,before,seconds,moving):
    bind(session,aid)


@hook('journey_snapshot_actor')
def snapshot_actor(actor,session,aid,engine):
    if not any(c.condition_id==FACT for c in actor.conditions.values()):return None
    copy=actor.model_copy(deep=True)
    copy.conditions={key:c for key,c in copy.conditions.items() if c.condition_id!=FACT}
    return copy
