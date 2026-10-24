"""Shared native scene, Body availability and paid-activation receipts.

Public consumers: nine_star and organ_furnaces. No family IDs occur here.
``body_mode_profiles(bundle)`` providers return source/feature_levels and optional
scene_resources. ``scene_record`` retains Source CL, scene and Initiative grant
identity independently for each source. ``available`` reads the effective-CL and
cultivation_suppression queries; absent replies retain compiled CL. A suppression
never erases anatomy, resources, selection, duration or spent scene allowances.
``paid_activation_resolved(engine, actor, receipt)`` is a strict notification from
real native payment and completion events, not from a caller supplied boolean.
Only positive net Stamina, exact source and event ancestry enter a receipt.
The original action/reaction is the sole payment authority. All data are JSON.

World facts reuse fact_consent_admission's trusted table-owner producer. Scene
end reuses JourneyStore.end_scene; no rest or combat reroll implies a new scene.
"""
from __future__ import annotations
from copy import deepcopy
from . import hook, query, run_strict

SCENE = 'condition:typed.body_scene'
SUPPRESSION = 'condition:typed.cultivation_suppression'
AUTHORITY = 'system:body_modes_scene_resources'
STAMINA = 'resource:core.stamina'


def bundle_of(engine, actor):
    return next((b for b in getattr(engine,'typed_bundle_documents',()) if b.get('actor_id')==actor.entity_id),{})


def profiles(bundle):
    return [p for reply in query('body_mode_profiles',bundle) for p in (reply or [])]


def turn_key(engine):
    # TURN_STARTED sequence distinguishes repeated/extra slots of the same actor.
    sequence=next((e.sequence for e in reversed(engine.events) if e.event_type=='TURN_STARTED'),0)
    return f'{engine.state.match_seed}:{engine.state.round_number}:{engine.state.current_actor_id}:{sequence}'


def unconscious(actor):
    return (not actor.active or actor.life_state in ('DYING','STABLE') or
            any(c.condition_id.rsplit('.',1)[-1] in ('unconscious','life_unconscious','dream_sleep') for c in actor.conditions.values()))


def effective_body_cl(engine,actor):
    bundle=bundle_of(engine,actor)
    base=int(bundle.get('body_mode_level',bundle.get('cl') or 1))
    replies=query('cultivation_effective_cl',engine,actor,'tianxia.path.body_refining')
    values=[v for v in replies if type(v) is int and v>=0]
    for c in actor.conditions.values():
        if c.condition_id==SUPPRESSION and c.data.get('system') in ('body','tianxia.path.body_refining','all') and type(c.data.get('effective_cl')) is int:
            values.append(c.data['effective_cl'])
    return min([base,*values])


def available(engine,actor,feature,level,*,requires_conscious=True):
    if actor is None or (requires_conscious and unconscious(actor)) or effective_body_cl(engine,actor)<level:return False
    if any(v is False for v in query('cultivation_feature_available',engine,actor,feature)):return False
    for c in actor.conditions.values():
        if c.condition_id!=SUPPRESSION:continue
        d=c.data
        if d.get('feature_id')==feature or (d.get('system') in ('body','all','tianxia.path.body_refining') and d.get('suppressed')==1):return False
    return True


def scene_record(engine,actor,source):
    return next((c for c in actor.conditions.values() if c.condition_id==SCENE and c.data.get('source')==source),None)


def set_record(engine,actor,source,data):
    old=scene_record(engine,actor,source)
    if old:engine._remove_condition_instance(actor,old.instance_id,source,expected=old)
    engine._apply_condition(actor,SCENE,source,actor.entity_id,expires_on='UNTIL_REMOVED',data=deepcopy(data))


@hook('match_start',priority=-200)
def initialize_scene(engine):
    for actor in engine.state.actors.values():
        bundle=bundle_of(engine,actor)
        transfer=bundle.get('body_modes_scene_resources') or {}
        for profile in profiles(bundle):
            source=profile['source']; old=scene_record(engine,actor,source)
            if old:continue
            data=deepcopy((transfer.get('records') or {}).get(source) or {})
            if not data:
                data={'source':source,'scene_id':'match:'+str(engine.state.match_seed),
                      'source_cl':effective_body_cl(engine,actor),'initiative':0,'label':profile['name']+' scene state'}
                for resource in profile.get('scene_resources',[]):
                    amount=int(actor.resources.get(resource,0))
                    if amount:engine._spend_resource(actor,resource,amount,source)
            set_record(engine,actor,source,data)


