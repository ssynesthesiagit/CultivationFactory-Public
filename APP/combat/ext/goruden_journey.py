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
from .goruden import PREFIX, SHEEN_HIDDEN, AURA_CHOICE, sheen_can_adjust
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
    payload={'scene':state['scene'],'hidden_sheen':state['hidden_sheen'],
             'native_turns_total':state.get('native_turns_total',0)}
    if cached:
        remaining=max(Fraction(0),Fraction(state['fact_deadline_num'],state['fact_deadline_den'])
                      -session.clock()-Fraction(state['fact_spent_num'],state['fact_spent_den']))
        state['fact_remaining_num']=remaining.numerator;state['fact_remaining_den']=remaining.denominator
        if cached['value']==1 and remaining>0:
            payload['corruption']={'record':deepcopy(cached),'remaining_num':remaining.numerator,'remaining_den':remaining.denominator}
    if owned(actor,PREFIX+'golden_aura') and (state.get('aura_record') or state.get('aura_activation')):
        if state.get('aura_epoch')!=session.state['journey_id']:
            deadline=session.clock()+Fraction(state['aura_remaining_num'],state['aura_remaining_den'])
            state['aura_epoch']=session.state['journey_id']
            state['aura_deadline_num']=deadline.numerator;state['aura_deadline_den']=deadline.denominator
        remaining=max(Fraction(0),Fraction(state['aura_deadline_num'],state['aura_deadline_den'])-session.clock())
        state['aura_remaining_num']=remaining.numerator;state['aura_remaining_den']=remaining.denominator
        if remaining>0:
            payload['aura']={**({'record':state['aura_record']} if state.get('aura_record') else {'activation':state['aura_activation']}),'choices':state.get('aura_choices',[]),
                             'remaining_num':remaining.numerator,'remaining_den':remaining.denominator}
    native=state.get('native_effects')
    if native:
        if state.get('native_epoch')!=session.state['journey_id']:
            deadline=session.clock()+Fraction(state['native_remaining_num'],state['native_remaining_den'])
            state['native_epoch']=session.state['journey_id']
            state['native_deadline_num']=deadline.numerator;state['native_deadline_den']=deadline.denominator
        remaining=max(Fraction(0),Fraction(state['native_deadline_num'],state['native_deadline_den'])-session.clock())
        state['native_remaining_num']=remaining.numerator;state['native_remaining_den']=remaining.denominator
        if remaining>0 or native_statue(native):
            live=live_native(session,native)
            if live:payload['native']={**live,'remaining_num':remaining.numerator,'remaining_den':remaining.denominator}
            else:state.pop('native_effects',None)
        else:state.pop('native_effects',None)
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
    if owned(actor,PREFIX+'golden_sheen') and cosmetic_control(actor):
        for hidden,word in ((0,'Reveal'),(1,'Suppress')):
            out.append({'id':'goruden.sheen.'+str(hidden),'kind':'goruden_sheen','payload':{'hidden':hidden},
                        'auto_select':0,'label':f"Golden Sheen: {word} {actor['name']}’s visible gold; no action or Stamina cost; defenses remain."})
    if owned(actor,FIST):
        out.append({'id':'goruden.collect','kind':'goruden_collect','payload':{},'auto_select':0,
                    'label':'Radiant Fist: mark which creatures the GM has confirmed are under daemonic corruption. Your Radiant Fist bonus damage is doubled against those creatures while the corruption lasts. No action or Stamina cost.'})
    return out


def cosmetic_control(actor):
    """Project only committed native snapshot conditions into the shared query."""
    from types import SimpleNamespace
    from ..gate2_runtime_models import ConditionInstance
    snapshot=actor.get('encounter_snapshot') or {}
    conditions={key:ConditionInstance.model_validate_json(row)
                for key,row in snapshot.get('conditions',{}).items()}
    return sheen_can_adjust(SimpleNamespace(conditions=conditions))


