"""A2WEATHER: real service actions, session intents, replay and cold reload."""
import pytest
from tests.test_auto13_weather import (arena, owner_turn, next_owner_turn, commit, action,
    choose_shroud, SHROUD_TALENTS, ME, ALLY, FOE, FOE2, shroud_of)
from combat.ext import weather_fields as wf

TALENTS = [wf.FOUNDATION, wf.CORE, wf.CUT, wf.STORM, wf.SHIFT, wf.SEVERE]


def choices(sign='heat', second=None, level=1):
    def pick(prompt):
        source = prompt['context']['reaction_source_id']
        options = [o['id'] for o in prompt['choice']['options']]
        if source.endswith('gather_sign') or source.endswith('weather_shroud_sign'):
            return [sign]
        if source.endswith('second_sign'):
            return [second] if second else None
        if 'severity_' in source:
            return [str(level)]
        if source.endswith('field_move'):
            return None
        if source.endswith('shift_old'):
            return [sign]
        if source.endswith('shift_new'):
            return [second]
        return options[:1]
    return pick


def next_owner_turn(combat, table, mid, tmp_path, move=None):
    # All other actors in these service fixtures are manual, so END_TURN truly
    # idles them. Keep the field stationary unless this case moves it.
    def choose(prompt):
        if prompt['context']['reaction_source_id'].endswith('weather_field_move'):
            return [move] if move else None
        return choices()(prompt)
    engine=combat._load_session(mid).engine
    if engine.state.current_actor_id==ME:
        cid=next(c.candidate_id for c in engine.legal_candidates() if c.kind.value=='END_TURN')
        commit(combat,table,mid,tmp_path,cid,choose=choose)
    for _ in range(20):
        engine=combat._load_session(mid).engine
        if engine.state.current_actor_id==ME:
            return
        cid=next(c.candidate_id for c in engine.legal_candidates() if c.kind.value=='END_TURN')
        commit(combat,table,mid,tmp_path,cid,choose=choose)
    pytest.fail('owner turn did not arrive')


def gather(combat, table, mid, tmp_path, sign='heat', second=None, level=1, at=(4,6)):
    owner_turn(combat, table, mid, tmp_path, idle=True)
    engine = combat._load_session(mid).engine
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name.startswith('Gather Weather at')
               and c.destination is not None and (c.destination.x,c.destination.y)==at)
    return commit(combat, table, mid, tmp_path, cid, choose=choices(sign,second,level))


@pytest.mark.parametrize('talents,radius,level', [([],20,1),([wf.FOUNDATION],30,2),([wf.FOUNDATION,wf.CORE],60,3)])
def test_field_sign_severity_cost_barrier_and_reload(tmp_path,talents,radius,level):
    combat,table,mid=arena(tmp_path,[wf.CUT,*talents],'field'+str(radius),dc=40,ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'cold',level=level)
    e=combat._load_session(mid).engine
    z=wf.fields(e,e.state.actors[ME])[0]
    assert z.trigger_profile['size_ft']==radius
    assert wf.signs(z)=={'cold':level}
    assert e.state.actors[ME].resources[wf.CP]==100-2-{1:0,2:2,3:4}[level]
    assert wf.severity(e,e.state.actors[ME],e.state.actors[FOE],'cold')==level
    # Membership behind the arena's actual pillar is resolved by the native LoE query.
    from combat.spatial_areas import zone_contains
    for creature in e.state.actors.values():
        assert bool(wf.severity(e,e.state.actors[ME],creature,'cold')) == zone_contains(e,creature,z)


