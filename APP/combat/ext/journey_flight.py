"""General source-granted journey flight and unsupported descent.

Consumers: Constellation Circuit and Nine-Star Incarnation. Capability comes
from journey_properties; no feature IDs occur here. Loss of support uses actual
position, native deterministic dice and persisted health, never a narration tag.
Ordinary ground journeys produce no events or state. Combat uses falling.py.
"""
import json
from contextvars import ContextVar
_STANDING_QUERY=ContextVar('journey_standing_query',default=None)
from . import hook
from ..gate2_runtime_models import Position,DiceSpec,ConditionInstance
from ..gate2_rolls import DeterministicRollAuthority

SOURCE='system:combat.falling'


def settle(session,aid):
    actor=session.state['actors'][aid]
    if session.state['phase']!='travel' or actor.get('carried_by'):return
    old=Position.model_validate(actor['position'])
    if old.z==0 or session.grid.roof_supported(old):return
    props=session.properties(aid)
    if not actor['incapacitated'] and (props.get('flight_hover') or props.get('fly_speed_ft',0)>0):return
    occupied={tuple(a['position'].get(k,0) for k in ('x','y','z')) for other,a in session.state['actors'].items() if other!=aid and not a.get('carried_by')}
    candidates=[Position(x=old.x,y=old.y,z=z) for z in range(old.z-1,-1,-1)]
    landing=next((p for p in candidates if (p.z==0 or session.grid.roof_supported(p)) and (p.x,p.y,p.z) not in occupied and session.grid.placement_legal(p,occupied_cells=set())),None)
    if landing is None:
        # Native geometry supplies the nearest legal adjacent ground space;
        # never put the falling creature inside a wall or another creature.
        candidates=[Position(x=x,y=y,z=0) for x in range(session.grid.width) for y in range(session.grid.height)
                    if max(abs(x-old.x),abs(y-old.y))<=1]
        landing=next((p for p in sorted(candidates,key=lambda p:(session.grid.distance_ft(old,p),p.x,p.y))
                      if (p.x,p.y,p.z) not in occupied and session.grid.placement_legal(p,occupied_cells=set())
                      and session.grid.line_of_physical_transmission(Position(x=old.x,y=old.y,z=0),p)),None)
    if landing is None:return
    distance=(old.z-landing.z)*5
    snapshot=actor.setdefault('encounter_snapshot',{'current_hp':actor['bundle']['actor_template']['maximum_hp'],
        'maximum_hp':actor['bundle']['actor_template']['maximum_hp'],'temporary_hp':0,'active':1,'life_state':'','conditions':{}})
    damage=0
    if distance>=10:
        roll=DeterministicRollAuthority(session.state['journey_id']+':fall:'+str(len(session.state['events']))).roll(
            DiceSpec(count=min(20,distance//10),sides=6),actor_id=aid,reason='FALLING_DAMAGE')
        damage=roll.total
        session.emit('JOURNEY_FALL_ROLLED',aid,roll=roll.model_dump(mode='json'),source=SOURCE)
    was_active=bool(snapshot.get('active',1))
    before=snapshot['current_hp'];temporary=min(snapshot.get('temporary_hp',0),damage)
    snapshot['temporary_hp']=snapshot.get('temporary_hp',0)-temporary
    damage-=temporary;snapshot['current_hp']=max(0,before-damage)
    if snapshot['current_hp']==0 and damage and was_active:
        dead=damage>=before+snapshot['maximum_hp']
        snapshot['life_state']='' if dead else 'DYING'
        snapshot['active']=int(not dead);actor['incapacitated']=1
        if dead:
            from .life_state import DEAD
            condition=ConditionInstance(instance_id='journey-fall-death:'+str(len(session.state['events'])),condition_id=DEAD,
                source_definition_id=SOURCE,source_actor_id=aid,target_id=aid,applied_sequence=len(session.state['events']),
                expires_on='UNTIL_REMOVED',data={'label':'Dead: massive falling damage'})
            snapshot['conditions'][condition.instance_id]=condition.model_dump_json()
    elif damage and was_active:
        condition=ConditionInstance(instance_id='journey-fall:'+str(len(session.state['events'])),condition_id='condition:core.prone',
            source_definition_id=SOURCE,source_actor_id=aid,target_id=aid,applied_sequence=len(session.state['events']),stacks=1,expires_on='STAND_UP',data={'label':'Prone after falling'})
        snapshot['conditions'][condition.instance_id]=condition.model_dump_json()
    actor['position']=landing.model_dump(mode='json')
    session.emit('JOURNEY_FALL_COMMITTED',aid,source=SOURCE,distance_ft=distance,position=actor['position'],
                 damage=damage,before=before,after=snapshot['current_hp'],clock_num=session.clock().numerator,clock_den=session.clock().denominator)


@hook('journey_state_changed',priority=200)
def changed(session,aid):
    settle(session,aid)


@hook('journey_elapsed',priority=200)
def elapsed(session,aid,before,seconds,moving):
    settle(session,aid)


def movement_rules(session,aid):
    """Actual retained condition rules, with native condition interpretation."""
    from types import SimpleNamespace
    from ..typed_executor import condition_rules
    rows=session.state['actors'][aid].get('encounter_snapshot',{}).get('conditions',{})
    actor=SimpleNamespace(conditions={key:ConditionInstance.model_validate(json.loads(raw)) for key,raw in rows.items()
        if not (_STANDING_QUERY.get()==(id(session),aid) and json.loads(raw).get('expires_on')=='STAND_UP')})
    return condition_rules(actor)


@hook('journey_step')
def retained_mobility(session,aid,old,nxt,regions):
    from ..journey import require
    rows=movement_rules(session,aid)
    require(not any(r.get('speed_zero') or r.get('no_actions') for r in rows),'A retained condition prevents this creature from moving.')
    if not (old.z or nxt.z) and any(r.get('ends_on_stand_up') for r in rows):return {'movement_cost':2}


def standing(session,aid):
    actor=session.state['actors'][aid]
    if actor['incapacitated']:return False
    rows=movement_rules(session,aid)
    raw=actor.get('encounter_snapshot',{}).get('conditions',{})
    return (any(json.loads(c).get('expires_on')=='STAND_UP' for c in raw.values()) and
        not any(r.get('speed_zero') or r.get('no_actions') for r in rows) and
        not any(json.loads(c).get('data',{}).get('cannot_stand') is True for c in raw.values()))


@hook('journey_options')
def stand_option(session,aid):
    if standing(session,aid):return [{'id':'ordinary:stand','kind':'stand_up','payload':{},
        'label':session.state['actors'][aid]['name']+': stand from Prone; spend the time for half your ordinary walking movement.'}]


@hook('journey_command')
def stand_command(session,aid,kind,payload):
    if kind!='stand_up':return
    from ..journey import require
    from fractions import Fraction
    require(not payload and standing(session,aid),'This creature cannot stand up now.')
    actor=session.state['actors'][aid]
    # Half the sourced walking Speed at the admitted overland pace. Nothing
    # grants a free stand; source features use their own explicit zero-cost path.
    seconds=Fraction(int(actor['bundle']['actor_template']['speed_ft'])*1800,actor['base_pace_ft_hour'])
    session.tick(seconds)
    health=actor['encounter_snapshot'];health['conditions']={key:raw for key,raw in health['conditions'].items() if json.loads(raw).get('expires_on')!='STAND_UP'}
    session.emit('STOOD_UP',aid,source='system:combat.stand_up',elapsed_num=seconds.numerator,elapsed_den=seconds.denominator)
    return True


def granted_destinations(session,aid,feet,*,after_standing=False):
    """One-step native travel geometry and movement cost for short grants.

    A standing projection only omits Prone after actual standing eligibility is
    established; no health, condition or position is mutated while offering it.
    """
    if after_standing and not standing(session,aid):return []
    token=_STANDING_QUERY.set((id(session),aid) if after_standing else None)
    try:
        actor=session.state['actors'][aid];old=Position.model_validate(actor['position']);out=[]
        for cell in session.adjacent(aid):
            try:cost=session.step_profile(aid,old,Position.model_validate(cell))
            except ValueError:continue
            if cost*session.grid.square_size_ft<=feet:out.append(cell)
        return out
    finally:_STANDING_QUERY.reset(token)