@hook('journey_command')
def command(session,aid,kind,payload):
    if kind not in ('goruden_sheen','goruden_collect'):return None
    actor=session.state['actors'][aid]
    require(owned(actor,PREFIX+('golden_sheen' if kind=='goruden_sheen' else 'radiant_fist')),'That creature has not acquired this Gōruden feature.')
    if kind=='goruden_sheen':
        require(cosmetic_control(actor),'Golden Sheen: this creature is unconscious or dead and cannot change its cosmetic stance.')
        require(set(payload)=={'hidden'} and type(payload['hidden']) is int and payload['hidden'] in (0,1),'Choose reveal or suppress.')
        actor.setdefault('source_states',{}).setdefault(FAMILY,{})['hidden_sheen']=payload['hidden']
        session.emit('GORUDEN_SHEEN_CHOSEN',aid,hidden=payload['hidden'],source=PREFIX+'golden_sheen')
    else:
        require(not payload,'Ask the GM to confirm which creatures are affected by daemonic corruption before collecting sources.')
        session.emit('GORUDEN_SOURCES_COLLECTED',aid,source=FIST)
    for subject in session.state['actors']:bind(session,subject)
    return True


@hook('journey_state_changed')
def state_changed(session,aid):
    bind(session,aid)


@hook('journey_encounter_settled')
def settled(session,aid,engine,creature):
    actor=session.state['actors'][aid]
    native=native_parts(engine,creature)
    if native and FAMILY not in actor.get('source_states',{}):
        actor.setdefault('source_states',{})[FAMILY]={}
    captured=next((b.get('goruden_continuation',{}).get('corruption') for b in engine.typed_bundle_documents if b['actor_id']==aid),None)
    # The pure entry export need not have persisted source_states. Bind the
    # actual current receipt before charging the captured encounter lifetime.
    projected=continuation_values(session,aid)
    if projected is None:return
    state,_=projected
    actor.setdefault('source_states',{})[FAMILY]=state
    entry=next((b.get('goruden_continuation',{}) for b in engine.typed_bundle_documents if b['actor_id']==aid),{})
    # Count actual committed expiry starts, even when a prior target is absent.
    # The sealed encounter input makes this independent of settlement order.
    state['native_turns_total']=entry.get('native_turns_total',0)+expiry_starts(creature)
    current=json.loads(state['fact_record']) if state.get('fact_record') else None
    if captured and current and current['receipt_id']==captured['record']['receipt_id']:
        condition=next((c for c in creature.conditions.values() if c.condition_id==FACT and c.data['receipt_id']==captured['record']['receipt_id']),None)
        remaining=max(Fraction(0),Fraction(condition.data['deadline_num'],condition.data['deadline_den'])-engine.state.round_number*6) if condition else Fraction(0)
        initial=Fraction(captured['remaining_num'],captured['remaining_den'])
        spent=max(Fraction(0),initial-remaining)
        total=Fraction(state.get('fact_spent_num',0),state.get('fact_spent_den',1))+spent
        state['fact_spent_num']=total.numerator;state['fact_spent_den']=total.denominator
    if owned(actor,PREFIX+'golden_aura'):
        active=[z for z in managed_auras(engine) if z.owner_id==aid]
        state.pop('aura_record',None);state.pop('aura_choices',None);state.pop('aura_activation',None)
        if active:
            zone=active[-1]
            deadline=zone.trigger_profile.get('goruden_deadline')
            clock=Fraction(deadline['num'],deadline['den']) if deadline else Fraction((zone.created_round+zone.duration_rounds)*6)
            remaining=max(Fraction(0),clock-engine.state.round_number*6)
            state['aura_record']=zone.model_dump_json()
            state['aura_choices']=[c.model_dump_json() for c in creature.conditions.values()
                                   if c.condition_id==AURA_CHOICE and c.data.get('zone_id')==zone.zone_id]
            state['aura_epoch']=session.state['journey_id']
            end=session.clock()+remaining
            state['aura_deadline_num']=end.numerator;state['aura_deadline_den']=end.denominator
            state['aura_remaining_num']=remaining.numerator;state['aura_remaining_den']=remaining.denominator
    state.pop('native_effects',None)
    if native:
        state['native_effects']=native
        state['native_epoch']=session.state['journey_id']
        state['native_deadline_num']=(session.clock()+6).numerator
        state['native_deadline_den']=(session.clock()+6).denominator
        state['native_remaining_num']=6;state['native_remaining_den']=1
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
        aura=saved.get('aura')
        if aura and owned({'bundle':bundle},PREFIX+'golden_aura'):
            restore_aura(engine,actor,aura)
        if saved.get('native'):restore_native(engine,actor,saved['native'])
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
                  'label':'Active daemonic corruption confirmed by the GM'})


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