@pytest.mark.parametrize('matching',[False,True])
def test_weather_cut_one_roll_each_turn(tmp_path,matching):
    combat,table,mid=arena(tmp_path,TALENTS,'cut'+str(matching),dc=40,ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'heat' if matching else 'cold')
    next_owner_turn(combat,table,mid,tmp_path)
    before=combat._load_session(mid).engine.state.actors[FOE].current_hp
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),choose=choices('heat'))
    e=combat._load_session(mid).engine
    rolls=[r for r in e.rolls if 'DAMAGE' in str(r.reason) and r.actor_id==ME]
    # Shroud deals the rolled damage plus exactly PB or 2PB, through native defenses.
    damage=[ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED' and FOE in ev.target_ids]
    assert damage
    assert len([r for r in e.rolls if r.reason.startswith('DAMAGE:') and r.actor_id==ME])==1
    roll = next(r for r in reversed(e.rolls) if r.reason.startswith('DAMAGE:') and r.actor_id == ME)
    assert roll.modifier == 2 + e.state.actors[ME].proficiency_bonus * (2 if matching else 1)
    assert 'weather_cut_turn' in e.state.actors[ME].turn_flags
    assert before>e.state.actors[FOE].current_hp
    assert shroud_of(e)[0].data['first_save_done']==1
    first_turn=wf.turn_key(e)
    next_owner_turn(combat,table,mid,tmp_path)
    e=combat._load_session(mid).engine
    rolls=[r for r in e.rolls if r.reason.startswith('DAMAGE:') and r.actor_id==ME]
    assert len(rolls)==2
    assert rolls[-1].modifier==2+e.state.actors[ME].proficiency_bonus*(2 if matching else 1)
    assert wf.turn_key(e)!=first_turn


@pytest.mark.parametrize('matching',[False,True])
def test_weather_cut_suppresses_second_shroud_roll_after_rod_move(tmp_path,matching):
    """The once-per-turn bonus covers every Shroud throw, including a legal Rod move."""
    combat,table,mid=arena(tmp_path,[*TALENTS,*SHROUD_TALENTS],
                            'cut-rod-'+str(matching),dc=40,ask_actors=(ALLY,FOE,FOE2))
    if matching:
        # Wind plus Rain is the shared Thunder-producing storm predicate.
        gather(combat,table,mid,tmp_path,'wind','rain')
        next_owner_turn(combat,table,mid,tmp_path)
    else:
        owner_turn(combat,table,mid,tmp_path,idle=True)

    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),
           choose=choices('thunder'))
    e=combat._load_session(mid).engine
    first=next(r for r in reversed(e.rolls) if r.reason.startswith('DAMAGE:') and r.actor_id==ME)
    assert first.modifier==2+e.state.actors[ME].proficiency_bonus*(2 if matching else 1)
    assert e.state.actors[ME].turn_flags.get('weather_cut_turn')==wf.turn_key(e)

    # Lightning Chooses the Rod moves the same Thunder Shroud and immediately forces its second save/damage roll.
    commit(combat,table,mid,tmp_path,action(combat,mid,'Move Thunder Shroud',FOE2))
    e=combat._load_session(mid).engine
    damage_rolls=[r for r in e.rolls if r.reason.startswith('DAMAGE:') and r.actor_id==ME]
    assert len(damage_rolls)==2
    assert damage_rolls[0].modifier==2+e.state.actors[ME].proficiency_bonus*(2 if matching else 1)
    assert damage_rolls[1].modifier==2, 'the second eligible roll in this owner turn receives no Weather Cut bonus'
    assert not shroud_of(e,FOE) and shroud_of(e,FOE2)


@pytest.mark.parametrize('sign',['cold','heat','rain','thunder','wind'])
def test_severe_first_save_and_optional_rider(tmp_path,sign):
    combat,table,mid=arena(tmp_path,TALENTS,'severe'+sign,dc=40,ask_actors=(ALLY,FOE,FOE2),
                         positions={FOE2:{'x':5,'y':8}} if sign=='wind' else None)
    gather(combat,table,mid,tmp_path,'wind' if sign=='thunder' else sign,'rain' if sign=='thunder' else None)
    next_owner_turn(combat,table,mid,tmp_path)
    before=combat._load_session(mid).engine.state.actors[FOE].position
    prompts=[]
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),choose=choices(sign),prompts=prompts)
    e=combat._load_session(mid).engine
    assert next(r for r in reversed(e.rolls) if r.reason.startswith('SAVE:')).mode=='DISADVANTAGE'
    assert any(p['context']['reaction_source_id'].endswith('weather_severe_rider') for p in prompts)
    if sign=='cold': assert e._effective_speed(e.state.actors[FOE])==0
    if sign=='heat':
        from combat.typed_executor import stored_healing_reductions
        assert stored_healing_reductions(e,e.state.actors[FOE],20)==0
    if sign in ('rain','thunder'):
        from combat.typed_executor import condition_rules
        assert any(r.get('no_reactions') for r in condition_rules(e.state.actors[FOE]))
    if sign=='wind': assert e.state.actors[FOE].position != before


