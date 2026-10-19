"""Source-owned short furnace benefits and prices across native encounters.

The existing journey snapshot and source-state contracts carry exact native
turn deadlines. A new fight never renews a benefit: it ends at the next printed
turn boundary. Elapsed travel time can expire it before a new fight begins.
Unrelated effects remain with their existing owners and require their own path.
"""
from fractions import Fraction
import json
from . import hook
from . import furnace_runtime as f
from ..journey import require

SHORTS=frozenset({'condition:typed.second_furnace_no_healing',
    'condition:typed.second_furnace_advantage','condition:typed.furnace_motion_check',
    'condition:typed.second_furnace_continuity'})


def deadline(engine,held):
    """Read this family's actual native turn token and committed turn receipts."""
    from .effect_durations import parse
    parsed=parse(held.expires_on)
    if parsed:edge,aid,count=parsed
    elif str(held.expires_on).startswith('END_OF_SOURCE_TURN_AT:'):
        edge,aid,count='end',held.source_actor_id,int(held.expires_on.rsplit(':',1)[1])
    else:
        raise ValueError('A short furnace effect needs its printed native turn deadline.')
    require(aid in engine.state.initiative_order,'The timed furnace effect needs its actual initiative actor.')
    actor=engine.state.actors[aid];order=len(engine.state.initiative_order)
    last=next((e for e in reversed(engine.events) if e.event_type=='TURN_STARTED' and e.actor_id==aid),None)
    last_round=int(last.payload['round']) if last else 0
    future=count-actor.turns_started
    end_round=last_round+future
    end_slot=engine.state.initiative_order.index(aid)+(edge=='end')
    remaining=Fraction((end_round-engine.state.round_number)*order+end_slot-engine.state.current_slot_index,order)*6
    return edge,aid,future,remaining


@hook('journey_snapshot_actor')
def export(creature,session,aid,engine):
    state=session.state['actors'][aid].get('source_states',{}).get(f.PARENT)
    if not state:return creature
    native=engine.state.actors[aid]
    if not f.acquired(native) or not f.owned(engine,native,f.SEED):return creature
    records=[];remove={}
    for held in native.conditions.values():
        if held.condition_id not in SHORTS:continue
        edge,owner,turns,remaining=deadline(engine,held)
        remove[held.instance_id]=1
        if remaining<=0:continue
        expiry=session.clock()+remaining
        data=json.loads(held.model_dump_json())
        if held.condition_id=='condition:typed.second_furnace_continuity':
            interference=native.conditions.get(held.data.get('interference_instance'))
            require(interference is not None,'Continuity must retain its actual suppression source.')
            data['data']['interference_admission_receipt']=interference.data['admission_receipt']
        records.append({'condition_json':json.dumps(data,sort_keys=True),'edge':edge,'turn_actor':owner,
            'remaining_turns':turns,'expires_num':expiry.numerator,'expires_den':expiry.denominator})
    state['continuation_conditions']=records
    if not remove:return creature
    clone=creature.model_copy(deep=True)
    clone.conditions={k:v for k,v in clone.conditions.items() if k not in remove}
    session.emit('SECOND_FURNACE_SHORT_EFFECTS_CONTINUED',aid,count=len(records),
        conditions=[json.loads(r['condition_json'])['condition_id'] for r in records])
    f.publish(session,aid)
    return clone


@hook('match_initialize',priority=40)
def bind(engine):
    from ..gate2_runtime_models import ConditionInstance
    from .effect_durations import token
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id']);native=bundle.get('second_furnace_native') or {}
        if actor is None or not f.acquired(actor) or not f.owned(engine,actor,f.SEED):continue
        now=Fraction(native.get('clock_num',native.get('clock_seconds',0)),native.get('clock_den',1))
        for record in native.get('continuation_conditions',[]):
            remaining=f.profile_expiry(record)-now
            if remaining<=0:continue
            held=ConditionInstance.model_validate_json(record['condition_json'])
            require(held.condition_id in SHORTS and held.target_id==actor.entity_id and held.source_actor_id==actor.entity_id,
                'Only the acquired owner’s actual short furnace effects may continue.')
            owner=engine.state.actors.get(record['turn_actor'])
            require(owner is not None and record['remaining_turns']>=0,'The actual deadline actor must remain present.')
            if held.condition_id=='condition:typed.second_furnace_continuity':
                receipt=held.data.get('interference_admission_receipt')
                interference=next((c for c in actor.conditions.values() if c.condition_id==f.INTERFERENCE and c.data.get('admission_receipt')==receipt),None)
                if interference is None:continue
                held.data['interference_instance']=interference.instance_id
            marker=held.instance_id
            data={**held.data,'furnace_continuation_key':marker}
            engine._apply_condition(actor,held.condition_id,held.source_definition_id,held.source_actor_id,
                expires_on=token(record['edge'],owner.entity_id,owner.turns_started+record['remaining_turns']),data=data)


@hook('journey_elapsed',priority=50)
def elapsed(session,aid,before,seconds,moving):
    state=session.state['actors'][aid].get('source_states',{}).get(f.PARENT)
    if state:state['continuation_conditions']=[r for r in state.get('continuation_conditions',[]) if f.profile_expiry(r)>session.clock()]


@hook('journey_properties')
def properties(session,aid):
    state=session.state['actors'][aid].get('source_states',{}).get(f.PARENT) or {}
    if any(f.profile_expiry(r)>session.clock() and json.loads(r['condition_json'])['condition_id']=='condition:typed.second_furnace_no_healing'
        for r in state.get('continuation_conditions',[])):
        return {'healing_denied':1}