def aura_source(engine,zone):
    action=engine.action_catalog.get(zone.source_definition_id)
    return bool(action and action.owner_id==zone.owner_id and
                (action.parameters.get('typed') or {}).get('source')==PREFIX+'golden_aura')


def managed_auras(engine):
    """Include dormant activations: suppression never pauses their clock."""
    return [z for z in engine.state.zones.values() if z.active
            and aura_source(engine,z) and z.trigger_profile.get('golden_ally_choices')]


def restore_aura(engine,actor,saved):
    """Restore the committed activation, never recast or pay/refund a use."""
    from ..gate2_runtime_models import ZoneState,ConditionInstance
    from .. import zones
    if saved.get('record'):
        zone=ZoneState.model_validate_json(saved['record'])
    else:
        activation=saved['activation'];current=engine.action_catalog.get(activation['source'])
        from ..gate2_runtime_models import ActionDefinition
        action=ActionDefinition.model_validate_json(activation['action_record'])
        require(current is not None and current.owner_id==actor.entity_id
                and (current.parameters.get('typed') or {}).get('source')==PREFIX+'golden_aura'
                and action.owner_id==actor.entity_id and action.source_definition_id==activation['source']
                and (action.parameters.get('typed') or {}).get('source')==PREFIX+'golden_aura'
                and action.parameters['typed'].get('zone_spec'), 'The carried Golden Aura source is not acquired.')
        from ..typed_executor import Context
        typed=action.parameters['typed']
        zone=zones.prospective_zone(Context(engine,actor,action,None,typed,[],None,{}),
                                   typed['zone_spec'],actor.position,zone_id=activation['zone_id'])
        zone.trigger_profile['golden_ally_choices']=1
    require(zone.owner_id==actor.entity_id and aura_source(engine,zone)
            and zone.active and zone.trigger_profile.get('golden_ally_choices'),
            'The carried Golden Aura does not belong to this cultivator.')
    remaining=Fraction(saved['remaining_num'],saved['remaining_den'])
    if remaining<=0:return
    deadline=engine.state.round_number*6+remaining
    zone.trigger_profile['goruden_deadline']={'num':deadline.numerator,'den':deadline.denominator}
    zone.created_round=engine.state.round_number
    zone.duration_rounds=max(1,(remaining.numerator+6*remaining.denominator-1)//(6*remaining.denominator))
    # Preserve only once-per-activation usage; old encounter turn keys cannot
    # suppress a new turn's hostile save.
    once_prefixes=tuple(f"{r.get('id') or r.get('name')}:" for r in zone.trigger_profile.get('triggers',())
                        if r.get('once_per_creature'))
    # A recipient can be absent for an encounter and later rejoin this same
    # activation. Retain their consumed mark too. Presence, not the old turn
    # number, is authoritative for once-per-creature triggers.
    zone.per_turn_triggered={k:0 for k in zone.per_turn_triggered if k.startswith(once_prefixes)}
    engine.state.zones[zone.zone_id]=zone
    engine._append_event('ZONE_CREATED',zone.source_definition_id,actor_id=actor.entity_id,
                         payload={'zone':zone.model_dump(mode='json'),'continuation':1})
    for raw in saved.get('choices',()):
        c=ConditionInstance.model_validate_json(raw)
        require(c.condition_id==AURA_CHOICE and c.source_actor_id==actor.entity_id
                and c.data.get('zone_id')==zone.zone_id,'Invalid carried Golden Aura choice.')
        engine._apply_condition(actor,c.condition_id,c.source_definition_id,c.source_actor_id,
                                expires_on='UNTIL_REMOVED',data=c.data)
    # Encounter setup can place the creator on a different square. Reuse the
    # normal follower update (including suppression and its replay receipt)
    # before reconciling benefits; this does not fire movement/entry triggers.
    zones.follow(engine,actor)


@hook('turn_start',priority=-100)
def expire_carried_aura(engine,actor):
    from .. import zones
    for zone in managed_auras(engine):
        deadline=zone.trigger_profile.get('goruden_deadline')
        if zone.owner_id==actor.entity_id and deadline and Fraction(engine.state.round_number*6)>=Fraction(deadline['num'],deadline['den']):
            zones.remove(engine,zone,'DURATION_ENDED')


@hook('journey_snapshot_actor')
def snapshot_actor(actor,session,aid,engine):
    from ..zones import ZONE_EFFECT
    ids={z.zone_id for z in managed_auras(engine)}
    removed=[c for c in actor.conditions.values() if c.condition_id==FACT or
             (c.condition_id in (ZONE_EFFECT,AURA_CHOICE) and c.data.get('zone_id') in ids)]
    native=native_parts(engine,actor)
    native_conditions=set()
    native_modifiers=set()
    if native:
        from ..gate2_runtime_models import ConditionInstance,ModifierInstance
        native_conditions={ConditionInstance.model_validate_json(r).instance_id for r in native['conditions']}
        native_modifiers={ModifierInstance.model_validate_json(r).modifier_id for r in native['modifiers']}
    # Also discard expired carried records, which must not regain six seconds.
    native_conditions.update(c.instance_id for c in actor.conditions.values() if c.data.get('goruden_carried_deadline'))
    native_modifiers.update(mid for mid in actor.modifiers if '_round_goruden_carried:'+mid in actor.turn_flags)
    if not removed and not native_conditions and not native_modifiers:return None
    copy=actor.model_copy(deep=True)
    for iid in native_conditions:copy.conditions.pop(iid,None)
    for mid in native_modifiers:copy.modifiers.pop(mid,None)
    for c in removed:
        copy.conditions.pop(c.instance_id,None)
        for mid in c.data.get('zone_modifiers',()):copy.modifiers.pop(mid,None)
    return copy


STAMINA='resource:core.stamina'
CULTIVATION=FAMILY+'.cultivation_session'


def aura_action(actor):
    return next((a for a in actor['bundle'].get('action_catalog',())
                 if a['owner_id']==actor['bundle']['actor_id'] and
                 (a.get('parameters',{}).get('typed') or {}).get('source')==PREFIX+'golden_aura'
                 and (a.get('parameters',{}).get('typed') or {}).get('zone_spec')),None)


def able(actor):
    from types import SimpleNamespace
    from ..gate2_runtime_models import ConditionInstance
    from ..typed_executor import condition_rules
    snapshot=actor.get('encounter_snapshot') or {}
    creature=SimpleNamespace(conditions={k:ConditionInstance.model_validate_json(v)
                              for k,v in snapshot.get('conditions',{}).items()})
    return (not actor['incapacitated'] and snapshot.get('current_hp',1)>0
            and not any(r.get('no_actions') for r in condition_rules(creature)))


def family_state(actor):
    return actor.setdefault('source_states',{}).setdefault(FAMILY,{})


def stamina_maximum(actor):
    return next((r['maximum'] for r in actor['bundle']['actor_template']['resources']
                 if r['resource_id']==STAMINA),0)


def restore_stamina(session,aid,amount,procedure):
    actor=session.state['actors'][aid];before=actor['resources'].get(STAMINA,0)
    actor['resources'][STAMINA]=min(stamina_maximum(actor),before+amount)
    session.emit('GORUDEN_STAMINA_RECOVERED',aid,source='tianxia.path.body_refining.stamina',
                 procedure=procedure,before=before,after=actor['resources'][STAMINA])


@hook('journey_options')
def native_body_options(session,aid):
    actor=session.state['actors'][aid]
    if session.state['phase']!='travel' or not owned(actor):return None
    state=actor.get('source_states',{}).get(FAMILY,{})
    pending=state.get('short_recovery_choice')
    if pending:
        want_recovery = actor['resources'].get(STAMINA,0) < stamina_maximum(actor)
        return [{'id':'goruden.short.'+str(v),'kind':'goruden_short_recovery','payload':{'recover':v},
                 'auto_select':int(bool(v) == want_recovery),
                 'label':label} for v,label in ((1,f"Recover up to {pending['amount']} Stamina from this Short Rest (twice per Long Rest)."),
                                               (0,'Decline Stamina recovery from this Short Rest.'))]
    if not able(actor):return None
    out=[];action=aura_action(actor)
    if not state.get('cultivation_used',0):
        out.append({'id':'goruden.cultivation','kind':'activity_start',
            'payload':{'source':CULTIVATION,'parameters':{}},'auto_select':0,
            'label':'Complete two uninterrupted hours of cultivation to restore all missing Stamina (once per Long Rest).'})
    return out


@hook('journey_command')
def native_body_command(session,aid,kind,payload):
    if kind not in ('goruden_aura','goruden_short_recovery'):return None
    actor=session.state['actors'][aid]
    require(owned(actor),'This creature has not acquired a Gōruden feature.')
    state=family_state(actor)
    if kind=='goruden_short_recovery':
        require(set(payload)=={'recover'} and type(payload['recover']) is int and payload['recover'] in (0,1),
                'Choose whether to recover Stamina from this Short Rest.')
        pending=state.get('short_recovery_choice')
        require(pending is not None and pending['rest']==actor.get('short_rests',0)
                and pending['long_rest']==actor['long_rests'] and state.get('short_recoveries',0)<2,
                'There is no current Short Rest recovery choice.')
        if payload['recover']:
            restore_stamina(session,aid,pending['amount'],'short_rest')
            state['short_recoveries']=state.get('short_recoveries',0)+1
        state.pop('short_recovery_choice',None)
        session.emit('GORUDEN_SHORT_RECOVERY_CHOSEN',aid,recover=payload['recover'])
        return True
    require(False,'Activate Golden Aura as a Bonus Action in a table scene, where its recipients and benefits resolve together.')


@hook('journey_before_command')
def pending_rest_choice(session,aid,kind,payload):
    actor=session.state['actors'][aid]
    pending=actor.get('source_states',{}).get(FAMILY,{}).get('short_recovery_choice')
    if pending and kind not in ('goruden_short_recovery','declare_fact','goruden_sheen','goruden_collect'):
        require(False,'Choose or decline the pending Short Rest Stamina recovery first.')


@hook('journey_short_rest')
def short_rest_offer(session,aid):
    actor=session.state['actors'][aid]
    if not owned(actor):return
    state=family_state(actor)
    if state.get('short_recoveries',0)>=2:return
    state['short_recovery_choice']={'amount':stamina_maximum(actor)//2,
        'rest':actor.get('short_rests',0),'long_rest':actor['long_rests']}
    session.emit('GORUDEN_SHORT_RECOVERY_OFFERED',aid,amount=stamina_maximum(actor)//2)


@hook('journey_rest')
def long_rest_recovery(session,aid):
    actor=session.state['actors'][aid]
    if not owned(actor):return
    state=family_state(actor)
    state['short_recoveries']=0;state['cultivation_used']=0
    state.pop('short_recovery_choice',None)
    restore_stamina(session,aid,stamina_maximum(actor),'long_rest')


@hook('activity_spec')
def cultivation_spec(session,aid,source,parameters):
    if source!=CULTIVATION:return None
    actor=session.state['actors'][aid]
    require(owned(actor) and able(actor) and not parameters
            and not actor.get('source_states',{}).get(FAMILY,{}).get('cultivation_used',0),
            'This full cultivation restoration is unavailable until a Long Rest.')
    return {'seconds':7200,'label':'two uninterrupted hours of full cultivation for Stamina recovery'}


@hook('activity_validate')
def cultivation_validate(session,aid,row):
    if row['source']==CULTIVATION:cultivation_spec(session,aid,row['source'],row['parameters'])


@hook('activity_finished')
def cultivation_finished(session,aid,row):
    if row['source']!=CULTIVATION:return
    cultivation_validate(session,aid,row)
    actor=session.state['actors'][aid]
    restore_stamina(session,aid,stamina_maximum(actor),'cultivation_session')
    family_state(actor)['cultivation_used']=1


# Source-owned native continuation. Model records are strings; direct state
# leaves remain integers/strings. Only actual committed family effects qualify.
def native_feature(engine,source,owner_id,subject_id):
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==owner_id),None)
    action=engine.action_catalog.get(source)
    feature=(action.parameters.get('typed') or {}).get('source') if action else source
    if bundle and feature in (FIST,PREFIX+'golden_aura',PREFIX+'immortal_gold') and owned({'bundle':bundle},feature):
        return feature
    carrier=next((b for b in engine.typed_bundle_documents if b['actor_id']==subject_id),{})
    for proof in carrier.get('goruden_continuation',{}).get('native',{}).get('sources',[]):
        if proof['source']==source and proof['owner']==owner_id:return proof['feature']
    return None