def test_severe_rider_expires_at_owners_next_start_after_cold_reload(tmp_path):
    combat,table,mid=arena(tmp_path,TALENTS,'severe-expiry',dc=40,ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'cold')
    next_owner_turn(combat,table,mid,tmp_path)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),choose=choices('cold'))
    e=combat._load_session(mid).engine
    assert e._effective_speed(e.state.actors[FOE])==0
    next_owner_turn(combat,table,mid,tmp_path)
    e=combat._load_session(mid).engine
    # Cold Cloud Shroud itself may still slow the victim; the optional Severe rider has its own
    # owner-turn deadline and its condition must be gone after the saved-fight reload.
    assert not any(c.condition_id=='condition:typed.weather_severe_cold'
                   for c in e.state.actors[FOE].conditions.values())
    assert combat._load_session(mid).mechanical.replay()['status']=='PASS'


def test_severe_disadvantage_applies_only_to_first_save_after_reload(tmp_path):
    combat,table,mid=arena(tmp_path,TALENTS,'severe-second-save',dc=40,ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'cold')
    next_owner_turn(combat,table,mid,tmp_path)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),choose=choices('cold'))
    e=combat._load_session(mid).engine
    shroud_saves=[r for r in e.rolls if r.reason.startswith('SAVE:') and 'CLOUD_SHROUD' in r.reason.upper()]
    saves_before=len(shroud_saves)
    assert shroud_saves[-1].mode=='DISADVANTAGE'
    # The target's next turn repeats the Shroud save through the table intent path.
    next_owner_turn(combat,table,mid,tmp_path)
    e=combat._load_session(mid).engine
    shroud_saves=[r for r in e.rolls if r.reason.startswith('SAVE:') and 'CLOUD_SHROUD' in r.reason.upper()]
    assert len(shroud_saves)>saves_before
    assert shroud_saves[-1].mode!='DISADVANTAGE'
    assert combat._load_session(mid).mechanical.replay()['status']=='PASS'


def test_dual_storm_birth_and_season_shift(tmp_path):
    combat,table,mid=arena(tmp_path,TALENTS,'storm',dc=40,ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'wind','rain',2)
    next_owner_turn(combat,table,mid,tmp_path)
    prompts=[]
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),choose=choices('thunder'),prompts=prompts)
    e=combat._load_session(mid).engine
    assert any(ev.source_definition_id==wf.STORM and ev.event_type=='DAMAGE_COMMITTED' for ev in e.events)
    assert wf.severity(e,e.state.actors[ME],e.state.actors[ALLY],'thunder')==2
    commit(combat,table,mid,tmp_path,action(combat,mid,'Sudden Shift',ME),choose=choices('rain','cold'))
    assert wf.signs(wf.fields(combat._load_session(mid).engine)[0])=={'wind':2,'cold':2}


def test_shift_cancels_one_sign_and_retains_other_paid_sign_after_reload(tmp_path):
    combat,table,mid=arena(tmp_path,[wf.FOUNDATION,wf.CORE,wf.SHIFT],
                           'shift-retains-second-sign',dc=40,ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'rain','wind',1)
    before_engine=combat._load_session(mid).engine
    before=wf.fields(before_engine,before_engine.state.actors[ME])[0]
    identity=(before.zone_id,before.created_round,before.duration_rounds,before.concentration_link)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Sudden Shift',ME),
           choose=choices('rain','dry'))
    e=combat._load_session(mid).engine
    after=wf.fields(e,e.state.actors[ME])[0]
    assert (after.zone_id,after.created_round,after.duration_rounds,after.concentration_link)==identity
    assert wf.signs(after)=={'wind':1}
    assert wf.severity(e,e.state.actors[ME],e.state.actors[FOE],'thunder')==0
    assert wf.severity(e,e.state.actors[ME],e.state.actors[ALLY],'wind')==1
    assert combat._load_session(mid).mechanical.replay()['status']=='PASS'


