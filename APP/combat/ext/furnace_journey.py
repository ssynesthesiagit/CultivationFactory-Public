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
        if p.get('subject')==aid and f.profile_expiry(p)>session.clock() and p.get('second_suppressed'):
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
    if s.get('seed_reinforcement_pending'):
        pb=int(numbers(a).get('pb',2))
        choices=[('temp_hp',f'Gain {pb} Temporary Hit Points'),
            ('advantage','Gain Advantage on one Intimidation or Cultivation Check before the end of your next turn')]
        from ..gate2_runtime_models import Position
        origin=Position.model_validate(a['position'])
        for cell in session.adjacent(aid):
            try:session.step_profile(aid,origin,Position.model_validate(cell))
            except ValueError:continue
            choices.append(('move','Move 5 feet without provoking Opportunity Attacks'))
            break
        return [{'id':'second_furnace_seed_reinforcement:'+kind,'kind':'furnace_seed_reinforcement',
            'payload':{'benefit':kind},'auto_select':0,
            'label':f"{a['name']}: Seed-Fed Reinforcement — {label}; free after Demon Seed Overdraw grants 1 Devil Qi"}
            for kind,label in choices]
    if s.get('engine_end_pending'):
        return [{'id':'second_furnace_end:'+kind,'kind':'furnace_engine_end','payload':{'damage_type':kind},
            'auto_select':0,'label':f"{a['name']}: End of the Engine — take 4d10 {kind.title()} damage that ignores Resistance"}
            for kind in ('psychic','necrotic')]
    if not usable(session,aid) or active(session,aid) or s.get('scene_engine_used'):return None
    available=[]
    qi=int(a['resources'].get(f.QI,0))
    if qi>=8:
        available.append(('ordinary',8,0,0,'spend 8 Qi'))
    # Journey uses the same printed cost alternatives as a combat activation:
    # quote only owned overdraw features, and make the chosen cost explicit.
    cl=int(numbers(a).get('cl',0)); pb=int(numbers(a).get('pb',2))
    owned={row.get('parameters',{}).get('typed',{}).get('source')
           for row in a['bundle'].get('action_catalog',[])}
    owned.update(a['bundle'].get('owned_ids',()))
    corruption=int(a['resources'].get(f.CORRUPTION,0))
    if f.PREFIX+'demon_seed_overdraw' in owned and corruption<10 and qi>=max(0,8-pb):
        available.append(('seed',max(0,8-pb),1,1,f'gain 1 Corruption and 1 Devil Qi to reduce the Qi cost by {pb}'))
    return [{'id':f'{f.ENGINE}:{method}','kind':'furnace_engine',
        'payload':{'payment':method},'auto_select':0,
        'label':f"{a['name']}: Demon Emperor’s Second Engine — Bonus Action, {price_text}; Fly 40 feet with Hover and gain Necrotic/Psychic Resistance for 1 minute; once per scene"}
        for method,price,corrupt,devil,price_text in available]


@hook('journey_command')
def command(session,aid,kind,payload):
    if kind not in ('furnace_engine','furnace_engine_end','furnace_seed_reinforcement'):return None
    a=session.state['actors'][aid];s=state(session,aid)
    require(s is not None,'Acquire an actual second furnace first.')
    if kind=='furnace_seed_reinforcement':
        pending=s.get('seed_reinforcement_pending')
        require(set(payload)=={'benefit'} and pending and payload['benefit'] in ('temp_hp','move','advantage')
                and any(o['kind']==kind and o['payload']==payload for o in options(session,aid) or []),
            'Choose one available Seed-Fed Reinforcement after Demon Seed Overdraw.')
        benefit=payload['benefit'];pb=int(numbers(a).get('pb',2))
        if benefit=='temp_hp':
            hp=snapshot(a);hp['temporary_hp']=max(hp.get('temporary_hp',0),pb)
        elif benefit=='move':
            from ..gate2_runtime_models import Position
            origin=Position.model_validate(a['position'])
            destination=next((cell for cell in session.adjacent(aid)
                if session.grid.distance_cells(origin,Position.model_validate(cell))==1
                and not any(other_id!=aid and other.get('position')==cell for other_id,other in session.state['actors'].items())),None)
            require(destination is not None,'No legal 5-foot destination is available for the Seed-Fed step.')
            session.move(aid,{'path':[destination]})
        else:
            expiry=session.clock()+6
            s.setdefault('continuation_conditions',[]).append({'subject':aid,'kind':'seed_advantage','cultivation':1,
                'expires_num':expiry.numerator,'expires_den':expiry.denominator,'expires_at':expiry.__ceil__()})
        s.pop('seed_reinforcement_pending')
        session.emit('SEED_FED_REINFORCEMENT',aid,source=f.SEED,benefit=benefit)
        f.publish(session,aid)
        return True
    if kind=='furnace_engine_end':
        require(set(payload)=={'damage_type'} and payload['damage_type'] in ('psychic','necrotic') and s.get('engine_end_pending'),
            'Choose Psychic or Necrotic damage for this ended Engine.')
        end_price(session,aid,payload['damage_type'])
    else:
        require(set(payload)=={'payment'} and any(o['kind']==kind and o['payload']==payload for o in options(session,aid) or []),'The Second Engine payment is unavailable.')
        require(not any(p.get('subject')==aid and p.get('ordinary_suppressed') and f.profile_expiry(p)>session.clock()
            for p in s.get('environment',[])),'Ordinary Qi is suppressed.')
        payment=payload['payment']; qi_cost=8
        if payment=='seed':
            pb=int(numbers(a).get('pb',2)); qi_cost=max(0,8-pb)
            a['resources'][f.CORRUPTION]=a['resources'].get(f.CORRUPTION,0)+1
        a['resources'][f.QI]-=qi_cost;s['scene_engine_used']=1
        expiry=session.clock()+60
        s['engine']={'expires_num':expiry.numerator,'expires_den':expiry.denominator,'corruption_gained':int(payment=='seed'),'breached':0}
        if payment=='seed':
            pb=int(numbers(a).get('pb',2))
            a['resources'][f.DEVIL]=min(pb,a['resources'].get(f.DEVIL,0)+1)
            s['seed_reinforcement_pending']=1
        session.emit('SECOND_ENGINE_OPENED',aid,source=f.ENGINE,qi_spent=qi_cost,economy='BONUS_ACTION',duration_seconds=60,payment=payment)
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
    for key,held in list(result.conditions.items()):
        if held.condition_id=='condition:typed.second_furnace_engine_breached':result.conditions.pop(key)
    session.emit('SECOND_ENGINE_CONTINUED',aid,source=f.ENGINE,remaining_num=remaining.numerator,remaining_den=remaining.denominator)
    return result