def native_parts(engine,creature):
    from .goruden import STATUE
    from ..zones import ZONE_EFFECT
    continuous={mid for c in creature.conditions.values() if c.condition_id==ZONE_EFFECT
                for mid in c.data.get('zone_modifiers',[])}
    result={'conditions':[],'modifiers':[],'zones':[],'sources':[]}
    def admit(source,owner):
        feature=native_feature(engine,source,owner,creature.entity_id)
        if feature:
            proof={'source':source,'owner':owner,'feature':feature}
            if feature in (FIST,PREFIX+'golden_aura'):
                anchor=owner if feature==FIST else creature.entity_id
                actual=engine.state.actors.get(anchor)
                if actual is not None:
                    entry=next((b.get('goruden_continuation',{}) for b in engine.typed_bundle_documents if b['actor_id']==anchor),{})
                    proof.update(turn_anchor=anchor,turn_deadline=entry.get('native_turns_total',0)+expiry_starts(actual)+1)
                else:
                    carrier=next((b for b in engine.typed_bundle_documents if b['actor_id']==creature.entity_id),{})
                    previous=next((p for p in carrier.get('goruden_continuation',{}).get('native',{}).get('sources',[])
                                   if p['source']==source and p['owner']==owner),{})
                    if 'turn_anchor' in previous:
                        proof.update(turn_anchor=previous['turn_anchor'],turn_deadline=previous['turn_deadline'])
            if proof not in result['sources']:result['sources'].append(proof)
        return feature
    now=Fraction(engine.state.round_number*6)
    for c in creature.conditions.values():
        feature=admit(c.source_definition_id,c.source_actor_id)
        if not feature or c.condition_id in (AURA_CHOICE,ZONE_EFFECT,FACT,'incapacitated'):continue
        deadline=c.data.get('goruden_carried_deadline')
        if deadline and now>=Fraction(deadline):continue
        if c.condition_id==STATUE or c.expires_on not in (None,'UNTIL_REMOVED'):
            result['conditions'].append(c.model_dump_json())
    for m in creature.modifiers.values():
        feature=admit(m.source_definition_id,m.source_actor_id)
        deadline=creature.turn_flags.get('_round_goruden_carried:'+m.modifier_id)
        if (not feature or m.modifier_id in continuous or m.consumed
                or deadline and now>=Fraction(deadline)):continue
        if feature==PREFIX+'immortal_gold' or m.expires_on not in (None,'UNTIL_REMOVED'):
            result['modifiers'].append(m.model_dump_json())
    for z in engine.state.zones.values():
        if (not z.active or z.trigger_profile.get('anchor_id')!=creature.entity_id
                or admit(z.source_definition_id,z.owner_id)!=FIST):continue
        deadline=z.trigger_profile.get('goruden_carried_deadline')
        if deadline and now>=Fraction(deadline):continue
        result['zones'].append(z.model_dump_json())
    return result if any(result[k] for k in ('conditions','modifiers','zones')) else None


