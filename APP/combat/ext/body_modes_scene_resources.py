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


def source_deadline(record):
    from fractions import Fraction
    return Fraction(record['deadline_num'],record['deadline_den']) if 'deadline_num' in record else Fraction(record['expires_at'])


def bundle_of(engine, actor):
    return next((b for b in getattr(engine,'typed_bundle_documents',()) if b.get('actor_id')==actor.entity_id),{})


def profiles(bundle):
    return [p for reply in query('body_mode_profiles',bundle) for p in (reply or [])]


def turn_key(engine):
    # TURN_STARTED sequence distinguishes repeated/extra slots of the same actor.
    sequence=next((e.sequence for e in reversed(engine.events) if e.event_type=='TURN_STARTED'),0)
    return f'{engine.state.round_number}:{engine.state.current_actor_id}:{sequence}'


def unconscious(actor):
    return (not actor.active or actor.life_state in ('DYING','STABLE') or
            any(c.condition_id.rsplit('.',1)[-1] in ('unconscious','life_unconscious','dream_sleep') for c in actor.conditions.values()))


def effective_body_cl(engine,actor):
    base=int(bundle_of(engine,actor).get('cl') or 1)
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
            'completion_sequence':engine.state.event_sequence,'turn':turn_key(engine),'round':int(engine.state.round_number)}


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
    if kind not in ('cultivation_suppression','qualified_source','recovery_interruption'):return
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
        if 'disable_embodied_traits' in value:
            require(type(value['disable_embodied_traits']) is int and value['disable_embodied_traits'] in (0,1),
                    'An explicit source rule must state whether embodied traits are suppressed.')
        require(value.get('system') in ('body','tianxia.path.body_refining','all') and
                (integer(value.get('effective_cl')) or value.get('suppressed')==1 or type(value.get('feature_id')) is str),
                'Name complete Body suppression, an effective CL limit or a specific feature.')
    elif payload['kind']=='qualified_source':
        require(value.get('source_actor_id') in session.state['actors'] and value.get('hostile') in (0,1)
                and value.get('staged') in (0,1),'Record the actual source, hostility and staged-interaction facts.')
    elif payload['kind']=='recovery_interruption':
        require(value.get('interrupted')==1 and type(value.get('reason')) is str and bool(value['reason'].strip()),
                'Record the actual interruption and its reason.')
    elif payload['kind']=='breathing_exposure':
        require(value.get('no_air') in (0,1),'Record whether breathable air is actually unavailable.')
    else:
        raise ValueError('Unsupported Body source record.')
    held=session.state['actors'][aid].setdefault('source_states',{}).setdefault(AUTHORITY,{}).setdefault('sources',{})
    held[payload['scope']]={'kind':payload['kind'],'value':deepcopy(value),'receipt_id':fact['receipt_id'],'expires_at':fact['expires_at']}
    remaining=source_deadline(held[payload['scope']])-session.clock()
    held[payload['scope']].update(epoch=session.state['journey_id'],remaining_num=remaining.numerator,remaining_den=remaining.denominator)
    if payload['kind']=='recovery_interruption':
        activity=recovery_state(session,aid).get('activity')
        if activity and not activity.get('interrupted'):
            activity['interrupted']=1
            session.emit('BODY_RECOVERY_INTERRUPTED',aid,mode=activity['mode'],receipt_id=fact['receipt_id'])
    session.emit('BODY_SOURCE_ADMITTED',aid,receipt_id=fact['receipt_id'],kind_name=payload['kind'],scope=payload['scope'])
    return True


@hook('journey_initialize')
def journey_initialize(session,aid):
    actor=session.state['actors'][aid]; ps=profiles(actor['bundle'])
    if not ps:return
    from fractions import Fraction
    for record in actor.get('source_states',{}).get(AUTHORITY,{}).get('sources',{}).values():
        if record.get('epoch') and record['epoch']!=session.state['journey_id']:
            deadline=session.clock()+Fraction(record['remaining_num'],record['remaining_den'])
            record.update(deadline_num=deadline.numerator,deadline_den=deadline.denominator,epoch=session.state['journey_id'])
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