def paid_receipt(engine,actor,source,stop):
    from .ability_source import mechanic_at
    canonical=mechanic_at(engine,source) or source
    events=[]
    for event in reversed(engine.events):
        if event.event_type==stop and (stop=='REACTION_WINDOW_OPENED' or event.actor_id==actor.entity_id):break
        events.append(event)
    paid=[e for e in events if e.event_type=='RESOURCE_SPENT' and e.actor_id==actor.entity_id
          and e.payload.get('resource_id')==STAMINA and (mechanic_at(engine,e.source_definition_id) or e.source_definition_id)==canonical
          and int(e.payload.get('amount') or 0)>0]
    refunds=sum(int(e.payload.get('gained') or e.payload.get('amount') or 0) for e in events if e.event_type=='RESOURCE_GAINED' and e.actor_id==actor.entity_id
                and e.payload.get('resource_id')==STAMINA and (mechanic_at(engine,e.source_definition_id) or e.source_definition_id)==canonical)
    amount=sum(int(e.payload['amount']) for e in paid)-refunds
    if amount<=0:return None
    return {'source':canonical,'paid':amount,'payment_sequences':sorted(e.sequence for e in paid),
            'completion_sequence':engine.state.event_sequence,'turn':turn_key(engine),'round':int(engine.state.round_number),'source_cl':effective_body_cl(engine,actor)}


def notify_paid(engine,actor,source,stop):
    if not profiles(bundle_of(engine,actor)):return
    receipt=paid_receipt(engine,actor,source,stop)
    if receipt:
        run_strict('paid_activation_resolved',engine,actor,receipt)


@hook('action_completed',priority=90)
def completed(engine,actor,economy,source):
    notify_paid(engine,actor,source,'INTENT_ACCEPTED')


@hook('state_event')
def completed_reaction(engine,event):
    if event.event_type!='REACTION_RESOLVED':return
    actor=engine.state.actors.get(event.actor_id)
    if actor is not None:notify_paid(engine,actor,event.source_definition_id,'REACTION_WINDOW_OPENED')


@hook('fact_admission_schema')
def world_schema(session,source,subject,kind):
    if source!=AUTHORITY or not profiles(session.state['actors'][subject]['bundle']):return
    if kind not in ('cultivation_suppression','qualified_source'):return
    return {'value_type':'document','maximum_seconds':86400,'authority':'table_owner',
            'description':'A printed source rule, authority and explicit scope for this Body scene.'}


@hook('journey_command')
def accept_world_state(session,aid,kind,payload):
    if kind!='body_source_state':return
    from ..journey import require,integer
    from ..fact_consent_admission import read
    require(set(payload)=={'scope','kind'},'Choose a declared source record and its kind.')
    fact=read(session,AUTHORITY,aid,payload['kind'],payload['scope'],aid)
    require(fact is not None,'The table owner must first record this source and its authority.')
    value=fact['value']
    require(type(value.get('source_rule')) is str and bool(value['source_rule'].strip()) and integer(value.get('source_cl')),
            'A source rule and explicit Source CL are required.')
    if payload['kind']=='cultivation_suppression':
        require(value.get('system') in ('body','tianxia.path.body_refining','all') and
                (integer(value.get('effective_cl')) or value.get('suppressed')==1 or type(value.get('feature_id')) is str),
                'Name complete Body suppression, an effective CL limit or a specific feature.')
    elif payload['kind']=='qualified_source':
        require(value.get('source_actor_id') in session.state['actors'] and value.get('hostile') in (0,1)
                and value.get('staged') in (0,1),'Record the actual source, hostility and staged-interaction facts.')
    elif payload['kind']=='breathing_exposure':
        require(value.get('no_air') in (0,1),'Record whether breathable air is actually unavailable.')
    else:
        raise ValueError('Unsupported Body source record.')
    held=session.state['actors'][aid].setdefault('source_states',{}).setdefault(AUTHORITY,{}).setdefault('sources',{})
    held[payload['kind']+':'+payload['scope']]={'scope':payload['scope'],'kind':payload['kind'],'value':deepcopy(value),'receipt_id':fact['receipt_id'],'expires_at':fact['expires_at']}
    session.emit('BODY_SOURCE_ADMITTED',aid,receipt_id=fact['receipt_id'],kind_name=payload['kind'],scope=payload['scope'])
    run_strict('journey_state_changed',session,aid)
    return True


@hook('journey_initialize')
def journey_initialize(session,aid):
    actor=session.state['actors'][aid]; ps=profiles(actor['bundle'])
    if not ps:return
    records=actor.setdefault('source_states',{}).setdefault(AUTHORITY,{}).setdefault('records',{})
    for p in ps:
        if p['source'] in records:continue
        records[p['source']]={'source':p['source'],'scene_id':session.state.get('scene_id',session.state['journey_id']),
            'source_cl':int(actor['bundle'].get('cl') or 1),'initiative':0,'label':p['name']+' scene state'}
        for resource in p.get('scene_resources',[]):actor['resources'][resource]=0