def native_statue(payload):
    from .goruden import STATUE
    from ..gate2_runtime_models import ConditionInstance
    return any(ConditionInstance.model_validate_json(r).condition_id==STATUE
               for r in (payload or {}).get('conditions',[]))


def rebase_native_expiry(engine,name,owner,holder):
    from .effect_durations import parse,token
    parsed=parse(name)
    if parsed:
        edge,aid,_=parsed
        actor=engine.state.actors.get(aid)
        return token(edge,aid,actor.turns_started+1) if actor else 'START_OF_SLOT_AT:2:0'
    return name


def restore_native(engine,actor,payload):
    from ..gate2_runtime_models import ConditionInstance,ModifierInstance,ZoneState
    from .goruden import STATUE
    from .. import zones
    remaining=Fraction(payload['remaining_num'],payload['remaining_den'])
    if remaining<=0 and not native_statue(payload):return
    deadline=engine.state.round_number*6+remaining
    clock=f'{deadline.numerator}/{deadline.denominator}'
    proofs=payload.get('sources',[])
    def valid(source,owner):
        require(any(p['source']==source and p['owner']==owner and p['feature'] in
                    (FIST,PREFIX+'golden_aura',PREFIX+'immortal_gold') for p in proofs),
                'The carried golden effect has no committed source binding.')
        require(native_feature(engine,source,owner,actor.entity_id) is not None,
                'The carried golden effect is not source-owned.')
    for raw in payload.get('conditions',[]):
        c=ConditionInstance.model_validate_json(raw);valid(c.source_definition_id,c.source_actor_id)
        require(c.target_id==actor.entity_id,'The carried golden condition belongs to another creature.')
        data=deepcopy(c.data)
        if c.condition_id!=STATUE:data['goruden_carried_deadline']=clock
        engine._apply_condition(actor,c.condition_id,c.source_definition_id,c.source_actor_id,
            expires_on=rebase_native_expiry(engine,c.expires_on,c.source_actor_id,actor.entity_id),data=data)
    for raw in payload.get('modifiers',[]):
        m=ModifierInstance.model_validate_json(raw);valid(m.source_definition_id,m.source_actor_id)
        require(m.target_id==actor.entity_id and not m.consumed,'The carried golden modifier is not active on this creature.')
        mid=engine._add_modifier(actor,m.source_definition_id,m.target_field,m.operation,m.value,m.applies_to,
            expires_on=rebase_native_expiry(engine,m.expires_on,m.source_actor_id,actor.entity_id),
            source_actor_id=m.source_actor_id,application_id=m.application_id)
        if m.expires_on not in (None,'UNTIL_REMOVED'):
            actor.turn_flags['_round_goruden_carried:'+mid]=clock
    for raw in payload.get('zones',[]):
        z=ZoneState.model_validate_json(raw);valid(z.source_definition_id,z.owner_id)
        require(z.active and z.trigger_profile.get('anchor_id')==actor.entity_id,
                'The carried light is not anchored to this creature.')
        owner=engine.state.actors.get(z.owner_id)
        if owner:z.trigger_profile['start_of_owner_turn']=owner.turns_started+1
        else:z.trigger_profile.pop('start_of_owner_turn',None)
        z.trigger_profile['goruden_carried_deadline']=clock
        engine.state.zones[z.zone_id]=z
        engine._append_event('ZONE_CREATED',z.source_definition_id,actor_id=z.owner_id,
                             payload={'zone':z.model_dump(mode='json'),'continuation':1})
    # A carried light rides its target, not its source or its old scene square.
    # follow also reconciles membership after updating the stored geometry.
    zones.follow(engine,actor)


