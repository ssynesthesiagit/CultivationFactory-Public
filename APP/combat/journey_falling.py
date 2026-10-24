"""Native falling adapter for journeys, used when Cloud Walker withdraws flight.

Physics, defenses, dice, reaction admission/payment and legal choices belong to
the combat engine. This adapter only transports its transaction and choices to
the journey journal. Unanswered human choices retain a deterministic genesis;
reopening never declines a reaction, heals an injury or refreshes a resource.
"""
import json
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from . import ext
from .journey import require

SOURCE='system:journey.falling'
# A printed fall ends in a landing, never in an endless descent. Featherfall's
# protection lasts one minute (ten six-second rounds), so no legitimate fall
# needs anything like this many; the bound only stops an unresolved geometry
# from consuming the session, and it raises the same explicit blocked-landing
# error rather than silently inventing a landing.
MAX_DESCENT_ROUNDS=120


def request_fall(session, actor_id, cause):
    if session.state['actors'][actor_id]['position'].get('z',0)>0:
        session.state.setdefault('journey_falls_due',{})[actor_id]=cause


class AwaitReaction(ext.ControllerPause):
    def __init__(self, request):
        self.request=request


def engine_for(state):
    from .gate4_engine import Gate4ControllerEngine
    from .gate2_runtime_models import Position, ConditionInstance
    actors=state['actors'];bundles=[]
    for aid,a in actors.items():
        bundle=deepcopy(a['bundle'])
        for pool in bundle['actor_template']['resources']:
            pool['initial']=a['resources'].get(pool['resource_id'],pool['initial'])
        bundle['journey_setup']={k:a[k] for k in ('incapacitated','exhaustion','encounter_snapshot') if k in a}
        bundles.append(bundle)
    # Distinct grouping IDs must not turn an undeclared relationship into
    # hostility either. Native recipient/reaction rules see unknown travellers
    # as neutral; explicit team declarations retain their native meaning.
    neutral={left:{right:'NEUTRAL' for right in sorted(actors) if left<right
                  and not (actors[left].get('team_id') and actors[right].get('team_id'))}
             for left in sorted(actors)}
    neutral={left:row for left,row in neutral.items() if row}
    engine=Gate4ControllerEngine(Path(__file__).resolve().parents[1],
        match_seed='JOURNEY-FALL-'+state['journey_id']+':'+str(len(state['events'])),
        typed_bundles=tuple(bundles),battlefield=state['battlefield'],
        # Joining a journey/accepting mist is not a declaration of allegiance.
        # Preserve an explicit team if present; otherwise AI may prefer itself
        # without treating unknown fellow travellers as known allies.
        roster_setup={'physical_scene':1,'primary_actor_ids':list(actors),'team_by_actor':{aid:a.get('team_id',aid) for aid,a in actors.items()},
                      'relations':{'actors':neutral},
                      'rules':{'zero_hp':'dying_2024','finalized_turns':'skip_finalized_v1'},
                      'starting_positions':{aid:a['position'] for aid,a in actors.items()}})
    engine.typed_control_modes={aid:a['control_mode'] for aid,a in actors.items()}
    engine.state.terminal_result=None
    now=Fraction(state['seconds'])+Fraction(state.get('subsecond_num',0),state.get('subsecond_den',1))
    for aid,a in actors.items():
        actor=engine.state.actors[aid];actor.position=Position.model_validate(a['position'])
        if now<Fraction(a.get('journey_reaction_ready','0')):actor.reaction_available=False
        for held in a.get('journey_fall_effects',()):
            if now<Fraction(held['expires']):
                condition=ConditionInstance.model_validate_json(held['condition'])
                actor.conditions[condition.instance_id]=condition
    return engine