@hook('journey_to_combat')
def journey_to_combat(session,aid,bundle):
    actor=session.state['actors'][aid]
    if not profiles(bundle):return
    bundle['body_modes_scene_resources']={'records':deepcopy(actor.get('source_states',{}).get(AUTHORITY,{}).get('records',{})),
        'source_states':deepcopy(actor.get('source_states',{}).get(AUTHORITY,{}).get('sources',{})),'seconds':int(session.clock())}


@hook('match_initialize',priority=-210)
def bind_world_sources(engine):
    initialized=False
    for actor in engine.state.actors.values():
        transfer=bundle_of(engine,actor).get('body_modes_scene_resources') or {}
        for scope,record in transfer.get('source_states',{}).items():
            if record['kind'] not in ('cultivation_suppression','qualified_source','breathing_exposure') or source_deadline(record)<=transfer.get('seconds',0):continue
            value=deepcopy(record['value'])
            remaining=source_deadline(record)-transfer.get('seconds',0)
            initialized=True
            engine._apply_condition(actor,SUPPRESSION if record['kind']=='cultivation_suppression' else 'condition:typed.qualified_body_source',AUTHORITY,actor.entity_id,expires_on='UNTIL_REMOVED',
                data={**value,'kind':record['kind'],'receipt_id':record['receipt_id'],'scope':scope,'label':'Recorded cultivation suppression',
                      'body_expires_num':remaining.numerator,'body_expires_den':remaining.denominator,
                      'body_created_round':engine.state.round_number,'body_created_slot':engine.state.current_slot_index})
    return True if initialized else None


@hook('turn_start',priority=-200)
def source_clock(engine,actor):
    from fractions import Fraction
    slots=max(1,len(engine.state.initiative_order))
    for subject in engine.state.actors.values():
        for c in list(subject.conditions.values()):
            d=c.data
            if 'body_expires_num' not in d and 'body_expires_seconds' not in d:continue
            expiry=Fraction(d['body_expires_num'],d['body_expires_den']) if 'body_expires_num' in d else Fraction(d['body_expires_seconds'])
            elapsed=Fraction(((engine.state.round_number-int(d['body_created_round']))*slots+engine.state.current_slot_index-int(d.get('body_created_slot',0)))*6,slots)
            if elapsed>=expiry:engine._remove_condition_instance(subject,c.instance_id,AUTHORITY,expected=c)


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
    if ps and source.startswith(('tianxia.path.body_refining.','tianxia.subpath.body.')) and not available(engine,actor,source,0):return False
    for profile in ps:
        level=profile.get('feature_levels',{}).get(source)
        if level is not None and not available(engine,actor,source,level):return False


@hook('reaction_rows')
def gate_reactions(engine,actor_id,block,rows):
    actor=engine.state.actors.get(actor_id)
    if actor is None:return
    levels={f:n for p in profiles(bundle_of(engine,actor)) for f,n in p.get('feature_levels',{}).items()}
    if not levels:return
    result=[]
    for row in rows:
        source=str(row.get('feature_id') or '')
        if not source.startswith(('tianxia.path.body_refining.','tianxia.subpath.body.')):
            result.append(row);continue
        policies=query('cultivation_row_available',engine,actor,block,row)
        if False not in policies and (True in policies or available(engine,actor,source,levels.get(source,0))):result.append(row)
    return result


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
    clone.modifiers={k:m for k,m in clone.modifiers.items() if not any(source_matches(m.source_definition_id,p) for p in ps)}
    return clone


@hook('journey_encounter_settled')
def export_managed(session,aid,engine,creature):
    ps=profiles(bundle_of(engine,creature))
    if not ps:return
    actor=session.state['actors'][aid]
    state=actor.setdefault('source_states',{}).setdefault(AUTHORITY,{})
    state['records']={p['source']:deepcopy(scene_record(engine,creature,p['source']).data) for p in ps if scene_record(engine,creature,p['source'])}
    items=[]
    for kind,collection in (('condition',creature.conditions),('modifier',creature.modifiers)):
        for item in collection.values():
            if kind=='condition' and item.condition_id in (SCENE,SUPPRESSION):continue
            if not any(source_matches(item.source_definition_id,p) for p in ps):continue
            if any(item.source_definition_id in p.get('separate_effect_sources',[]) for p in ps):continue
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
    for record in state.get('sources',{}).values():
        if record.get('epoch'):
            remaining=max(Fraction(0),source_deadline(record)-session.clock())
            record.update(remaining_num=remaining.numerator,remaining_den=remaining.denominator)
    keep=[]
    for row in state.get('effects',[]):
        if 'remaining_num' in row:
            remaining=Fraction(row['remaining_num'],row['remaining_den'])-seconds
            if remaining<=0:continue
            row.update(remaining_num=remaining.numerator,remaining_den=remaining.denominator)
        keep.append(row)
    state['effects']=keep