@hook('turn_start',priority=-99)
def expire_native_carried(engine,actor):
    from .condition_ownership import remove_instance
    from .. import zones
    now=Fraction(engine.state.round_number*6)
    for holder in engine.state.actors.values():
        for c in list(holder.conditions.values()):
            deadline=c.data.get('goruden_carried_deadline')
            if deadline and now>=Fraction(deadline):remove_instance(engine,holder,c.instance_id,c.source_definition_id)
        for mid,m in list(holder.modifiers.items()):
            key='_round_goruden_carried:'+mid;deadline=holder.turn_flags.get(key)
            if deadline and now>=Fraction(deadline):
                engine._remove_modifier_instance(holder,mid,m.source_definition_id)
                holder.turn_flags.pop(key,None)
    for z in list(engine.state.zones.values()):
        deadline=z.trigger_profile.get('goruden_carried_deadline')
        if z.active and deadline and now>=Fraction(deadline):zones.remove(engine,z,'DURATION_ENDED')


@hook('fight_setup_tasks')
def native_continuation_tasks(engine):
    # The ordinary setup transaction starts the first turn. This prevents a
    # restored Aura/statue from asking a human question in a constructor.
    out=[]
    for b in engine.typed_bundle_documents:
        saved=b.get('goruden_continuation',{});aid=b['actor_id']
        if saved.get('aura'):out.append({'actor_id':aid,'source_id':PREFIX+'golden_aura'})
        if native_statue(saved.get('native')):out.append({'actor_id':aid,'source_id':PREFIX+'immortal_gold'})
    return out