@hook('journey_scene_end')
def journey_scene_end(session,previous,current):
    for aid,actor in session.state['actors'].items():
        for p in profiles(actor['bundle']):
            actor.setdefault('source_states',{}).setdefault(AUTHORITY,{}).setdefault('records',{})[p['source']]={'source':p['source'],'scene_id':current,
                'source_cl':int(actor['bundle'].get('cl') or 1),'initiative':0,'label':p['name']+' scene state'}
            for resource in p.get('scene_resources',[]):actor['resources'][resource]=0
            for resource in p.get('scene_limits',[]):actor['resources'][resource]=1
        actor.get('source_states',{}).get(AUTHORITY,{}).pop('scene_limits',None)
        run_strict('body_scene_ended',session,aid,previous,current)


@hook('journey_combat_bundle')
def journey_to_combat(bundle,session,aid):
    actor=session.state['actors'][aid]
    if not profiles(bundle):return
    bundle['body_modes_scene_resources']={'records':deepcopy(actor.get('source_states',{}).get(AUTHORITY,{}).get('records',{})),
        'source_states':deepcopy(actor.get('source_states',{}).get(AUTHORITY,{}).get('sources',{})),
        'clock_num':session.clock().numerator,'clock_den':session.clock().denominator}


@hook('match_start',priority=-190)
def bind_world_sources(engine):
    from fractions import Fraction
    for actor in engine.state.actors.values():
        transfer=bundle_of(engine,actor).get('body_modes_scene_resources') or {}
        now=Fraction(transfer.get('clock_num',transfer.get('seconds',0)),transfer.get('clock_den',1))
        for scope,record in transfer.get('source_states',{}).items():
            remaining=record['expires_at']-now
            if remaining<=0:continue
            value=deepcopy(record['value'])
            engine._apply_condition(actor,SUPPRESSION if record['kind']=='cultivation_suppression' else 'condition:typed.qualified_body_source',AUTHORITY,actor.entity_id,expires_on='UNTIL_REMOVED',
                data={**value,'kind':record['kind'],'receipt_id':record['receipt_id'],'scope':record.get('scope',scope),
                      'label':{'cultivation_suppression':'Recorded cultivation suppression','qualified_source':'Recorded source authority and hostility','breathing_exposure':'Recorded breathing hazard'}[record['kind']],
                      'body_expires_num':remaining.numerator,'body_expires_den':remaining.denominator,
                      'body_created_round':engine.state.round_number,'body_created_slot':engine.state.current_slot_index})


@hook('turn_start',priority=-200)
def source_clock(engine,actor):
    from fractions import Fraction
    slots=max(1,len(engine.state.initiative_order))
    for subject in engine.state.actors.values():
        for c in list(subject.conditions.values()):
            if 'body_expires_num' not in c.data:continue
            elapsed=Fraction(((engine.state.round_number-c.data['body_created_round'])*slots+engine.state.current_slot_index-c.data['body_created_slot'])*6,slots)
            if elapsed>=Fraction(c.data['body_expires_num'],c.data['body_expires_den']):
                engine._remove_condition_instance(subject,c.instance_id,AUTHORITY,expected=c)


def setting_action(info,source,key,name,effect,description,*,batch=True):
    """Owned free self setting; same typed effect in table and settings batches."""
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.{key}",display_name=name,
        owner_id=info['actor_id'],economy=EconomyKind.NONE,resolution_kind='TYPED',target_kind='SELF',
        parameters={'setting_only':True,'player_only':True,'expected_damage':0,'body_mode_source':source,
            'body_setting_batch':int(batch),'setting_description':description,
            'typed':{'source':source,'effects':[effect],'numbers':info['numbers'],'duration':{'kind':'instant'},'riders':[]}})


@hook('settings_batch_key')
def setting_key(action):
    if not action.parameters.get('body_setting_batch'):return
    return action.parameters['body_mode_source']+':'+action.parameters['typed']['effects'][0]['type']


@hook('candidate_allowed')
def gate_owned_modes(engine,actor,candidate,action):
    if action is None:return
    source=action.parameters.get('body_mode_source')
    typed=action.parameters.get('typed') or {}
    from .ability_source import mechanic_of
    source=source or mechanic_of(action)
    ps=profiles(bundle_of(engine,actor))
    if ps and source.startswith(('tianxia.path.body_refining.','tianxia.subpath.body.')) and not available(engine,actor,source,bundle_of(engine,actor).get('body_feature_levels',{}).get(source,0)):return False
    for profile in ps:
        level=profile.get('feature_levels',{}).get(source)
        if level is not None and not available(engine,actor,source,level):return False