@hook('journey_to_combat',priority=100)
def transfer_managed(session,aid,bundle):
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
    cl=int(actor['bundle'].get('cl') or 1)
    for record in actor.get('source_states',{}).get(AUTHORITY,{}).get('sources',{}).values():
        if source_deadline(record)<=(session.clock() if at is None else at) or record['kind']!='cultivation_suppression':continue
        value=record['value']
        if value.get('feature_id')==feature:return False
        if value.get('system') in ('body','all','tianxia.path.body_refining'):
            if value.get('suppressed')==1:return False
            cl=min(cl,int(value.get('effective_cl',cl)))
    return cl>=level


def qualifying_activation(engine,actor,receipt):
    """Reject declared staged/controlled resource farms and repeated nonhostile uses.

    Hostility/Source CL are native relation/bundle facts; staging is a trusted
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
        if other.summon is not None and other.owner_id in (actor.entity_id,actor.owner_id):continue
        cl=int(bundle_of(engine,other).get('cl') or 0)
        if cl and cl>=effective_body_cl(engine,actor)-5:return True
        if any(d.get('equivalent_encounter_threat')==1 and d.get('hostile')==1 and d.get('staged')==0 for d in declared):return True
    if disqualified:return False
    record=next((c for c in actor.conditions.values() if c.condition_id==SCENE),None)
    if record is None:return False
    prior=set(record.data.get('nonhostile_sources') or [])
    if source in prior:return False
    set_record(engine,actor,record.data['source'],{**record.data,'nonhostile_sources':sorted(prior|{source})})
    return True


@hook('path_rider_rows')
def gate_path_riders(engine,actor,kind,rows):
    levels={f:n for p in profiles(bundle_of(engine,actor)) for f,n in p.get('feature_levels',{}).items()}
    if levels:return [r for r in rows if (not str(r.get('feature_id') or '').startswith(('tianxia.path.body_refining.','tianxia.subpath.body.')) or available(engine,actor,r['feature_id'],levels.get(r['feature_id'],0)))]


@hook('pinpoint_target')
def visible_light_source(engine,viewer,seen):
    # Light reveals its source square, never grants sight of an Invisible body,
    # sight through Smoke, truesight, or perception through a wall.
    # Only a light reply from a Body source enrolled on the seen creature counts;
    # other creatures' light (or a reply with no source) never changes location knowledge.
    if any(c.condition_id in ('condition:typed.invisible','condition:core.invisible') for c in seen.conditions.values()):return
    enrolled={p.get('source') for p in profiles(bundle_of(engine,seen)) if p.get('source')}
    if not any(isinstance(reply,dict) and reply.get('source') in enrolled and (reply.get('dim_ft',0)>0 or reply.get('bright_ft',0)>0)
               for reply in query('light_emission',engine,seen)):return
    from .. import senses,zones
    from ..typed_executor import condition_rules
    if any(r.get('blinded') for r in condition_rules(viewer)):return
    if senses.physical_sight(engine,viewer,seen) and not zones.hidden_from(engine,viewer,seen):return True


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


@hook('journey_to_combat',priority=110)
def bind_scene_limits(session,aid,bundle):
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
        if fact['kind'] not in ('cultivation_suppression','qualified_source','breathing_exposure','recovery_interruption'):continue
        current=read(session,AUTHORITY,aid,fact['kind'],fact['scope'],aid)
        if current is None or current['receipt_id']!=fact['receipt_id']:continue
        label={'cultivation_suppression':'cultivation suppression','qualified_source':'hostile-source authority','breathing_exposure':'breathing hazard','recovery_interruption':'recovery interruption'}[fact['kind']]
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
    compiled=min([int(bundle_of(engine,actor).get('cl') or 1),*[int(p['body_attainment']) for p in profiles(bundle_of(engine,actor)) if 'body_attainment' in p]])
    effective=effective_body_cl(engine,actor)
    return min(base,2+(max(1,effective)-1)//4) if effective<compiled else base


@hook('resolution_numbers')
def body_resolution_numbers(ctx,numbers):
    if not profiles(bundle_of(ctx.engine,ctx.actor)) or ctx.typed.get('source_cl_locked')==1:return
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


RECOVERY='body_recover_stamina'


def recovery_state(session,aid):
    return session.state['actors'][aid].setdefault('source_states',{}).setdefault(AUTHORITY,{}).setdefault(
        'recovery',{'short_rests':0,'cultivation_sessions':0})


def stamina_maximum(actor):
    return next((int(p['maximum']) for p in actor['bundle']['actor_template']['resources'] if p['resource_id']==STAMINA),0)


@hook('journey_options')
def recovery_options(session,aid):
    actor=session.state['actors'][aid]
    if not profiles(actor['bundle']) or actor['incapacitated']:return
    from fractions import Fraction
    state=actor.get('source_states',{}).get(AUTHORITY,{}).get('recovery',{});activity=state.get('activity')
    out=[]
    if activity:
        if not activity.get('interrupted'):
            remaining=max(Fraction(0),Fraction(activity['deadline_num'],activity['deadline_den'])-session.clock())
            if remaining:
                seconds=(remaining.numerator+remaining.denominator-1)//remaining.denominator
                out.append({'id':'body.recovery.wait','kind':'wait','payload':{'seconds':seconds},'auto_select':0,
                    'label':f"{actor['name']}: continue the {activity['name']} for {seconds} seconds; acting or entering combat interrupts it."})
            else:
                out.append({'id':'body.recovery.finish','kind':RECOVERY,'payload':{'phase':'finish'},'auto_select':0,
                    'label':f"{actor['name']}: finish the uninterrupted {activity['name']} and recover Stamina (no scene reset)."})
        out.append({'id':'body.recovery.cancel','kind':RECOVERY,'payload':{'phase':'cancel'},'auto_select':0,
                    'label':f"{actor['name']}: end the {activity['name']} without recovering Stamina."})
        return out
    for mode,name,seconds,key,limit in (('short_rest','one-hour Short Rest',3600,'short_rests',2),
                                       ('cultivation_session','two-hour Cultivation Session',7200,'cultivation_sessions',1)):
        if state.get(key,0)<limit:
            amount=stamina_maximum(actor)//2 if mode=='short_rest' else stamina_maximum(actor)
            out.append({'id':'body.recovery.'+mode,'kind':RECOVERY,'payload':{'phase':'start','mode':mode},'auto_select':0,
                'label':f"{actor['name']}: begin a {name}; recover {'up to ' if mode=='short_rest' else 'all missing '}{amount if mode=='short_rest' else ''} Stamina after uninterrupted time; {limit-state.get(key,0)} uses before a Long Rest."})
    return out or None


@hook('journey_command')
def recover_stamina(session,aid,kind,payload):
    if kind!=RECOVERY:return
    from ..journey import require
    actor=session.state['actors'][aid]
    require(profiles(actor['bundle']) and not actor['incapacitated'],'Only a conscious enrolled Body practitioner may recover Stamina.')
    require(payload.get('phase') in ('start','finish','cancel'),'Choose whether to start, finish or cancel recovery.')
    state=recovery_state(session,aid)
    if payload['phase']=='start':
        require(set(payload)=={'phase','mode'} and payload['mode'] in ('short_rest','cultivation_session') and not state.get('activity'),
                'Choose one recovery procedure; finish or cancel an existing one first.')
        mode=payload['mode'];key='short_rests' if mode=='short_rest' else 'cultivation_sessions';limit=2 if mode=='short_rest' else 1
        require(state.get(key,0)<limit,'This recovery has no uses left before a Long Rest.')
        deadline=session.clock()+(3600 if mode=='short_rest' else 7200)
        state['activity']={'mode':mode,'name':'Short Rest' if mode=='short_rest' else 'Cultivation Session',
            'deadline_num':deadline.numerator,'deadline_den':deadline.denominator,'interrupted':0}
        session.emit('BODY_RECOVERY_STARTED',aid,mode=mode,deadline_num=deadline.numerator,deadline_den=deadline.denominator)
    else:
        require(set(payload)=={'phase'} and state.get('activity'),'There is no recovery in progress.')
        activity=state['activity']
        if payload['phase']=='finish':
            from fractions import Fraction
            require(not activity['interrupted'] and session.clock()>=Fraction(activity['deadline_num'],activity['deadline_den']),
                    'The printed uninterrupted recovery time has not completed.')
            maximum=stamina_maximum(actor);before=actor['resources'].get(STAMINA,0)
            amount=maximum//2 if activity['mode']=='short_rest' else maximum
            actor['resources'][STAMINA]=min(maximum,before+amount)
            key='short_rests' if activity['mode']=='short_rest' else 'cultivation_sessions'
            state[key]=state.get(key,0)+1
            session.emit('RESOURCE_GAINED',aid,source=AUTHORITY,resource_id=STAMINA,amount=actor['resources'][STAMINA]-before)
            session.emit('BODY_RECOVERY_COMPLETED',aid,mode=activity['mode'])
        else:session.emit('BODY_RECOVERY_CANCELLED',aid,mode=activity['mode'])
        state.pop('activity')
    return True


@hook('journey_before_command')
def recovery_interruption(session,aid,kind,payload):
    quiet={'wait','declare_fact','body_source_state',RECOVERY,'incapacitated'}
    for subject,actor in session.state['actors'].items():
        state=actor.get('source_states',{}).get(AUTHORITY,{}).get('recovery',{})
        activity=state.get('activity')
        if not activity or activity.get('interrupted'):continue
        interrupt=(kind=='enter_combat' or subject==aid and (kind not in quiet or kind=='incapacitated' and payload.get('value')))
        if interrupt:
            activity['interrupted']=1
            session.emit('BODY_RECOVERY_INTERRUPTED',subject,mode=activity['mode'],trigger=kind)


@hook('journey_rest')
def full_rest_stamina(session,aid):
    actor=session.state['actors'][aid]
    if not profiles(actor['bundle']):return
    before=actor['resources'].get(STAMINA,0);actor['resources'][STAMINA]=stamina_maximum(actor)
    actor.setdefault('source_states',{}).setdefault(AUTHORITY,{})['recovery']={'short_rests':0,'cultivation_sessions':0}
    session.emit('RESOURCE_GAINED',aid,source=AUTHORITY,resource_id=STAMINA,amount=actor['resources'][STAMINA]-before)


@hook('state_event')
def stamina_empty_exhaustion(engine,event):
    if event.event_type!='RESOURCE_SPENT' or event.payload.get('resource_id')!=STAMINA or int(event.payload.get('amount') or 0)<=0:return
    actor=engine.state.actors.get(event.actor_id)
    if actor is None or actor.resources.get(STAMINA)!=0 or not profiles(bundle_of(engine,actor)):return
    from .forged_exhaustion import add
    add(engine,actor,1,AUTHORITY)


@hook('journey_acquired')
def acquisition_interrupts_recovery(session,aid,source,acquisition_id,userdata_root=None):
    recovery_interruption(session,aid,'source_acquired',{})


@hook('state_event',priority=150)
def reconcile_dormant_effects(engine,event):
    """Retain actual source effects while their admitted feature is dormant.

    This consumes the same cultivation_suppression producer as activation
    availability. Existing generic suppression records carry original models
    and absolute clocks; no damage/payment is undone and nothing is re-created
    from a declaration. Family-owned deferred procedures may opt out because
    they preserve another source's consequence rather than a cultivated state.
    """
    if getattr(engine,'_body_retained_batch',0):return
    if event.event_type not in ('CONDITION_APPLIED','CONDITION_REMOVED','CONDITION_UPDATED','MODIFIER_APPLIED','MODIFIER_REMOVED','TURN_STARTED','ROUND_STARTED'):return
    from .benefit_suppression import SUPPRESSED,suppress
    from .suppressed_effects import alive,restore,saved_lifetime
    from .ability_source import mechanic_at
    for holder in list(engine.state.actors.values()):
        for marker in list(holder.conditions.values()):
            binding=marker.data.get('resume_when') if marker.condition_id==SUPPRESSED else None
            if marker.source_definition_id!=AUTHORITY or marker.data.get('until')!='source_available' or not binding:continue
            owner=engine.state.actors.get(binding['owner'])
            if owner is None:continue
            if not alive(engine,marker.data['lifetime']):
                engine._remove_condition_instance(holder,marker.instance_id,AUTHORITY,expected=marker)
            elif available(engine,owner,binding['feature'],binding['level'],requires_conscious=False):
                clock=saved_lifetime(holder,marker)
                if engine._remove_condition_instance(holder,marker.instance_id,AUTHORITY,expected=marker):
                    restore(engine,holder,marker.data['model'],clock,modifier=marker.data['kind']=='modifier',restore_reaction_state=True)
        for kind,collection in (('condition',holder.conditions),('modifier',holder.modifiers)):
            for item in list(collection.values()):
                if kind=='condition' and item.condition_id in (SUPPRESSION,SCENE,SUPPRESSED):continue
                owner=engine.state.actors.get(item.source_actor_id)
                if owner is None:continue
                source=mechanic_at(engine,item.source_definition_id) or item.source_definition_id
                profile=next((p for p in profiles(bundle_of(engine,owner)) if source in p.get('feature_levels',{})),None)
                if profile is None or kind=='condition' and item.condition_id in profile.get('dormancy_exclusions',[]):continue
                level=profile['feature_levels'][source]
                bindings=[b for b in query('cultivation_effect_binding',engine,holder,item) if b is not None]
                if len(bindings)>1:raise ValueError('An effect has conflicting cultivation source bindings.')
                if bindings:
                    source=bindings[0]['feature']
                    level=profile['feature_levels'].get(source,level)
                if not available(engine,owner,source,level,requires_conscious=False):
                    suppress(engine,owner,holder,kind+':'+(item.instance_id if kind=='condition' else item.modifier_id),
                             'source_available',AUTHORITY,label='Dormant cultivated effect: '+profile['name'],
                             resume_when={'owner':owner.entity_id,'feature':source,'level':level})


from contextlib import contextmanager

@contextmanager
def retained_effect_batch(engine):
    """Restore linked native components atomically before availability resumes.

    A transient nesting counter defers only Body dormancy reconciliation. It
    does not change payment, expiry or the enclosing persisted transaction.
    The final real committed event supplies the reconciliation boundary.
    """
    old=getattr(engine,'_body_retained_batch',0)
    engine._body_retained_batch=old+1
    try:yield
    finally:
        engine._body_retained_batch=old
        if not old and engine.events:reconcile_dormant_effects(engine,engine.events[-1])


@hook('damage_type_grant_available')
def granted_type_available(ctx,source):
    levels={f:n for p in profiles(bundle_of(ctx.engine,ctx.actor)) for f,n in p.get('feature_levels',{}).items()}
    if source in levels:return available(ctx.engine,ctx.actor,source,levels[source])


@hook('state_event')
def consume_dormant_next_roll(engine,event):
    if event.event_type not in ('ATTACK_ROLLED','SAVE_ROLLED'):return
    from .benefit_suppression import SUPPRESSED,cancel
    holder=engine.state.actors.get(event.actor_id)
    if holder is None:return
    ability=str(event.payload.get('ability') or event.payload.get('reason','').rsplit(':',1)[-1]).upper()
    for marker in list(holder.conditions.values()):
        d=marker.data
        if marker.condition_id!=SUPPRESSED or marker.source_definition_id!=AUTHORITY or d.get('until')!='source_available':continue
        model=d.get('model') or {}
        consume=(event.event_type=='ATTACK_ROLLED' and d.get('kind')=='modifier' and
                 model.get('target_field')=='attack_mode' and model.get('applies_to')=='NEXT_ATTACK')
        rule=(model.get('data',{}).get('rule') or {}).get('save_against') or {}
        if (event.event_type=='SAVE_ROLLED' and d.get('kind')=='condition' and rule.get('next')
                and not rule.get('against') and ability in rule.get('abilities',())):consume=True
        if consume:cancel(engine,holder,'condition:'+marker.instance_id,AUTHORITY)