def test_storm_birth_allowance_is_per_creature_and_resets_next_round(tmp_path):
    combat,table,mid=arena(tmp_path,[*TALENTS,'TAL_WEATHER_PERSISTENT_SHROUD'],'storm-allowance-round-reset',dc=40,
                         ask_actors=(ALLY,FOE,FOE2))
    # Place a second Shroud before there is a maintained storm. Its failed save
    # is declined once the field is up, leaving its per-creature allowance free.
    owner_turn(combat,table,mid,tmp_path,idle=True)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature) + Persistent Shroud',FOE2),
           choose=choices('thunder'))
    next_owner_turn(combat,table,mid,tmp_path)
    gather(combat,table,mid,tmp_path,'wind','rain',2)

    def decline_charge(prompt):
        if prompt['context']['reaction_source_id'].endswith('weather_storm_charge'):
            return None
        if prompt['context']['reaction_source_id'].endswith('weather_field_move'):
            return None
        return [o['id'] for o in (prompt.get('choice') or {}).get('options',[])[:1]]

    prompts=[]
    target_of=lambda prompt: next((aid for aid in (FOE,FOE2)
                                   if str(prompt['context'].get('checkpoint','')).endswith(aid)),None)
    for _ in range(20):
        e=combat._load_session(mid).engine
        cid=next(c.candidate_id for c in e.legal_candidates() if c.kind.value=='END_TURN')
        commit(combat,table,mid,tmp_path,cid,choose=decline_charge,prompts=prompts)
        if combat._load_session(mid).engine.state.current_actor_id==ME:
            break
    assert combat._load_session(mid).engine.state.current_actor_id==ME
    charges=[p for p in prompts if p['context']['reaction_source_id'].endswith('weather_storm_charge')]
    assert any(target_of(p)==FOE2 for p in charges), [p['context'] for p in charges]
    before=len([ev for ev in combat._load_session(mid).engine.events
                if ev.source_definition_id==wf.STORM and ev.event_type=='DAMAGE_COMMITTED'])
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),
           choose=choices('thunder'),prompts=prompts)
    e=combat._load_session(mid).engine
    assert len([ev for ev in e.events if ev.source_definition_id==wf.STORM
                and ev.event_type=='DAMAGE_COMMITTED'])==before+1

    # End this round. FOE's repeat save must be suppressed, while FOE2 can use
    # its independent allowance. Every committed intent cold reloads/replays.
    for _ in range(20):
        e=combat._load_session(mid).engine
        cid=next(c.candidate_id for c in e.legal_candidates() if c.kind.value=='END_TURN')
        commit(combat,table,mid,tmp_path,cid,prompts=prompts)
        if combat._load_session(mid).engine.state.current_actor_id==ME:
            break
    assert combat._load_session(mid).engine.state.current_actor_id==ME
    e=combat._load_session(mid).engine
    same_round=[p for p in prompts if p['context']['reaction_source_id'].endswith('weather_storm_charge')]
    assert sum(target_of(p)==FOE for p in same_round)==1
    assert sum(target_of(p)==FOE2 for p in same_round)==2

    # FOE fails the same Shroud save in the following round: its allowance has reset.
    for _ in range(12):
        e=combat._load_session(mid).engine
        if e.state.current_actor_id==FOE:
            break
        cid=next(c.candidate_id for c in e.legal_candidates() if c.kind.value=='END_TURN')
        commit(combat,table,mid,tmp_path,cid,prompts=prompts)
    e=combat._load_session(mid).engine
    assert e.state.current_actor_id==FOE
    cid=next(c.candidate_id for c in e.legal_candidates() if c.kind.value=='END_TURN')
    before=len([ev for ev in e.events if ev.source_definition_id==wf.STORM
                and ev.event_type=='DAMAGE_COMMITTED' and FOE in ev.target_ids])
    commit(combat,table,mid,tmp_path,cid,prompts=prompts)
    e=combat._load_session(mid).engine
    after=len([ev for ev in e.events if ev.source_definition_id==wf.STORM
               and ev.event_type=='DAMAGE_COMMITTED' and FOE in ev.target_ids])
    assert after==before+1
    assert combat._load_session(mid).mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('level,dice',[(2,6),(3,8)])