@hook('reaction_rows')
def gate_reactions(engine,actor_id,block,rows):
    actor=engine.state.actors[actor_id]
    levels={**bundle_of(engine,actor).get('body_feature_levels',{}),**{f:n for p in profiles(bundle_of(engine,actor)) for f,n in p.get('feature_levels',{}).items()}}
    if not levels:return
    return [r for r in rows if (not str(r.get('feature_id') or '').startswith(('tianxia.path.body_refining.','tianxia.subpath.body.')) or available(engine,actor,r['feature_id'],levels.get(r['feature_id'],0)))]


def source_matches(source,profile):
    """A catalog transport id may wrap a feature, never match another family."""
    return any(source==f or source.endswith('.'+f) for f in profile.get('feature_levels',{}))


def remaining_seconds(engine,expiry):
    """Exact round/slot deadline expressed as an integer fraction."""
    from fractions import Fraction
    if not expiry or expiry=='UNTIL_REMOVED':return None
    if expiry.startswith('START_OF_SLOT_AT:'):
        r,s=map(int,expiry.removeprefix('START_OF_SLOT_AT:').split(':'))
        slots=max(1,len(engine.state.initiative_order))
        return max(Fraction(0),Fraction(((r-engine.state.round_number)*slots+s-engine.state.current_slot_index)*6,slots))
    # Turn-bound riders expire at the next ordinary six-second boundary outside
    # turn play; they do not become permanent during an uncounted interval.
    return Fraction(6)


@hook('journey_snapshot_actor')
def snapshot_managed(actor,session,aid,engine):
    ps=profiles(bundle_of(engine,actor))
    if not ps:return
    clone=actor.model_copy(deep=True)
    clone.conditions={k:c for k,c in clone.conditions.items() if c.condition_id not in (SCENE,SUPPRESSION)
        and not any(source_matches(c.source_definition_id,p) for p in ps)}
    return clone


@hook('journey_encounter_settled')
def export_managed(session,aid,engine,creature):
    ps=profiles(bundle_of(engine,creature))
    if not ps:return
    actor=session.state['actors'][aid]
    state=actor.setdefault('source_states',{}).setdefault(AUTHORITY,{})
    state['records']={p['source']:deepcopy(scene_record(engine,creature,p['source']).data) for p in ps if scene_record(engine,creature,p['source'])}
    items=[]
    for kind,collection in (('condition',creature.conditions),):
        for item in collection.values():
            if kind=='condition' and item.condition_id in (SCENE,SUPPRESSION):continue
            if not any(source_matches(item.source_definition_id,p) for p in ps):continue
            if kind=='condition' and any(item.condition_id in p.get('separate_conditions',[]) for p in ps):continue
            duration=remaining_seconds(engine,item.expires_on)
            if duration is not None and duration<=0:continue
            row={'kind':kind,'model':item.model_dump_json()}
            if duration is not None:row.update(remaining_num=duration.numerator,remaining_den=duration.denominator)
            items.append(row)
    state['effects']=items
    # Preserve exact scene-limited counters, without restoring general pools.
    scene_limits={r for p in ps for r in p.get('scene_limits',[])}
    state['scene_limits']={r:int(creature.resources.get(r,0)) for r in scene_limits}


@hook('journey_elapsed')
def elapse_managed(session,aid,before,seconds,moving):
    from fractions import Fraction
    state=session.state['actors'][aid].get('source_states',{}).get(AUTHORITY)
    if not state:return
    keep=[]
    for row in state.get('effects',[]):
        if 'remaining_num' in row:
            remaining=Fraction(row['remaining_num'],row['remaining_den'])-seconds
            if remaining<=0:continue
            row.update(remaining_num=remaining.numerator,remaining_den=remaining.denominator)
        keep.append(row)
    state['effects']=keep


@hook('journey_combat_bundle',priority=100)
def transfer_managed(bundle,session,aid):
    state=session.state['actors'][aid].get('source_states',{}).get(AUTHORITY)
    if not state:return
    bundle.setdefault('body_modes_scene_resources',{})['effects']=deepcopy(state.get('effects',[]))
    balances=state.get('scene_limits',{})
    for pool in bundle['actor_template']['resources']:
        if pool['resource_id'] in balances:pool['initial']=balances[pool['resource_id']]


