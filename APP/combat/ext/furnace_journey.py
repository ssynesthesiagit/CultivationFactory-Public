"""Second Furnace's elapsed-time continuation on the existing journey contracts.

No encounter is created to use an organ outside combat. Acquisition, source facts,
resources, map movement and optimistic revision locking remain native producers.
"""
from fractions import Fraction
import copy
import json
from . import hook
from . import furnace_runtime as f
from ..journey import require


def state(session,aid):
    return session.state['actors'][aid].get('source_states',{}).get(f.PARENT)


def numbers(actor,source=f.ENGINE):
    for action in actor['bundle']['action_catalog']:
        typed=action.get('parameters',{}).get('typed',{})
        if typed.get('source')==source:return typed.get('numbers',{})
    return {}


def usable(session,aid):
    a=session.state['actors'][aid];s=state(session,aid)
    if not s or s.get('organ_removed') or s.get('dormant') or a['incapacitated']:return False
    cl=int(numbers(a).get('cl',0))
    for p in s.get('environment',[]):
        if p.get('subject')==aid and p.get('expires_at',0)>session.clock() and p.get('second_suppressed'):
            if (s.get('engine') and p.get('ordinary_suppressed') and int(p['source_cl'])<cl
                and not p.get('multiple_systems') and not p.get('complete')):continue
            return False
    return cl>=18


def active(session,aid):
    s=state(session,aid)
    return s and s.get('engine') and Fraction(s['engine']['expires_num'],s['engine']['expires_den'])>session.clock()


def snapshot(actor):
    if 'encounter_snapshot' not in actor:
        template=actor['bundle']['actor_template']
        actor['encounter_snapshot']={'current_hp':template['maximum_hp'],'maximum_hp':template['maximum_hp'],
            'temporary_hp':0,'active':1,'life_state':'','conditions':{}}
    return actor['encounter_snapshot']


@hook('journey_options')
def options(session,aid):
    if session.state['phase']!='travel':return None
    a=session.state['actors'][aid];s=state(session,aid)
    if not s:return None
    if s.get('engine_end_pending'):
        return [{'id':'second_furnace_end:'+kind,'kind':'furnace_engine_end','payload':{'damage_type':kind},
            'auto_select':0,'label':f"{a['name']}: End of the Engine — take 4d10 {kind.title()} damage that ignores Resistance"}
            for kind in ('psychic','necrotic')]
    if not usable(session,aid) or active(session,aid) or s.get('scene_engine_used') or a['resources'].get(f.QI,0)<8:return None
    # This is the ordinary payment option. Overdraw remains an actual alternative
    # at the existing combat activation checkpoint, never an automatic refund.
    return [{'id':f.ENGINE,'kind':'furnace_engine','payload':{},'auto_select':0,
        'label':f"{a['name']}: Demon Emperor’s Second Engine — Bonus Action, spend 8 Qi, Fly 40 feet with Hover and gain Necrotic/Psychic Resistance for 1 minute; once per scene"}]


@hook('journey_command')
def command(session,aid,kind,payload):
    if kind not in ('furnace_engine','furnace_engine_end'):return None
    a=session.state['actors'][aid];s=state(session,aid)
    require(s is not None,'Acquire an actual second furnace first.')
    if kind=='furnace_engine_end':
        require(set(payload)=={'damage_type'} and payload['damage_type'] in ('psychic','necrotic') and s.get('engine_end_pending'),
            'Choose Psychic or Necrotic damage for this ended Engine.')
        end_price(session,aid,payload['damage_type'])
    else:
        require(not payload and any(o['kind']==kind for o in options(session,aid) or []),'The Second Engine is unavailable.')
        require(not any(p.get('subject')==aid and p.get('ordinary_suppressed') and p.get('expires_at',0)>session.clock()
            for p in s.get('environment',[])),'Ordinary Qi is suppressed.')
        a['resources'][f.QI]-=8;s['scene_engine_used']=1
        expiry=session.clock()+60
        s['engine']={'expires_num':expiry.numerator,'expires_den':expiry.denominator,'corruption_gained':0,'breached':0}
        session.emit('SECOND_ENGINE_OPENED',aid,source=f.ENGINE,qi_spent=8,economy='BONUS_ACTION',duration_seconds=60)
    f.publish(session,aid)
    return True