def test_stormlord_bolt_service_and_automatic_enemy_recipients(tmp_path,level,dice):
    combat,table,mid=arena(tmp_path,[*TALENTS,wf.FINGER],f'bolt{level}',dc=40,ask_actors=(ALLY,FOE,FOE2),
                         positions={ALLY:{'x':4,'y':7}})
    gather(combat,table,mid,tmp_path,'wind','rain',level)
    next_owner_turn(combat,table,mid,tmp_path)
    e=combat._load_session(mid).engine
    hp={a:e.state.actors[a].current_hp for a in (ME,ALLY,FOE,FOE2)}
    first=len(e.events)
    combat.set_controller_mode(mid,actor_id=ME,controller_mode='LOCAL_AUTO')
    aims={c.candidate_id:c.destination for c in combat._load_session(mid).engine.legal_candidates()
          if c.display_name.startswith('Stormlord')}
    commit(combat,table,mid,tmp_path)
    e=combat._load_session(mid).engine
    damage=[ev for ev in e.events[first:] if ev.event_type=='DAMAGE_COMMITTED' and 'STORMLORD' in ev.source_definition_id.upper()]
    assert damage, [(ev.event_type,ev.source_definition_id) for ev in e.events[first:]]
    accepted=next(ev for ev in e.events[first:] if ev.event_type=='INTENT_ACCEPTED'
                  and 'STORMLORD' in ev.source_definition_id.upper())
    point=aims[accepted.payload['candidate_id']]
    from combat.typed_executor import in_area
    assert in_area(e,point,point,e.state.actors[ALLY].position,{'shape':'sphere','size_ft':5})
    assert in_area(e,point,point,e.state.actors[ME].position,{'shape':'sphere','size_ft':5})
    roll=next(r for r in reversed(e.rolls) if r.reason.startswith('DAMAGE:') and 'STORMLORD' in r.reason.upper())
    assert len(roll.dice)==dice and roll.expression.startswith(str(dice)+'d10')
    assert all(ev.target_ids[0] in (FOE,FOE2) for ev in damage)
    assert e.state.actors[ALLY].current_hp==hp[ALLY]
    assert e.state.actors[ME].current_hp==hp[ME]
    assert e.state.actors[ME].resources[wf.CP]==100-2-2*{2:2,3:4}[level]-3
    assert e.state.actors[ME].turn_flags['weather_finger_turn']==e.state.actors[ME].turns_started
    assert not any(c.display_name.startswith('Stormlord') for c in e.legal_candidates())


def test_foundation_field_move_is_evented_and_preserves_lifetime(tmp_path):
    combat,table,mid=arena(tmp_path,[wf.FOUNDATION],'move',dc=40,ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'cold')
    e=combat._load_session(mid).engine
    z=wf.fields(e)[0]
    zid,created,duration=z.zone_id,z.created_round,z.duration_rounds
    cp=e.state.actors[ME].resources[wf.CP]
    next_owner_turn(combat,table,mid,tmp_path,move='5,6,0')
    e=combat._load_session(mid).engine
    z=wf.fields(e)[0]
    assert (z.center.x,z.center.y,z.center.z)==(5,6,0)
    assert (z.zone_id,z.created_round,z.duration_rounds)==(zid,created,duration)
    assert e.state.actors[ME].resources[wf.CP]==cp


def test_partial_opposed_overlap_cancels_only_intersection(tmp_path):
    combat,table,mid=arena(tmp_path,[wf.CUT],'overlap',dc=40,ask_actors=(ALLY,FOE,FOE2),
                         positions={ALLY:{'x':1,'y':6},FOE2:{'x':8,'y':6}})
    gather(combat,table,mid,tmp_path,'cold',at=(2,6))
    next_owner_turn(combat,table,mid,tmp_path)
    gather(combat,table,mid,tmp_path,'heat',at=(8,6))
    e=combat._load_session(mid).engine
    assert len(wf.fields(e))==2
    owner=e.state.actors[ME]
    assert wf.severity(e,owner,e.state.actors[FOE],'cold')==0
    assert wf.severity(e,owner,e.state.actors[FOE],'heat')==0
    assert wf.severity(e,owner,e.state.actors[ALLY],'cold')==1
    assert wf.severity(e,owner,e.state.actors[FOE2],'heat')==1