@hook('match_initialize',priority=-50)
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


@hook('match_initialize',priority=-49)
def bind_seed_advantage(engine):
    """Carry a chosen Journey Seed-Fed check benefit into its next table turn."""
    for bundle in engine.typed_bundle_documents:
        native=bundle.get('second_furnace_native') or {}
        actor=engine.state.actors.get(bundle['actor_id'])
        if not actor or f.condition(actor,'condition:typed.second_furnace_advantage'):continue
        clock=Fraction(native.get('clock_num',native.get('clock_seconds',0)),native.get('clock_den',1))
        for held in native.get('continuation_conditions',[]):
            if held.get('kind')!='seed_advantage' or Fraction(held['expires_num'],held['expires_den'])<=clock:continue
            engine._apply_condition(actor,'condition:typed.second_furnace_advantage',f.SEED,actor.entity_id,
                expires_on=f'END_OF_SOURCE_TURN_AT:{actor.turns_started+1}',
                data={'cultivation':1,'label':'Advantage on one Intimidation or Cultivation Check before the end of your next turn'})
            break


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
    seed_pending=[owner for owner in session.state['actors'] if (state(session,owner) or {}).get('seed_reinforcement_pending')]
    require(not seed_pending or aid in seed_pending and kind=='furnace_seed_reinforcement',
        'Choose the Seed-Fed Reinforcement before continuing the journey.')
    pending=[owner for owner in session.state['actors'] if (state(session,owner) or {}).get('engine_end_pending')]
    require(not pending or aid in pending and kind=='furnace_engine_end',
        'Resolve the End of the Engine: choose Psychic or Necrotic damage before continuing.')


@hook('journey_initialize',priority=100)
def reconcile_maintained_engine(session,aid):
    a=session.state['actors'][aid];s=state(session,aid)
    if s and s.get('engine') and not usable(session,aid):
        now=session.clock()
        s['engine']['expires_num']=now.numerator;s['engine']['expires_den']=now.denominator
        elapsed(session,aid,now,0,())


@hook('journey_time_gate')
def ending_boundary(session,seconds):
    """Use the Asset owner's shared time gate for a mandatory price decision."""
    for aid in session.state['actors']:
        s=state(session,aid)
        if not s:continue
        require(not s.get('engine_end_pending'),'Choose the End of the Engine damage type before time advances.')
        form=s.get('engine')
        if not form or form['corruption_gained']<2:continue
        remaining=Fraction(form['expires_num'],form['expires_den'])-session.clock()
        require(seconds<=remaining,
            f"{session.state['actors'][aid]['name']}: advance only {remaining} seconds to the Engine ending, then choose Psychic or Necrotic damage.")


@hook('flight')
def initializing_engine_flight(engine,actor):
    """Preserve actual continued flight while native genesis assembles its rows.

    Native condition events settle falling immediately. A real stored Engine
    supplies its capability before the organ and form finish binding; the hook
    stops at MATCH_CREATED and cannot resurrect a dispelled/ended form.
    """
    if any(e.event_type=='MATCH_CREATED' for e in (getattr(engine,'events',()) or ())):return
    native=next((b.get('second_furnace_native') or {} for b in (getattr(engine,'typed_bundle_documents',()) or ()) if b['actor_id']==actor.entity_id),{})
    form=native.get('engine')
    if not form or not native.get('access_receipt') or native.get('organ_removed') or native.get('dormant') or not f.owns(engine,actor,f.ENGINE):return
    now=Fraction(native.get('clock_num',native.get('clock_seconds',0)),native.get('clock_den',1))
    if f.profile_expiry(form)<=now:return
    cl=int(f.source_numbers(engine,actor,f.ENGINE)['cl'])
    for profile in native.get('environment',[]):
        if profile['subject']!=actor.entity_id or f.profile_expiry(profile)<=now or not profile.get('second_suppressed') or profile.get('interrupt_next_activation'):continue
        if profile.get('ordinary_suppressed') and profile['source_cl']<cl and not profile.get('multiple_systems') and not profile.get('complete'):continue
        return
    return {'fly_speed_ft':40,'flight_hover':1,'source_definition_id':f.ENGINE}