@hook('journey_properties')
def properties(session,aid):
    if active(session,aid) and usable(session,aid):
        s=state(session,aid)
        return {'fly_speed_ft':40,'hover':1,'expiry_num':s['engine']['expires_num'],'expiry_den':s['engine']['expires_den'],
                'expires_at':s['engine']['expires_num']//s['engine']['expires_den']}


@hook('journey_step')
def flying_step(session,aid,old,nxt,regions):
    if active(session,aid) and usable(session,aid):
        return {'flight':1,'supported_kinds':['cliff','river','forest','broken_terrain','water','vertical_surface'],
                'ignore_slowing':['cliff','river','forest','broken_terrain','water','vertical_surface']}


@hook('journey_snapshot_actor')
def transfer(creature,session,aid,engine):
    s=state(session,aid)
    form=f.engine_form(creature)
    if not s or not form:return creature
    from .effect_durations import parse_round
    deadline=parse_round(form.expires_on)
    require(deadline is not None,'The Engine requires its actual counted source clock.')
    order=max(1,len(engine.state.initiative_order))
    remaining=Fraction((deadline[0]-engine.state.round_number)*order+deadline[1]-engine.state.current_slot_index,order)*6
    require(remaining>0,'An expired Engine must resolve its ending before continuation.')
    expires=session.clock()+remaining
    gained=int(form.data.get('continued_corruption',0))+sum(int(e.payload.get('gained',0)) for e in engine.events[int(form.data.get('event_start',0)):]
        if e.event_type=='RESOURCE_GAINED' and e.actor_id==aid and e.payload.get('resource_id')==f.CORRUPTION
        and e.source_definition_id.startswith(f.PREFIX))
    s['engine']={'expires_num':expires.numerator,'expires_den':expires.denominator,
        'corruption_gained':gained,'breached':int(f.condition(creature,'condition:typed.second_furnace_engine_breached') is not None)}
    # Clone only the snapshot. The terminal fight and its replay remain immutable.
    result=creature.model_copy(deep=True)
    result.conditions.pop(form.instance_id,None)
    session.emit('SECOND_ENGINE_CONTINUED',aid,source=f.ENGINE,remaining_num=remaining.numerator,remaining_den=remaining.denominator)
    return result


@hook('match_initialize',priority=50)
def bind(engine):
    for bundle in engine.typed_bundle_documents:
        native=bundle.get('second_furnace_native') or {};stored=native.get('engine')
        actor=engine.state.actors.get(bundle['actor_id'])
        if not stored or not actor or f.engine_form(actor):continue
        remaining=Fraction(stored['expires_num'],stored['expires_den'])-Fraction(native.get('clock_num',native.get('clock_seconds',0)),native.get('clock_den',1))
        if remaining<=0:continue
        from ..typed_executor import clock_expiry
        order=max(1,len(engine.state.initiative_order))
        slots=(remaining*order/6).__ceil__()
        round_delta,slot=divmod(engine.state.current_slot_index+slots,order)
        expiry=f'START_OF_SLOT_AT:{engine.state.round_number+round_delta}:{slot}'
        engine._set_resource_maximum(actor,f.DEVIL,int(f.source_numbers(engine,actor,f.ENGINE)['pb'])+3,f.ENGINE)
        engine._apply_condition(actor,f.FORM,f.ENGINE,actor.entity_id,expires_on=expiry,
            data={'label':'Demon Emperor’s Second Engine continued from the journey','fly_speed_ft':40,'flight_hover':1,
                'rule':{'damage_resistances':['NECROTIC','PSYCHIC']},'event_start':len(engine.events),'retain_removal_data':1,
                'continued_corruption':stored['corruption_gained']})
        if stored['breached'] and not f.condition(actor,'condition:typed.second_furnace_engine_breached'):
            engine._apply_condition(actor,'condition:typed.second_furnace_engine_breached',f.ENGINE,actor.entity_id,
                expires_on='UNTIL_REMOVED',data={'label':'This Engine suffered a Furnace Breach'})


@hook('journey_elapsed')
def elapsed(session,aid,before,seconds,moving):
    s=state(session,aid)
    if not s or not s.get('engine'):return
    if Fraction(s['engine']['expires_num'],s['engine']['expires_den'])>session.clock():return
    end=s.pop('engine')
    a=session.state['actors'][aid]
    pb=int(numbers(a).get('pb',a['bundle']['actor_template'].get('proficiency_bonus',2)))
    a['resources'][f.DEVIL]=min(pb,a['resources'].get(f.DEVIL,0))
    session.emit('SECOND_ENGINE_ENDED',aid,source=f.ENGINE,corruption_gained=end['corruption_gained'],breached=end['breached'])
    if end['corruption_gained']>=2:s['engine_end_pending']=end
    elif end['breached']:make_dormant(a,s)
    f.publish(session,aid)


def make_dormant(actor,s):
    s['dormant']=1;s['rest_completed']=0;s['stabilization_completed']=0
    # Dormancy's native genesis condition is projected from source state.


def end_price(session,aid,kind):
    from ..gate2_rolls import DeterministicRollAuthority
    from ..gate2_runtime_models import DiceSpec
    a=session.state['actors'][aid];s=state(session,aid);ending=s.pop('engine_end_pending')
    seed=session.state['journey_id']+':second_furnace:'+str(len(session.state['events']))
    roll=DeterministicRollAuthority(seed).roll(DiceSpec(count=4,sides=10),actor_id=aid,reason='END_OF_SECOND_ENGINE')
    hp=snapshot(a);amount=roll.total
    # Immunity and Vulnerability still apply. Only Resistance is bypassed.
    template=a['bundle']['actor_template'];rules=[]
    for raw in hp['conditions'].values():rules.append(json.loads(raw).get('data',{}).get('rule',{}))
    if kind.upper() in {str(x).upper() for x in template.get('damage_immunities',[])} or any(kind.upper() in r.get('damage_immunities',[]) for r in rules):amount=0
    elif kind.upper() in {str(x).upper() for x in template.get('damage_vulnerabilities',[])} or any(kind.upper() in r.get('damage_vulnerabilities',[]) for r in rules):amount*=2
    temp=min(hp['temporary_hp'],amount);hp['temporary_hp']-=temp;hp['current_hp']=max(0,hp['current_hp']-(amount-temp))
    if hp['current_hp']==0:hp['life_state']='DYING';a['incapacitated']=1
    if ending['corruption_gained']>=4:a['exhaustion']+=1
    if ending['breached']:make_dormant(a,s)
    session.emit('SECOND_ENGINE_END_PRICE',aid,source=f.ENGINE,damage_type=kind,roll_seed=seed,
        roll=roll.model_dump(mode='json'),damage=amount,temporary_hp_absorbed=temp,
        exhaustion_added=int(ending['corruption_gained']>=4))


@hook('journey_validate_command')
def pending_price(session,aid,kind,payload):
    s=state(session,aid)
    require(not s or not s.get('engine_end_pending') or kind=='furnace_engine_end',
        'Resolve the End of the Engine: choose Psychic or Necrotic damage before continuing.')