@hook('match_start',priority=-180)
def restore_managed(engine):
    import json
    from ..gate2_runtime_models import ConditionInstance,ModifierInstance
    for actor in engine.state.actors.values():
        transfer=bundle_of(engine,actor).get('body_modes_scene_resources',{})
        for item in transfer.get('effects',[]):
            model=json.loads(item['model'])
            # New application receives an engine-issued identity and event.
            if item['kind']=='condition':
                if 'remaining_num' in item:
                    model['data'].update(body_timer_num=item['remaining_num'],body_timer_den=item['remaining_den'],
                        body_timer_round=engine.state.round_number,body_timer_slot=engine.state.current_slot_index)
                engine._apply_condition(actor,model['condition_id'],model['source_definition_id'],model['source_actor_id'],
                    expires_on='UNTIL_REMOVED',data=model['data'])
            # Source families currently use dynamic benefit readers, rather
            # than extending expiring stat modifiers into an encounter.


@hook('turn_start',priority=-195)
def managed_round_clock(engine,actor):
    from fractions import Fraction
    slots=max(1,len(engine.state.initiative_order))
    for subject in engine.state.actors.values():
        for c in list(subject.conditions.values()):
            d=c.data
            if 'body_timer_num' not in d:continue
            elapsed=Fraction(((engine.state.round_number-d['body_timer_round'])*slots+engine.state.current_slot_index-d['body_timer_slot'])*6,slots)
            if elapsed>=Fraction(d['body_timer_num'],d['body_timer_den']):
                engine._remove_condition_instance(subject,c.instance_id,c.source_definition_id,expected=c)


def journey_available(session,aid,feature,level,*,requires_conscious=True,at=None):
    actor=session.state['actors'][aid]
    if requires_conscious and actor['incapacitated']:return False
    cl=int(actor['bundle'].get('body_mode_level',actor['bundle'].get('cl') or 1))
    for record in actor.get('source_states',{}).get(AUTHORITY,{}).get('sources',{}).values():
        if record['expires_at']<=(session.clock() if at is None else at) or record['kind']!='cultivation_suppression':continue
        value=record['value']
        if value.get('feature_id')==feature:return False
        if value.get('system') in ('body','all','tianxia.path.body_refining'):
            if value.get('suppressed')==1:return False
            cl=min(cl,int(value.get('effective_cl',cl)))
    return cl>=level


def qualifying_activation(engine,actor,receipt,scene_source):
    """Reject declared staged/controlled resource farms and repeated nonhostile uses.

    Hostility is a native relation fact; staging is a trusted
    world declaration, never inferred from a creature's name or inactivity.
    A first nonhostile resolved activation can light one point. Repeating that
    nonhostile activation cannot farm later round triggers in the same scene.
    """
    from ..relations import relation,ENEMY
    source=receipt['source']; payments=set(receipt['payment_sequences'])
    start=min(payments)
    opposition=[]
    for event in engine.events:
        if event.sequence<start or event.sequence>receipt['completion_sequence']:continue
        for aid in ((event.actor_id,) if event.actor_id!=actor.entity_id else event.target_ids):
            other=engine.state.actors.get(aid)
            if other is not None and other is not actor and relation(engine,actor,other)==ENEMY:
                opposition.append(other)
    from ..pending_damage import current
    packet=current(engine)
    if packet is not None and packet.target_id==actor.entity_id and packet.source_actor_id in engine.state.actors:
        opposition.append(engine.state.actors[packet.source_actor_id])
    declarations=[c.data for c in actor.conditions.values() if c.condition_id=='condition:typed.qualified_body_source' and c.data.get('kind')=='qualified_source']
    disqualified=False
    for other in opposition:
        declared=[d for d in declarations if d.get('source_actor_id')==other.entity_id]
        if any(d.get('staged')==1 or d.get('hostile')==0 for d in declared):
            disqualified=True
            continue
        controllers={actor.entity_id}|({actor.owner_id} if actor.owner_id else set())
        if other.summon is not None and other.owner_id in controllers:continue
        # Marks do not print the separate 'qualifying hostile creature' CL
        # threshold. A real hostile low-CL source remains a legal trigger.
        return True
    if disqualified:return False
    record=next((c for c in actor.conditions.values() if c.condition_id==SCENE and c.data.get('source')==scene_source),None)
    if record is None:return False
    prior=set(record.data.get('nonhostile_sources') or [])
    if source in prior:return False
    set_record(engine,actor,record.data['source'],{**record.data,'nonhostile_sources':sorted(prior|{source})})
    return True


@hook('path_rider_rows')
def gate_path_riders(engine,actor,kind,rows):
    levels={**bundle_of(engine,actor).get('body_feature_levels',{}),**{f:n for p in profiles(bundle_of(engine,actor)) for f,n in p.get('feature_levels',{}).items()}}
    if levels:return [r for r in rows if (not str(r.get('feature_id') or '').startswith(('tianxia.path.body_refining.','tianxia.subpath.body.')) or available(engine,actor,r['feature_id'],levels.get(r['feature_id'],0)))]