def resolve(session, genesis, answers):
    from .gate2_runtime_models import ActionIntent, ReactionDecision
    from .falling import settle, required
    engine=engine_for(genesis)
    initial={aid:set(a.conditions) for aid,a in engine.state.actors.items()}
    now=Fraction(genesis['seconds'])+Fraction(genesis.get('subsecond_num',0),genesis.get('subsecond_den',1))
    elapsed=0;deadlines={};reaction_spent_at={}
    for aid,a in genesis['actors'].items():
        for row in a.get('journey_fall_effects',()):
            deadlines[json.loads(row['condition'])['instance_id']]=Fraction(row['expires'])
    def provider(request):
        key=tuple(request[k] for k in ('checkpoint','reactor_id','reaction_source_id'))
        answer=next((a for a in answers if tuple(a[k] for k in ('checkpoint','reactor_id','reaction_source_id'))==key),None)
        if answer:return ReactionDecision.model_validate(answer),None
        if genesis['actors'][request['reactor_id']]['control_mode']=='LOCAL_AUTO':
            spec=request.get('extension_choice') or {}
            options=spec.get('preferred_option_ids',[])[:spec.get('maximum_selections',1)] if spec.get('automatic_use') else []
            return ReactionDecision(checkpoint=key[0],reactor_id=key[1],reaction_source_id=key[2],
                                    selection='USE' if options else 'DECLINE',option_ids=tuple(options)),None
        raise AwaitReaction(request)
    engine.set_reaction_provider(provider)
    engine._active_intent=ActionIntent(intent_id='journey:fall',decision_id='journey:fall',candidate_id='journey:fall',
        state_version=engine.state.state_version,actor_id=next(iter(genesis['journey_falls_due'])))
    try:
        stalled={}
        rounds=0
        while True:
            rounds+=1
            positions={aid:a.position for aid,a in engine.state.actors.items()}
            available={aid for aid,a in engine.state.actors.items() if a.reaction_available}
            event_start=len(engine.events)
            settle(engine,'journey:flight_withdrawn',engine._active_intent)
            # A native admitted reaction spends at this checkpoint, not at the
            # end of a possibly multi-round descent. Imported unavailability
            # and injury/incapacitation are not new reaction consumption.
            for event in engine.events[event_start:]:
                if (event.event_type=='REACTION_WINDOW_OPENED' and event.actor_id in available
                        and not engine.state.actors[event.actor_id].reaction_available):
                    reaction_spent_at[event.actor_id]=now+elapsed
            for actor in engine.state.actors.values():
                for condition in actor.conditions.values():
                    if 'fall_speed_ft' in condition.data and condition.instance_id not in deadlines:
                        deadlines[condition.instance_id]=now+elapsed+60
            if not any(required(engine,a) for a in engine.state.actors.values()):break
            # A descent must lose altitude every round. The stalled check below only
            # fires when nothing moved at all, so a creature that keeps changing
            # position without ever getting closer to the ground used to spin here
            # for unlimited rounds. Unresolved geometry is an explicit error instead.
            for aid,creature in engine.state.actors.items():
                if not required(engine,creature):continue
                was=stalled.get(aid)
                stalled[aid]=creature.position.z
                require(was is None or creature.position.z!=was,
                        'The fall cannot reach a legal supporting space. Resolve the blocked landing before continuing.')
            require(rounds<=MAX_DESCENT_ROUNDS,
                    'The fall cannot reach a legal supporting space. Resolve the blocked landing before continuing.')
            if positions=={aid:a.position for aid,a in engine.state.actors.items()} and any(
                    e.payload.get('blocked_landing') for e in engine.events):break
            if positions=={aid:a.position for aid,a in engine.state.actors.items()}:
                from .falling import settings
                falling=[a for a in engine.state.actors.values() if required(engine,a)]
                # Only a spent native per-round descent budget can make the
                # next round useful without moving now. An unresolved geometry
                # or provider failure must not spin through unlimited rounds.
                require(all(settings(a)[0] is not None
                            and a.turn_flags.get('fall_round_number')==engine.state.round_number
                            and int(a.turn_flags.get('fall_round_ft',0))>=settings(a)[0]
                            for a in falling),
                        'The fall cannot reach a legal supporting space. Resolve the blocked landing before continuing.')
            # A native rate-limited descent continues at the next six-second
            # round checkpoint. Featherfall's printed minute never becomes permanent.
            elapsed+=6;engine.state.round_number+=1
            for actor in engine.state.actors.values():
                for iid in list(actor.conditions):
                    if iid in deadlines and deadlines[iid]<=now+elapsed:
                        engine._remove_condition_instance(actor,iid,'journey:elapsed')
            # A physically blocked landing remains explicit instead of looping.
            if all(a.position.z==0 or not a.active for a in engine.state.actors.values()):break
    except AwaitReaction as pause:
        session.state['journey_fall_pending']={'genesis':json.dumps(genesis,sort_keys=True),
            'answers':answers,'request':pause.request,'selected':[]}
        return
    from .ext.journey_setup import encounter_snapshot, encounter_incapacitated, encounter_condition_persistent
    for aid,creature in engine.state.actors.items():
        if aid not in session.state['actors']:continue
        a=session.state['actors'][aid];snapshot=creature.model_copy(deep=True)
        protections=[]
        for iid,c in list(snapshot.conditions.items()):
            if iid in deadlines and deadlines[iid]>now+elapsed:
                protections.append({'condition':c.model_dump_json(),'expires':str(deadlines[iid])})
            if iid in deadlines or (iid in initial[aid] and not encounter_condition_persistent(c)):
                del snapshot.conditions[iid]
        a['journey_fall_effects']=protections
        a['encounter_snapshot']=encounter_snapshot(snapshot)
        a['incapacitated']=int(encounter_incapacitated(a['encounter_snapshot']))
        a['resources']={k:int(v) for k,v in creature.resources.items()}
        a['position']=creature.position.model_dump(mode='json')
        if aid in reaction_spent_at:a['journey_reaction_ready']=str(reaction_spent_at[aid]+6)
    session.state.pop('journey_fall_pending',None)
    session.state.pop('journey_falls_due',None)
    session.emit('JOURNEY_FALL_RESOLVED',engine._active_intent.actor_id,
        native_events=json.dumps([e.model_dump(mode='json') for e in engine.events],sort_keys=True),elapsed_seconds=elapsed,
        text='Lost flight: falling, optional reactions and landing are resolved.')
    for aid in session.state['actors']:update_protections(session,aid,now,0,())
    if elapsed:session.tick(elapsed)