def test_sudden_opposed_shift_reduces_before_establishing_new_sign(tmp_path):
    combat,table,mid=arena(tmp_path,[wf.FOUNDATION,wf.SHIFT],'shift-opposed',dc=40,ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'heat',level=2)
    for expected in (1,0):
        commit(combat,table,mid,tmp_path,action(combat,mid,'Sudden Shift',ME),choose=choices('heat','cold'))
        e=combat._load_session(mid).engine
        if expected:
            assert wf.signs(wf.fields(e)[0])=={'heat':expected}
        else:
            # Equal cancellation ends the now-empty zone on commit/reload.
            assert not wf.fields(e,e.state.actors[ME])
            assert not any(c.display_name.startswith('Sudden Shift') for c in e.legal_candidates())
            assert combat._load_session(mid).mechanical.replay()['status']=='PASS'
            assert e.state.actors[ME].resources[wf.CP]==100-2-2-1-1
        if expected:
            next_owner_turn(combat,table,mid,tmp_path)


def test_rain_mantle_resistance_reads_actual_gathered_field(tmp_path):
    from tests.test_auto13_weather import mantle_chooser
    combat,table,mid=arena(tmp_path,[wf.FOUNDATION],'rain-mantle',dc=40,
                         ask_actors=(ALLY,FOE,FOE2),foe_talents=(wf.FOUNDATION,))
    gather(combat,table,mid,tmp_path,'rain')
    next_owner_turn(combat,table,mid,tmp_path)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Sky Mantle',ALLY),choose=mantle_chooser('rain','active'))
    for _ in range(8):
        e=combat._load_session(mid).engine
        if e.state.current_actor_id==FOE:
            break
        cid=next(c.candidate_id for c in e.legal_candidates() if c.kind.value=='END_TURN')
        commit(combat,table,mid,tmp_path,cid,choose=choices())
    first=len(combat._load_session(mid).engine.events)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',ALLY),choose=choices('heat'))
    e=combat._load_session(mid).engine
    packets=[ev for ev in e.events[first:] if ev.event_type=='DAMAGE_COMMITTED' and ALLY in ev.target_ids]
    assert packets
    assert all(ev.payload['reduced_to']==ev.payload['rolled_or_pending_damage']//2 for ev in packets)


def test_gather_minute_expires_without_ending_later_concentration(tmp_path):
    from tests.test_auto13_weather import mantle_chooser
    combat,table,mid=arena(tmp_path,[wf.FOUNDATION],'expiry',dc=40,maximum_rounds=14,ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'cold')
    created=combat._load_session(mid).engine.state.round_number
    next_owner_turn(combat,table,mid,tmp_path)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Sky Mantle',ME),choose=mantle_chooser('heat','force'))
    while combat._load_session(mid).engine.state.round_number < created+10:
        next_owner_turn(combat,table,mid,tmp_path)
    e=combat._load_session(mid).engine
    assert not wf.fields(e)
    assert e.state.actors[ME].concentration is not None
    assert 'SKY_MANTLE' in e.state.actors[ME].concentration.source_definition_id


def test_matching_bonuses_use_another_creatures_gathered_weather(tmp_path):
    combat,table,mid=arena(tmp_path,[wf.CUT,wf.SEVERE], 'shared-matching',dc=40,
                         ask_actors=(ALLY,FOE,FOE2),foe_talents=(wf.FOUNDATION,))
    # The enemy gathers Heat through its real table action. Our caster has no field.
    for _ in range(20):
        e=combat._load_session(mid).engine
        if e.state.current_actor_id==FOE:
            break
        cid=next(c.candidate_id for c in e.legal_candidates() if c.kind.value=='END_TURN')
        commit(combat,table,mid,tmp_path,cid,choose=choices())
    else:
        pytest.fail('gathering enemy turn did not arrive')
    cid=next(c.candidate_id for c in e.legal_candidates() if c.display_name.startswith('Gather Weather at')
             and c.destination is not None and (c.destination.x,c.destination.y)==(4,6))
    commit(combat,table,mid,tmp_path,cid,choose=choices('heat'))
    next_owner_turn(combat,table,mid,tmp_path)
    e=combat._load_session(mid).engine
    assert not wf.fields(e,e.state.actors[ME])
    assert wf.severity(e,None,e.state.actors[FOE],'heat')==1
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),choose=choices('heat'))
    e=combat._load_session(mid).engine
    roll=next(r for r in reversed(e.rolls) if r.reason.startswith('DAMAGE:') and r.actor_id==ME)
    assert roll.modifier==2+2*e.state.actors[ME].proficiency_bonus
    assert next(r for r in reversed(e.rolls) if r.reason.startswith('SAVE:')
                and 'CLOUD_SHROUD' in r.reason.upper()).mode=='DISADVANTAGE'