@hook('state_event')
def scene_limit_payment(engine,event):
    if event.event_type!='RESOURCE_SPENT':return
    actor=engine.state.actors.get(event.actor_id)
    if actor is None:return
    resource=event.payload.get('resource_id')
    for p in profiles(bundle_of(engine,actor)):
        if resource not in p.get('scene_limits',[]):continue
        record=scene_record(engine,actor,p['source'])
        if record:
            balances={**record.data.get('scene_limits',{}),resource:int(actor.resources.get(resource,0))}
            set_record(engine,actor,p['source'],{**record.data,'scene_limits':balances})


@hook('journey_combat_bundle',priority=110)
def bind_scene_limits(bundle,session,aid):
    state=session.state['actors'][aid].get('source_states',{}).get(AUTHORITY,{})
    balances={k:v for r in state.get('records',{}).values() for k,v in r.get('scene_limits',{}).items()}
    for pool in bundle['actor_template']['resources']:
        if pool['resource_id'] in balances:pool['initial']=balances[pool['resource_id']]


@hook('journey_options')
def admitted_source_options(session,aid):
    from ..fact_consent_admission import read
    out=[]
    for fact in session.state.get('fact_consent_admission',[]):
        if fact['source']!=AUTHORITY or fact['subject']!=aid:continue
        if fact['kind'] not in ('cultivation_suppression','qualified_source','breathing_exposure'):continue
        current=read(session,AUTHORITY,aid,fact['kind'],fact['scope'],aid)
        if current is None or current['receipt_id']!=fact['receipt_id']:continue
        label={'cultivation_suppression':'cultivation suppression','qualified_source':'hostile-source authority','breathing_exposure':'breathing hazard'}[fact['kind']]
        out.append({'id':'body-source:'+fact['receipt_id'],'kind':'body_source_state',
            'payload':{'scope':fact['scope'],'kind':fact['kind']},'label':session.state['actors'][aid]['name']+': apply the table owner’s recorded '+label+'; its source and expiry remain unchanged.'})
    return out or None


@hook('journey_encounter_clock')
def encounter_clock(session,engine):
    return True if any(profiles(bundle_of(engine,a)) for a in engine.state.actors.values()) else None