@ext.hook('journey_checkpoint')
def checkpoint(session):
    if session.state.get('journey_falls_due') and not session.state.get('journey_fall_pending'):
        from .journey_replay import body
        resolve(session,deepcopy(body(session.state)),[])


@ext.hook('journey_interruption_options')
def options(session,aid):
    pending=session.state.get('journey_fall_pending')
    if not pending:return None
    if pending['request']['reactor_id']!=aid:return []
    request=pending['request'];spec=request.get('extension_choice') or {}
    selected=pending['selected'];trigger=request.get('choice_trigger') or {};labels=trigger.get('labels') or {}
    name=trigger.get('name') or 'Falling reaction'
    prompt=trigger.get('prompt') or 'Resolve the reaction to lost flight.'
    result=[]
    if 'extension_choice' not in request:
        for spend in request.get('spend_options') or [0]:
            for option in request.get('legal_option_ids') or [None]:
                payload={'selection':'USE','spend':spend,'option_ids':[option] if option else []}
                result.append({'id':'journey_fall_reply:'+str(spend)+':'+str(option),'kind':'journey_fall_reply',
                    'payload':payload,'label':name+': use the reaction'+(f' (spend {spend}). ' if spend else '. ')+prompt})
        result.append({'id':'journey_fall_reply:DECLINE','kind':'journey_fall_reply',
            'payload':{'selection':'DECLINE'},'label':name+': decline the reaction to lost flight.'})
        return result
    for key in spec.get('option_ids',request.get('legal_option_ids',[])):
        if key not in selected and len(selected)>=spec.get('maximum_selections',1):continue
        result.append({'id':'journey_fall_select:'+key,'kind':'journey_fall_select','payload':{'option_id':key},
            'label':name+': '+('Remove ' if key in selected else 'Choose ')+labels.get(key,key)+'. '+prompt})
    for selection in ('USE','DECLINE'):
        if selection=='DECLINE' and not spec.get('allow_decline',True):continue
        if selection=='USE' and not spec.get('minimum_selections',1)<=len(selected)<=spec.get('maximum_selections',1):continue
        result.append({'id':'journey_fall_reply:'+selection,'kind':'journey_fall_reply',
            'payload':{'selection':selection},'label':name+': '+('Confirm selected creatures. ' if selection=='USE' else 'Decline. ')+prompt})
    return result