def test_repeated_same_sign_fields_do_not_stack_opposition(tmp_path):
    combat,table,mid=arena(tmp_path,[wf.CUT,wf.FOUNDATION],'repeat-category',dc=40,
                         ask_actors=(ALLY,FOE,FOE2))
    for sign,level in [('cold',1),('cold',1),('heat',2)]:
        gather(combat,table,mid,tmp_path,sign,level=level)
        if sign!='heat':
            next_owner_turn(combat,table,mid,tmp_path)
    e=combat._load_session(mid).engine
    assert len(wf.fields(e))==3
    assert wf.severity(e,None,e.state.actors[FOE],'cold')==0
    assert wf.severity(e,None,e.state.actors[FOE],'heat')==1


@pytest.mark.parametrize('cl,reach',[(4,90),(5,120),(10,180)])
def test_sky_bound_realm_reach_casts_beyond_base_range_and_reloads(tmp_path,cl,reach):
    combat,table,mid=arena(tmp_path,[wf.SKY_BOUND],f'reach{cl}',cl=cl,dc=40,
                         ask_actors=(ALLY,FOE,FOE2),positions={ME:{'x':3,'y':8},FOE:{'x':17,'y':8}})
    gather(combat,table,mid,tmp_path,'heat',at=(17,8))
    e=combat._load_session(mid).engine
    actions=[a for a in e.action_catalog.values() if ((a.parameters or {}).get('typed') or {}).get('source')
             in (wf.BASE,'WEATHER_BASE_CLOUD_SHROUD')]
    assert actions and all(a.range_ft==reach for a in actions)
    assert e.grid.distance_ft(e.state.actors[ME].position,e.state.actors[FOE].position)>60
    assert wf.severity(e,None,e.state.actors[FOE],'heat')==1
    next_owner_turn(combat,table,mid,tmp_path)
    before=combat._load_session(mid).engine.state.actors[FOE].current_hp
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),choose=choices('heat'))
    assert combat._load_session(mid).engine.state.actors[FOE].current_hp < before


def test_shift_player_selects_an_older_maintained_field(tmp_path):
    combat,table,mid=arena(tmp_path,[wf.FOUNDATION,wf.SHIFT],'shift-field-choice',dc=40,
                         ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'cold',at=(2,6))
    next_owner_turn(combat,table,mid,tmp_path)
    gather(combat,table,mid,tmp_path,'wind',at=(8,6))
    e=combat._load_session(mid).engine
    first=wf.fields(e)[0].zone_id
    prompts=[]
    def select(prompt):
        if prompt['context']['reaction_source_id'].endswith('weather_field_shift_field'):
            return [first]
        return choices('cold','rain')(prompt)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Sudden Shift',ME),choose=select,prompts=prompts)
    e=combat._load_session(mid).engine
    assert any(p['context']['reaction_source_id'].endswith('weather_field_shift_field') for p in prompts)
    assert wf.signs(wf.fields(e)[0])=={'rain':1}
    assert wf.signs(wf.fields(e)[1])=={'wind':1}
    assert wf.severity(e,e.state.actors[ME],e.state.actors[FOE],'thunder')==1


def test_shift_can_merge_into_a_sign_already_in_the_field(tmp_path):
    combat,table,mid=arena(tmp_path,[wf.FOUNDATION,wf.CORE,wf.SHIFT],'shift-merge',dc=40,
                         ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'wind','rain',2)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Sudden Shift',ME),choose=choices('wind','rain'))
    e=combat._load_session(mid).engine
    assert wf.signs(wf.fields(e)[0])=={'rain':2}
    assert wf.severity(e,e.state.actors[ME],e.state.actors[FOE],'thunder')==0
    assert e.state.actors[ME].resources[wf.CP]==100-2-2-2-1