def complete_journey_activation(session,aid,source,event_start):
    """Native journey completion adapter; derive payment from committed events.

    Source callers invoke only after their effect resolves. This is the journey
    adapter for upstream activation settlement, not a supplied payment receipt.
    The owned compiled action and its actual resource events are both required.
    """
    from ..journey import require
    actor=session.state['actors'][aid]
    owned=any((a.get('parameters',{}).get('typed') or {}).get('source')==source for a in actor['bundle'].get('action_catalog',[]))
    require(owned,'A journey activation must resolve an actually acquired source.')
    events=session.state['events'][event_start:]
    paid=sum(int(e.get('amount',0)) for e in events if e['kind']=='RESOURCE_SPENT' and e['actor_id']==aid and e.get('source')==source and e.get('resource_id')==STAMINA)
    refunded=sum(int(e.get('amount',0)) for e in events if e['kind']=='RESOURCE_GAINED' and e['actor_id']==aid and e.get('source')==source and e.get('resource_id')==STAMINA)
    if paid<=refunded:return
    receipt={'source':source,'paid':paid-refunded,'round':int(session.clock())//6,'completion_event':len(session.state['events'])}
    session.emit('ACTIVATION_RESOLVED',aid,source=source,paid_stamina=paid-refunded)
    run_strict('journey_paid_activation_resolved',session,aid,receipt)


def effective_body_pb(engine,actor):
    base=int(actor.proficiency_bonus or 2)
    bundle=bundle_of(engine,actor)
    compiled=int(bundle.get('body_mode_level',bundle.get('cl') or 1))
    effective=effective_body_cl(engine,actor)
    return min(base,2+(max(1,effective)-1)//4) if effective<compiled else base


@hook('resolution_numbers')
def body_resolution_numbers(ctx,numbers):
    if not profiles(bundle_of(ctx.engine,ctx.actor)):return
    from .ability_source import mechanic_of
    source=mechanic_of(ctx.action)
    if not source.startswith(('tianxia.path.body_refining.','tianxia.subpath.body.')):return
    level=effective_body_cl(ctx.engine,ctx.actor);pb=effective_body_pb(ctx.engine,ctx.actor)
    compiled_pb=int(numbers.get('pb') or ctx.actor.proficiency_bonus or 2)
    if level==int(numbers.get('cl') or level) and pb==compiled_pb:return
    result={**numbers,'cl':level,'pb':pb}
    for key in ('save_dc','attack_bonus'):
        if key in result:result[key]=int(result[key])-compiled_pb+pb
    return result


@hook('compile_bundle')
def seal_body_level(bundle,info):
    if not profiles(bundle):return
    sheet=info.get('owner_sheet') or {}
    rows=(sheet.get('path_and_subpath') or {}).get('paths') or []
    if isinstance(rows,dict):rows=list(rows.values())
    body=next((r for r in rows if isinstance(r,dict) and r.get('path_id')=='tianxia.path.body_refining'),None)
    if body is None:return
    level=next((body[key] for key in ('effective_cl','attainment','owning_path_level') if type(body.get(key)) is int and body[key]>=0),None)
    levels={r['feature_id']:r['required_path_level'] for r in (sheet.get('path_and_subpath') or {}).get('earned_feature_occurrences',[])
            if r.get('owning_path_id')=='tianxia.path.body_refining' and r.get('source_backed') is True and type(r.get('required_path_level')) is int}
    return {**bundle,**({'body_mode_level':min(level, int(bundle.get('cl') or 1))} if level is not None else {}),'body_feature_levels':levels}


def constitution_modifier(engine,actor):
    """CON from the owner's sealed compiled statistics, never a save total."""
    for action in engine.action_catalog.values():
        if action.owner_id!=actor.entity_id:continue
        numbers=(action.parameters.get('typed') or {}).get('numbers') or {}
        if type(numbers.get('con_mod')) is int:return numbers['con_mod']
    return 0


@hook('fact_admission_validate')
def validate_body_fact(session,source,subject,kind,scope,value):
    if source!=AUTHORITY or kind not in ('cultivation_suppression','qualified_source','breathing_exposure'):return
    from ..journey import require,integer
    require(type(value.get('source_rule')) is str and bool(value['source_rule'].strip()) and integer(value.get('source_cl')),
            'Record a printed source rule and its explicit Source CL.')
    if kind=='cultivation_suppression':
        require(value.get('system') in ('body','tianxia.path.body_refining','all') and
                (integer(value.get('effective_cl')) or value.get('suppressed')==1 or type(value.get('feature_id')) is str),
                'Name complete Body suppression, an effective CL limit or a specific feature.')
    elif kind=='qualified_source':
        require(value.get('source_actor_id') in session.state['actors'] and value.get('hostile') in (0,1)
                and value.get('staged') in (0,1),'Name the actual source, hostility and staged-interaction facts.')
    else:require(value.get('no_air') in (0,1),'Record actual breathable-air availability.')
    return True


@hook('state_event')
def combat_source_input(engine,event):
    if event.event_type!='WORLD_FACT_DECLARED' or event.source_definition_id!=AUTHORITY:return
    from ..combat_world_facts import records,clock
    from fractions import Fraction
    record=next(r for r in records(engine) if r['receipt_id']==event.payload['receipt_id'])
    actor=engine.state.actors[record['subject']]
    for c in list(actor.conditions.values()):
        if c.source_definition_id==AUTHORITY and c.data.get('scope')==record['scope'] and c.data.get('kind')==record['kind']:
            engine._remove_condition_instance(actor,c.instance_id,AUTHORITY,expected=c)
    remaining=record['expires_at']-clock(engine)
    engine._apply_condition(actor,SUPPRESSION if record['kind']=='cultivation_suppression' else 'condition:typed.qualified_body_source',AUTHORITY,actor.entity_id,
        expires_on='UNTIL_REMOVED',data={**deepcopy(record['value']),'kind':record['kind'],'scope':record['scope'],'receipt_id':record['receipt_id'],
        'label':'Recorded Body source state','body_expires_num':remaining.numerator,'body_expires_den':remaining.denominator,
        'body_created_round':engine.state.round_number,'body_created_slot':engine.state.current_slot_index})


@hook('presentation_hidden_conditions')
def private_source_details(engine,actor):
    return [c.instance_id for c in actor.conditions.values() if c.source_definition_id==AUTHORITY and c.condition_id in (SUPPRESSION,'condition:typed.qualified_body_source')]


@hook('journey_encounter_settled',priority=100)
def export_body_source_inputs(session,aid,engine,actor):
    from ..combat_world_facts import records
    rows=[r for r in records(engine) if r['source']==AUTHORITY and r['subject']==aid]
    if not rows:return
    state=session.state['actors'][aid].setdefault('source_states',{}).setdefault(AUTHORITY,{})
    for r in rows:
        state.setdefault('sources',{})[r['kind']+':'+r['scope']]={'scope':r['scope'],'kind':r['kind'],'value':deepcopy(r['value']),'receipt_id':r['receipt_id'],'expires_at':r['expires_at']}


@hook('path_rider_turn_key')
def body_rider_turn_identity(engine,actor,row):
    if any(row.get('feature_id') in p.get('feature_levels',{}) for p in profiles(bundle_of(engine,actor))):
        return turn_key(engine)


def queue_journey_choice(session,aid,source,kind,data):
    """Queue an earned source operation; only completed native callers use this."""
    from ..journey import require
    actor=session.state['actors'][aid]
    require(feature_owned(actor['bundle'],source) and any(source in p.get('feature_levels',{}) for p in profiles(actor['bundle'])), 'The source must be an acquired Body mode.')
    state=actor.setdefault('source_states',{}).setdefault(AUTHORITY,{})
    state.setdefault('pending',[]).append({'source':source,'kind':kind,'data':deepcopy(data)})
    session.emit('BODY_CHOICE_QUEUED',aid,source=source,choice_kind=kind)


@hook('journey_pending_options')
def pending_journey_menu(session,aid):
    pending=session.state['actors'][aid].get('source_states',{}).get(AUTHORITY,{}).get('pending',[])
    if not pending:return
    rows=[r for reply in run_strict('body_journey_choice_options',session,aid,pending[0]) for r in (reply or [])]
    if not rows:raise ValueError('The earned Body choice has no source consumer.')
    return rows


@hook('journey_before_command')
def finish_earned_body_choice(session,aid,kind,payload):
    from ..journey import require
    for owner,actor in session.state['actors'].items():
        if actor.get('source_states',{}).get(AUTHORITY,{}).get('pending'):
            require(owner==aid and kind=='body_mode_choice','Finish '+actor['name']+'’s earned Body choice before advancing this scene.')


@hook('journey_auto_blocked')
def pending_human_body_choice(session,aid):
    return True if any(other!=aid and actor['control_mode']=='MANUAL' and actor.get('source_states',{}).get(AUTHORITY,{}).get('pending')
                       for other,actor in session.state['actors'].items()) else None


@hook('journey_command')
def resolve_journey_body_choice(session,aid,kind,payload):
    if kind!='body_mode_choice':return
    from ..journey import require
    require(set(payload)=={'choice','parameters'} and type(payload['choice']) is str and isinstance(payload['parameters'],dict),
            'Choose one earned Body operation and its parameters.')
    pending=session.state['actors'][aid].get('source_states',{}).get(AUTHORITY,{}).get('pending',[])
    require(pending,'This creature has no pending Body operation.')
    replies=run_strict('body_journey_choice_resolve',session,aid,pending[0],payload['choice'],payload['parameters'])
    require(sum(r is True for r in replies)==1,'Choose one operation offered by this source.')
    row=pending.pop(0)
    session.emit('BODY_CHOICE_RESOLVED',aid,source=row['source'],choice_kind=row['kind'],choice=payload['choice'])
    run_strict('journey_state_changed',session,aid)
    return True


def journey_health(session,aid):
    """Persisted native encounter health, or the admitted sheet's full health."""
    actor=session.state['actors'][aid];maximum=actor['bundle']['actor_template']['maximum_hp']
    return actor.setdefault('encounter_snapshot',{'current_hp':maximum,'maximum_hp':maximum,'temporary_hp':0,'active':1,'life_state':'','conditions':{}})


def feature_owned(bundle,feature):
    return (any(r.get('feature_id')==feature for key in ('typed_passives','typed_reactions') for r in bundle.get(key,())) or
            any(((a.get('parameters') or {}).get('typed') or {}).get('source')==feature for a in bundle.get('action_catalog',())))


def journey_body_cl(session,aid,*,at=None):
    actor=session.state['actors'][aid]
    level=int(actor['bundle'].get('body_mode_level',actor['bundle'].get('cl') or 1))
    for row in actor.get('source_states',{}).get(AUTHORITY,{}).get('sources',{}).values():
        if row['kind']!='cultivation_suppression' or row['expires_at']<=(session.clock() if at is None else at):continue
        value=row['value']
        if value.get('system') in ('body','all','tianxia.path.body_refining'):
            if value.get('suppressed')==1:return 0
            level=min(level,int(value.get('effective_cl',level)))
    return level


def journey_body_pb(session,aid):
    actor=session.state['actors'][aid];base=int(actor['bundle']['actor_template']['proficiency_bonus'])
    compiled=int(actor['bundle'].get('body_mode_level',actor['bundle'].get('cl') or 1));level=journey_body_cl(session,aid)
    return min(base,2+(max(1,level)-1)//4) if level<compiled else base