@ext.hook('journey_command_guard')
def guard(session,aid,kind,payload):
    if session.state.get('journey_fall_pending'):
        require(any(o['kind']==kind and o['payload']==payload for o in options(session,aid)),
                'Answer the pending falling reaction before continuing the journey.')


@ext.hook('journey_command')
def reply(session,aid,kind,payload):
    if kind not in {'journey_fall_select','journey_fall_reply'}:return None
    guard(session,aid,kind,payload)
    pending=session.state.get('journey_fall_pending');require(pending,'No falling reaction is pending.')
    if kind=='journey_fall_select':
        selected=pending['selected'];key=payload['option_id']
        if key in selected:selected.remove(key)
        else:selected.append(key)
    else:
        request=pending['request']
        answer={k:request[k] for k in ('checkpoint','reactor_id','reaction_source_id')}
        answer.update(selection=payload['selection'],spend=payload.get('spend',0),
            option_ids=payload.get('option_ids',list(pending['selected'])) if payload['selection']=='USE' else [])
        resolve(session,json.loads(pending['genesis']),[*pending['answers'],answer])
    return True


@ext.hook('journey_auto_blocked')
def waiting(session,aid):
    return True if session.state.get('journey_fall_pending') else None


@ext.hook('match_initialize')
def restore_protections(engine):
    from .gate2_runtime_models import ConditionInstance
    from .asset_anchor_runtime import remaining_lifetime_token
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:continue
        for row in bundle.get('journey_fall_protections',()):
            c=ConditionInstance.model_validate_json(row['condition'])
            c.expires_on=remaining_lifetime_token(engine,Fraction(row['remaining']))
            actor.conditions[c.instance_id]=c


@ext.hook('journey_elapsed')
def update_protections(session,aid,before,seconds,moving):
    actor=session.state['actors'][aid]
    if 'journey_fall_effects' not in actor:return
    actor['journey_fall_effects']=[row for row in actor.get('journey_fall_effects',()) if Fraction(row['expires'])>session.clock()]
    if actor['journey_fall_effects']:
        actor['bundle']['journey_fall_protections']=[{'condition':r['condition'],'remaining':str(Fraction(r['expires'])-session.clock())}
            for r in actor['journey_fall_effects']]
    else:actor['bundle'].pop('journey_fall_protections',None)
    actor.setdefault('source_states',{})[SOURCE]={
        'effects':[{'condition':r['condition'],'remaining':str(Fraction(r['expires'])-session.clock())}
                   for r in actor['journey_fall_effects']],
        'reaction_remaining':str(max(Fraction(0),Fraction(actor.get('journey_reaction_ready','0'))-session.clock()))}


@ext.hook('journey_initialize')
def restore_journey(session,aid):
    actor=session.state['actors'][aid]
    saved=actor.get('source_states',{}).get(SOURCE)
    if saved is None:return
    actor['journey_fall_effects']=[{'condition':r['condition'],'expires':str(session.clock()+Fraction(r['remaining']))}
        for r in saved['effects'] if Fraction(r['remaining'])>0]
    actor['journey_reaction_ready']=str(session.clock()+Fraction(saved['reaction_remaining']))
    update_protections(session,aid,session.clock(),0,())


@ext.hook('journey_state_changed')
def save_journey(session,aid):
    update_protections(session,aid,session.clock(),0,())