@hook('fight_setup')
def native_continuation_ready(engine,actor,source,intent):
    if source not in (PREFIX+'golden_aura',PREFIX+'immortal_gold'):return None
    return True


@hook('journey_native_scene')
def native_scene_interest(session,aid):
    if not any(owned(a) or a.get('source_states',{}).get(FAMILY,{}).get('native_effects')
               for a in session.state['actors'].values()):return None
    if any(a.get('source_states',{}).get(FAMILY,{}).get('short_recovery_choice')
           for a in session.state['actors'].values()):return False
    return True


@hook('journey_step')
def native_field_step(session,aid,old,nxt,regions):
    for other in session.state['actors']:
        projected=continuation_values(session,other)
        if projected and (projected[1].get('aura') or projected[1].get('native')):
            return {'native_scene_required':'Golden effects are active. Use a table scene for movement, recipient choices and their normal timing.'}


@hook('journey_before_command')
def statue_clock_requires_native_scene(session,aid,kind,payload):
    if kind in ('enter_combat','goruden_sheen','goruden_collect','declare_fact'):return
    if any(native_statue(a.get('source_states',{}).get(FAMILY,{}).get('native_effects'))
           for a in session.state['actors'].values()):
        require(False,'A golden statue reaches its next turn in a table scene; resolve its healing and free Aura there before advancing or finishing this journey.')