@pytest.mark.parametrize('old,remaining,new,expected', [
    ('wind', 'rain', 'dry', {}),
    ('wind', 'cold', 'heat', {}),
])
def test_shift_reduces_opposition_against_the_whole_field_and_replays(tmp_path,old,remaining,new,expected):
    combat,table,mid=arena(tmp_path,[wf.FOUNDATION,wf.CORE,wf.SHIFT],f'shift-opposition-{old}',dc=40,
                         ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,old,remaining,2)
    def pick(prompt):
        if prompt['context']['reaction_source_id'].endswith('shift_old'):
            return [old]
        if prompt['context']['reaction_source_id'].endswith('shift_new'):
            return [new]
        return choices()(prompt)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Sudden Shift',ME),choose=pick)
    e=combat._load_session(mid).engine
    if expected:
        actual={k:v for k,v in wf.signs(wf.fields(e)[0]).items() if v}
        assert actual==expected
    else:
        assert not wf.fields(e,e.state.actors[ME])
        assert not any(c.display_name.startswith('Sudden Shift') for c in e.legal_candidates())
    assert combat._load_session(mid).mechanical.replay()['status']=='PASS'


def test_weather_prompts_name_effect_and_cost_in_newcomer_language(tmp_path):
    combat,table,mid=arena(tmp_path,[*TALENTS,wf.SKY_BOUND],'player-words',dc=40,
                         ask_actors=(ALLY,FOE,FOE2))
    gather(combat,table,mid,tmp_path,'cold')
    next_owner_turn(combat,table,mid,tmp_path)
    prompts=[]
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),
           choose=choices('cold'),prompts=prompts)
    severe=next(p for p in prompts if p['context']['reaction_source_id'].endswith('weather_severe_rider'))
    assert 'Speed to 0' in severe['moment'] and 'start of your next turn' in severe['moment']
    assert 'no extra cost' in severe['moment'] and 'Cloud Shroud' in severe['moment']


@pytest.mark.parametrize('mode',['MANUAL','SUGGESTED','MANUAL_AI_BRIDGE'])
def test_storm_birth_pauses_ai_turn_for_player_decline_and_accept(tmp_path,mode):
    combat,table,mid=arena(tmp_path,[wf.FOUNDATION,wf.CORE,wf.STORM],'storm-player-choice-'+mode,dc=40,
                         ask_actors=(ALLY,FOE,FOE2),owner_mode=mode)
    gather(combat,table,mid,tmp_path,'wind','rain',2)
    next_owner_turn(combat,table,mid,tmp_path)
    prompts=[]
    def decline_storm(prompt):
        if prompt['context']['reaction_source_id'].endswith('weather_storm_charge'):
            return None
        return choices('thunder')(prompt)
    commit(combat,table,mid,tmp_path,action(combat,mid,'Cloud Shroud (any creature)',FOE),
           choose=decline_storm,prompts=prompts)
    assert any(p['context']['reaction_source_id'].endswith('weather_storm_charge') for p in prompts)
    combat.set_controller_mode(mid,actor_id=FOE,controller_mode='LOCAL_AUTO')
    # The victim's turn-end save is resolved by AI. Its optional damage question must still be presented to the player.
    for _ in range(30):
        e=combat._load_session(mid).engine
        if e.state.current_actor_id==FOE:
            break
        cid=next(c.candidate_id for c in e.legal_candidates() if c.kind.value=='END_TURN')
        commit(combat,table,mid,tmp_path,cid)
    e=combat._load_session(mid).engine
    event_start=len(e.events)
    for _ in range(12):
        if combat._load_session(mid).engine.state.current_actor_id!=FOE:
            break
        commit(combat,table,mid,tmp_path,choose=decline_storm,prompts=prompts)
    e=combat._load_session(mid).engine
    assert any(p['context']['reaction_source_id'].endswith('weather_storm_charge') for p in prompts)
    assert not any(ev.source_definition_id==wf.STORM and ev.event_type=='DAMAGE_COMMITTED'
                   for ev in e.events[event_start:])
    declined_round=e.state.round_number
    for _ in range(40):
        e=combat._load_session(mid).engine
        if e.state.current_actor_id==FOE and e.state.round_number>declined_round:
            break
        cid=next(c.candidate_id for c in e.legal_candidates() if c.kind.value=='END_TURN')
        commit(combat,table,mid,tmp_path,cid)
    accepted=[]
    for _ in range(12):
        if combat._load_session(mid).engine.state.current_actor_id!=FOE:
            break
        commit(combat,table,mid,tmp_path,prompts=accepted)
    e=combat._load_session(mid).engine
    assert any(p['context']['reaction_source_id'].endswith('weather_storm_charge') for p in accepted)
    assert any(ev.source_definition_id==wf.STORM and ev.event_type=='DAMAGE_COMMITTED'
               for ev in e.events[event_start:])