def live_native(session,native):
    """Drop carried effects whose real source/holder already took its next turn.

    Opaque source receipts come only from native_parts, not player declarations.
    Missing old receipts preserve old sealed policy; missing actors are not
    guessed to have acted. The existing elapsed clock still bounds that case.
    """
    expired=set()
    for proof in native.get('sources',[]):
        if 'turn_anchor' not in proof:continue
        require(type(proof.get('turn_deadline')) is int and proof['turn_deadline']>=0,
                'This carried golden effect has an invalid turn receipt.')
        anchor=session.state['actors'].get(proof['turn_anchor'])
        if anchor is not None and anchor.get('source_states',{}).get(FAMILY,{}).get('native_turns_total',0)>=proof['turn_deadline']:
            expired.add((proof['source'],proof['owner']))
    result=deepcopy(native)
    for kind in ('conditions','modifiers','zones'):
        rows=[]
        for raw in result.get(kind,[]):
            row=json.loads(raw)
            owner=row.get('owner_id') if kind=='zones' else row.get('source_actor_id')
            if (row['source_definition_id'],owner) not in expired:rows.append(raw)
        result[kind]=rows
    result['sources']=[p for p in result.get('sources',[]) if (p['source'],p['owner']) not in expired]
    return result if any(result[k] for k in ('conditions','modifiers','zones')) else None


def expiry_starts(actor):
    """Real source turns plus recognized omitted-slot starts; never recovery turns."""
    return actor.turns_started+int(actor.turn_flags.get('_round_goruden_nominal_expiry_starts',0))


@hook('nominal_slot_boundary')
def carried_expiry_slot(engine,actor,checkpoint):
    if checkpoint!='START_OF_TURN':return
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    saved=bundle.get('goruden_continuation',{})
    if 'native_turns_total' not in saved:return
    key='_round_goruden_nominal_expiry_starts'
    actor.turn_flags[key]=int(actor.turn_flags.get(key,0))+1
