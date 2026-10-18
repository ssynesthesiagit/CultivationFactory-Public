"""Cloud Walker native table regression; no model/network transports."""
from combat.flight import horizontal_jump_feet, profile
from combat.gate2_runtime_models import Position
from tests.worker2_support import fixture, reload, candidate, settle, turn, OWNER, ALLY, FOE
from combat.ext.qi_subpaths_five import CLOUD


def verify(combat, mid):
    session = combat._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_feather_long_jump_uses_tripled_distance(tmp_path):
    c,t,mid=fixture(tmp_path,[],cl=3,owner_features=[CLOUD+'light_as_a_feather'],ask=False)
    e=reload(tmp_path,mid);actor=e.state.actors[OWNER]
    assert horizontal_jump_feet(e,actor)==actor.strength_score//2*3
    assert horizontal_jump_feet(e,e.state.actors[ALLY])==e.state.actors[ALLY].strength_score//2
    from combat.flight import jump_steps
    assert jump_steps(e,actor,[actor.position]) > jump_steps(e,e.state.actors[ALLY],[e.state.actors[ALLY].position])
    jumps=[x for x in e.legal_candidates() if x.kind.value=='MOVE'
           and x.metadata.get('movement_mode')=='jump' and x.destination.z==0
           and e.grid.distance_ft(actor.position,x.destination)>=15]
    assert jumps
    settle(t,mid,jumps[0].candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].position==jumps[0].destination
    verify(c,mid)


def test_leap_alone_does_not_pay_companion_qi(tmp_path):
    c,t,mid=fixture(tmp_path,[],cl=14,owner_features=[CLOUD+'heavenly_leap'],ask=True)
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    settle(t,mid,candidate(c,mid,'Heavenly Leap').candidate_id,
           choices={'choice:needle.cloud_leap_destination':'first'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==before-3
    assert not e.state.actors[OWNER].bonus_action_available
    assert not any(ev.event_type=='TELEPORT_COMMITTED' for ev in e.events)
    verify(c,mid)


def test_cloud_step_stationary_end_descends_and_lands_standing(tmp_path):
    c,t,mid=fixture(tmp_path,[],cl=6,owner_features=[CLOUD+'cloud_step'],ask=True)
    settle(t,mid,candidate(c,mid,'Cloud Step').candidate_id)
    e=reload(tmp_path,mid)
    move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination==Position(x=3,y=6,z=3))
    settle(t,mid,move.candidate_id)
    turn(t,mid,ALLY);turn(t,mid,OWNER)
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position.z==0
    assert not any(x.condition_id.endswith('prone') for x in e.state.actors[OWNER].conditions.values())
    verify(c,mid)


def test_immortal_free_leap_still_costs_bonus_action(tmp_path):
    c,t,mid=fixture(tmp_path,[],cl=18,owner_features=[CLOUD+'cloud_immortal',CLOUD+'heavenly_leap'],ask=True)
    settle(t,mid,candidate(c,mid,'Cloud Immortal').candidate_id)
    turn(t,mid,ALLY);turn(t,mid,OWNER)
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    settle(t,mid,candidate(c,mid,'Heavenly Leap').candidate_id,
           choices={'choice:needle.cloud_leap_destination':'first'})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==before
    assert profile(e,e.state.actors[OWNER]).hover
    assert not e.state.actors[OWNER].bonus_action_available
    verify(c,mid)


def journey_game(tmp_path, owner_mode='MANUAL', companion_mode='MANUAL', map_walls=(),companion_position=None):
    import json,zipfile
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT,sheet
    for pid,features in [('walker',[CLOUD+'wind_walk']),('companion',[])]:
        doc=sheet([],cl=10 if pid=='walker' else 1,name=pid)
        doc.setdefault('path_and_subpath',{})['path_feature_record_ids']=features
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    aid,bid='actor:factory.walker','actor:factory.companion'
    companion_position=companion_position or {'x':4,'y':6}
    def cold():return CombatService(ROOT,tmp_path)
    c=cold();c.tabletop_maps.save({'display_name':'Wind Walk ritual','width_squares':12,'height_squares':14,
                                  'walls':list(map_walls),'starts':{'team1':[[3,6]],'team2':[[4,6]]}})
    state=c.create_journey(project_ids=['walker','companion'],arena_id='battlefield:map.wind-walk-ritual',
            positions={aid:{'x':3,'y':6},bid:companion_position},base_paces={aid:18000,bid:18000},
            control_modes={aid:owner_mode,bid:companion_mode})
    jid=state['journey_id']
    def act(kind,payload=None,actor=aid):
        c=cold();state=c.journey_state(jid)
        return c.journey_act(jid,state['revision'],actor,kind,payload or {})
    return cold,jid,act,aid,bid


def test_wind_ritual_recipient_consent_and_native_combat_continuation(tmp_path):
    from combat.tabletop_service import TabletopService
    FORM='condition:typed.cloud_walker_form'
    cold,jid,act,aid,bid=journey_game(tmp_path)
    before=cold().journey_state(jid)['actors'][aid]['resources']['resource:core.qi']
    act('cloud_wind_begin')
    import pytest
    with pytest.raises(ValueError):act('cloud_wind_finish')
    act('wait',{'seconds':600})
    act('cloud_wind_invite',{'target_id':bid})
    assert not cold().journey_state(jid)['actors'][bid]['travel_effects']
    with pytest.raises(ValueError):act('cloud_wind_finish')
    act('cloud_wind_reply',{'caster_id':aid,'accept':True},bid)
    state=act('cloud_wind_finish')
    assert state['seconds']==600 and state['actors'][aid]['resources']['resource:core.qi']==before-5
    assert CLOUD+'wind_walk' in state['actors'][bid]['travel_effects']
    act('move',{'path':[{'x':3,'y':6,'z':1}]})
    state=cold().journey_state(jid)
    result=cold().journey_start_combat(jid,state['revision'],{aid:'team:a',bid:'team:b'},
                positions={aid:{'x':3,'y':6},bid:{'x':4,'y':6}})
    c=cold();mid=result['match_id'];t=TabletopService(c,tmp_path)
    turn(t,mid,bid)
    e=c._load_session(mid).engine
    assert profile(e,e.state.actors[bid]).speed_ft==40 and profile(e,e.state.actors[bid]).hover
    assert any(x.condition_id==FORM for x in e.state.actors[bid].conditions.values())
    assert not any('Attack'==x.display_name for x in e.legal_candidates())
    end=next(x for x in e.legal_candidates() if x.display_name=='End Wind Walk (Bonus Action)')
    settle(t,mid,end.candidate_id)
    e=cold()._load_session(mid).engine
    assert not any(x.condition_id==FORM for x in e.state.actors[bid].conditions.values())
    assert not e.state.actors[bid].bonus_action_available
    assert profile(e,e.state.actors[aid]).speed_ft==40
    verify(cold(),mid)


def test_occupied_cloud_end_displaces_and_deals_force_through_table(tmp_path):
    c,t,mid=fixture(tmp_path,[],cl=18,owner_features=[CLOUD+'cloud_immortal'],ask=True)
    settle(t,mid,candidate(c,mid,'Cloud Immortal').candidate_id)
    e=reload(tmp_path,mid)
    move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination==e.state.actors[FOE].position)
    settle(t,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position==e.state.actors[FOE].position
    before=e.state.actors[OWNER].current_hp
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position!=e.state.actors[FOE].position
    roll=next(r for r in e.rolls if r.reason=='CLOUD_IMMORTAL_OCCUPIED_FORCE')
    assert roll.expression=='4d10+0'
    assert e.state.actors[OWNER].current_hp==before-roll.total
    assert not any(ev.event_type=='TELEPORT_COMMITTED' for ev in e.events)
    verify(c,mid)


def test_unowned_creature_cannot_end_in_another_creature(tmp_path):
    c,t,mid=fixture(tmp_path,[],cl=18,ask=False)
    e=reload(tmp_path,mid)
    assert not any(x.kind.value=='MOVE' and x.destination==e.state.actors[FOE].position for x in e.legal_candidates())
    assert not any(x.source_definition_id==CLOUD+'wind_walk'+'#end' for x in e.legal_candidates())
    verify(c,mid)


import pytest


@pytest.mark.parametrize('accept',[True,False])
def test_leap_companion_consent_cost_and_committed_physical_route(tmp_path,accept):
    c,t,mid=fixture(tmp_path,[],cl=14,owner_features=[CLOUD+'heavenly_leap'],ask=True,named=True)
    settle(t,mid,candidate(c,mid,'Heavenly Leap').candidate_id,choices={
        'choice:needle.cloud_leap_destination':['cell:3,3'],
        'choice:needle.cloud_leap_companion':[ALLY],
        'choice:needle.fact_admission.heavenly_leap_carry':['accept' if accept else 'refuse'],
        'choice:needle.cloud_leap_landing':['cell:4,3']})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==100-(5 if accept else 3)
    assert e.state.actors[OWNER].position==Position(x=3,y=3)
    assert e.state.actors[ALLY].position==(Position(x=4,y=3) if accept else Position(x=4,y=6))
    from combat.fact_consent_admission import combat_records
    admitted=combat_records(e,e.state.actors[OWNER],source=CLOUD+'heavenly_leap',kind='heavenly_leap_carry')
    assert len(admitted)==1 and admitted[0]['value']==('accept' if accept else 'refuse')
    assert admitted[0]['authority']==ALLY
    assert not combat_records(e,e.state.actors[FOE],source=CLOUD+'heavenly_leap')
    if accept:
        moves=[ev for ev in e.events if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==ALLY]
        assert len(moves)>=3
    assert not any(ev.event_type=='TELEPORT_COMMITTED' for ev in e.events)
    assert not any(x.condition_id in ('condition:typed.cloud_walker_carry','condition:typed.cloud_walker_leap')
                   for actor in e.state.actors.values() for x in actor.conditions.values())
    verify(c,mid)


def test_ai_ritual_waits_for_manual_recipient(tmp_path):
    cold,jid,act,aid,bid=journey_game(tmp_path,owner_mode='LOCAL_AUTO')
    act('cloud_wind_begin');act('wait',{'seconds':600})
    state=act('cloud_wind_invite',{'target_id':bid})
    assert cold().journey_auto_step(jid,state['revision'],aid)==state
    assert cold().journey_state(jid)==state
    act('cloud_wind_reply',{'caster_id':aid,'accept':False},bid)
    state=act('cloud_wind_finish')
    assert CLOUD+'wind_walk' not in state['actors'][bid]['travel_effects']


def test_ai_recipient_answers_own_ritual_offer_before_moving(tmp_path):
    cold,jid,act,aid,bid=journey_game(tmp_path,companion_mode='LOCAL_AUTO')
    act('cloud_wind_begin');act('wait',{'seconds':600})
    state=act('cloud_wind_invite',{'target_id':bid})
    after=cold().journey_auto_step(jid,state['revision'],bid)
    assert after['actors'][bid]['position']==state['actors'][bid]['position']
    assert after['actors'][aid]['cloud_ritual']['invitations'][bid]=='accept'
    state=act('cloud_wind_finish')
    assert CLOUD+'wind_walk' in state['actors'][bid]['travel_effects']


@pytest.fixture(scope='module',autouse=True)
def record_tested_sources(request, tmp_path_factory):
    """Compact provenance for the actual source snapshot that a queued job ran."""
    from pathlib import Path
    import hashlib,json
    app=Path(__file__).resolve().parents[1]
    paths=['combat/asset_anchor_runtime.py','combat/ext/objects.py','combat/tabletop_service.py','combat/fact_consent_admission.py','combat/ext/fact_consent_admission.py','combat/ext/cloud_walker_environment.py','combat/tabletop.py','combat/falling.py','combat/voluntary_movement.py','combat/ext/movement_clock.py','combat/ext/cloud_walker.py','combat/ext/qi_subpaths_five.py',
           'combat/creature_passage.py','combat/flight.py','combat/granted_movement.py',
           'combat/gate2_engine.py','combat/gate5_service.py','combat/journey.py',
           'combat/armour.py','combat/weapon_delivery.py','combat/ext/shield_wielding.py',
           'combat/ext/hand_occupancy.py','combat/roof_movement.py',
           'authority/Tianxia_Typed_Mechanics_Authority_R1.json']
    receipt={path:hashlib.sha256((app/path).read_bytes()).hexdigest() if (app/path).is_file() else None
             for path in paths}
    evidence=tmp_path_factory.getbasetemp()/'cloud-source-evidence'
    evidence.mkdir(parents=True,exist_ok=True)
    name=Path(request.config.getoption('basetemp')).name
    (evidence/(name+'-source.json')).write_text(json.dumps(receipt,indent=2)+'\n')


def test_invalid_jump_bonus_rejected_by_native_menu(tmp_path,monkeypatch):
    from tests.test_lock_choices import install
    c,t,mid=fixture(tmp_path,[],cl=3,owner_features=[CLOUD+'light_as_a_feather'],ask=False)
    e=reload(tmp_path,mid)
    install(monkeypatch,'jump_distance_bonus_ft',lambda *args:'three')
    with pytest.raises(ValueError,match='positive integer'):
        e.legal_candidates()


def test_cloud_immortal_force_penalty_ignores_feather_and_zero_hp_ends_all_benefits(tmp_path):
    from combat.creature_passage import permission
    features=[CLOUD+'light_as_a_feather',CLOUD+'cloud_immortal']
    c,t,mid=fixture(tmp_path,[],cl=18,owner_features=features,ask=True,seed='CLOUD-IMMORTAL-ENDING')
    settle(t,mid,candidate(c,mid,'Cloud Immortal').candidate_id)
    for _ in range(9):
        e=reload(tmp_path,mid)
        move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination==e.state.actors[FOE].position)
        settle(t,mid,move.candidate_id)
        before=reload(tmp_path,mid).state.actors[OWNER].current_hp
        settle(t,mid,t.state(mid)['menu']['end_turn'])
        e=reload(tmp_path,mid)
        force=next(r for r in reversed(e.rolls) if r.reason=='CLOUD_IMMORTAL_OCCUPIED_FORCE')
        assert e.state.actors[OWNER].current_hp==max(0,before-force.total)
        if e.state.actors[OWNER].current_hp==0:
            break
        turn(t,mid,OWNER)
    actor=e.state.actors[OWNER]
    assert actor.current_hp==0
    assert not profile(e,actor).speed_ft and not profile(e,actor).hover
    assert permission(e,actor,e.state.actors[FOE]) is None
    assert not any(x.condition_id=='condition:typed.cloud_walker_form' for x in actor.conditions.values())
    verify(c,mid)


def test_paid_wind_survives_finished_journey_and_two_encounters(tmp_path):
    from combat.tabletop_service import TabletopService
    cold,jid,act,aid,bid=journey_game(tmp_path)
    act('cloud_wind_begin');act('wait',{'seconds':600});state=act('cloud_wind_finish')
    initial=state['actors'][aid]['resources']['resource:core.qi']
    for _ in range(2):
        state=cold().journey_state(jid)
        match=cold().journey_start_combat(jid,state['revision'],{aid:'team:a',bid:'team:b'},maximum_rounds=1)
        mid=match['match_id']
        for _ in range(6):
            c=cold()
            if c._load_session(mid).engine.state.terminal_result is not None:
                break
            t=TabletopService(c,tmp_path)
            settle(t,mid,t.state(mid)['menu']['end_turn'])
        verify(cold(),mid)
        state=cold().journey_state(jid)
        state=cold().journey_resume(jid,state['revision'])
        assert CLOUD+'wind_walk' in state['actors'][aid]['travel_effects']
        assert state['actors'][aid]['resources']['resource:core.qi']==initial
    state=act('finish')
    new=cold().create_journey(project_ids=['walker','companion'],arena_id='battlefield:map.wind-walk-ritual',
        positions={aid:{'x':3,'y':6},bid:{'x':4,'y':6}},base_paces={aid:18000,bid:18000})
    jid2=new['journey_id']
    assert CLOUD+'wind_walk' in new['actors'][aid]['travel_effects']
    assert new['actors'][aid]['resources']['resource:core.qi']==initial
    new=cold().journey_act(jid2,new['revision'],aid,'cloud_wind_end',{})
    new=cold().journey_act(jid2,new['revision'],aid,'finish',{})
    third=cold().create_journey(project_ids=['walker','companion'],arena_id='battlefield:map.wind-walk-ritual',
        positions={aid:{'x':3,'y':6},bid:{'x':4,'y':6}},base_paces={aid:18000,bid:18000})
    assert CLOUD+'wind_walk' not in third['actors'][aid]['travel_effects']


def authored_environment(tmp_path, *, surfaces=(), barriers=(), fields=(), objects=()):
    """Real owner-map collection, normalization, persistence and sealing path."""
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from combat.tabletop import to_battlefield
    source='tianxia.subpath.qi.cloud_walker'
    c=CombatService(ROOT,tmp_path)
    c.tabletop_maps.save({'display_name':'Declared Cloud Walker scene','width_squares':12,'height_squares':14,
        'walls':[],'objects':list(objects),'starts':{'team1':[[3,6]],'team2':[[6,6]]},'source_data':{source:{
            'source':source,'authority':'map_owner','declared_by':'Scene GM','expires':'scene',
            'bodies':{OWNER:{'body_weight_lb':160,'width_inches':18}},
            'surfaces':list(surfaces),'barriers':list(barriers),'fields':list(fields)}}})
    saved=CombatService(ROOT,tmp_path).tabletop_maps.get('declared-cloud-walker-scene')
    return to_battlefield(saved)


@pytest.mark.parametrize('trigger',['weight','qi_pressure'])
def test_authored_fragile_footing_and_actual_end_weight(tmp_path,trigger):
    surface={'id':'hanging-cloth','kind':'hanging_cloth','z':1,'capacity_lb':1,
        'cells':[[x,y] for x in range(12) for y in range(14)],'fragile':True,'trigger':trigger}
    arena=authored_environment(tmp_path,surfaces=[surface])
    c,t,mid=fixture(tmp_path,[],cl=3,owner_features=[CLOUD+'light_as_a_feather'],ask=False,battlefield=arena)
    e=reload(tmp_path,mid)
    jump=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.metadata.get('movement_mode')=='jump'
              and x.destination==Position(x=3,y=5,z=1))
    settle(t,mid,jump.candidate_id)
    e=reload(tmp_path,mid)
    failures=[ev for ev in e.events if ev.event_type=='PASSIVE_TRIGGERED' and ev.payload.get('cloud_surface_failed')==1]
    if trigger=='qi_pressure':
        assert failures and e.state.actors[OWNER].position.z==0
    else:
        assert not failures and e.state.actors[OWNER].position.z==1
        settle(t,mid,t.state(mid)['menu']['end_turn'])
        assert reload(tmp_path,mid).state.actors[OWNER].position.z==0
    verify(c,mid)


@pytest.mark.parametrize('opening',[0,'1/2',1])
def test_native_mist_narrow_opening_and_airtight_boundary(tmp_path,opening):
    barrier={'axis':'x','plane':4,'low':[0,0],'high':[13,200],
             'opening_inches':opening,'total_cover':False,'sealed_formation':False}
    arena=authored_environment(tmp_path,barriers=[barrier])
    c,t,mid=fixture(tmp_path,[],cl=18,owner_features=[CLOUD+'cloud_immortal'],ask=False,battlefield=arena)
    e=reload(tmp_path,mid)
    assert not any(x.kind.value=='MOVE' and x.destination.x>=4 for x in e.legal_candidates())
    settle(t,mid,candidate(c,mid,'Cloud Immortal').candidate_id)
    e=reload(tmp_path,mid)
    rows=[x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination==Position(x=4,y=5)]
    from fractions import Fraction
    assert bool(rows)==(Fraction(opening)>=1)
    if rows:
        settle(t,mid,rows[0].candidate_id)
        assert reload(tmp_path,mid).state.actors[OWNER].position==Position(x=4,y=5)
    verify(c,mid)


def test_native_ritual_refusal_supersedes_earlier_acceptance(tmp_path):
    cold,jid,act,aid,bid=journey_game(tmp_path)
    act('cloud_wind_begin');act('wait',{'seconds':600})
    act('cloud_wind_invite',{'target_id':bid})
    act('cloud_wind_reply',{'caster_id':aid,'accept':True},bid)
    act('cloud_wind_reply',{'caster_id':aid,'accept':False},bid)
    state=act('cloud_wind_finish')
    assert CLOUD+'wind_walk' in state['actors'][aid]['travel_effects']
    assert CLOUD+'wind_walk' not in state['actors'][bid]['travel_effects']
    from combat.fact_consent_admission import read
    history=cold().journeys.load(jid).state['fact_consent_admission']
    assert len(history)==2 and [row['value'] for row in history]==[1,0]
    assert all(row['authority']==bid and row['readers']==[aid] for row in history)
    assert not any('value' in event for event in state['events'] if event['kind']=='FACT_DECLARED')


def test_wind_willing_incapacitated_recipient_is_not_assumed_unwilling(tmp_path):
    cold,jid,act,aid,bid=journey_game(tmp_path)
    act('cloud_wind_begin');act('wait',{'seconds':600})
    act('incapacitated',{'value':True},bid)
    act('cloud_wind_invite',{'target_id':bid})
    act('cloud_wind_reply',{'caster_id':aid,'accept':True},bid)
    state=act('cloud_wind_finish')
    assert CLOUD+'wind_walk' in state['actors'][bid]['travel_effects']
    menu=cold().journey_menu(jid,bid) if hasattr(cold(),'journey_menu') else cold().journeys.load(jid).menu(bid)
    assert not any(row['kind']=='cloud_wind_end' for row in menu['options'])


@pytest.mark.parametrize('point,bad,message',[
    ('support_override','stable','support_override'),
    ('movement_edge_allowed','yes','movement_edge_allowed'),
    ('equipment_use_allowed',1,'equipment_use_allowed')])
def test_native_query_rejects_malformed_general_provider(tmp_path,monkeypatch,point,bad,message):
    from tests.test_lock_choices import install
    c,t,mid=fixture(tmp_path,[],cl=3,owner_features=[CLOUD+'light_as_a_feather'],ask=False,
        owner_kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.fu','name':'Fu','quantity':1},
                                        {'item_id':'tianxia.mortal.armor.shield','name':'Shield','quantity':1}]}})
    e=reload(tmp_path,mid)
    install(monkeypatch,point,lambda *args:bad)
    with pytest.raises(ValueError,match=message):e.legal_candidates()


def test_native_source_continuation_rejects_binary_floats_atomically(tmp_path,monkeypatch):
    from tests.test_lock_choices import install
    cold,jid,act,aid,bid=journey_game(tmp_path)
    before=cold().journey_state(jid)
    def invalid(session,actor):
        session.state['actors'][actor]['source_states']={'guard':{'invalid':1.5}}
    install(monkeypatch,'journey_state_changed',invalid)
    with pytest.raises(ValueError,match='Source continuation state'):act('incapacitated',{'value':True})
    assert cold().journey_state(jid)==before


def test_feather_odd_strength_does_not_round_before_tripling(tmp_path):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    document=sheet([CLOUD+'light_as_a_feather'],cl=3,score=17)
    bundle=compile_character(document,actor_id=OWNER)
    c,t,mid=fixture(tmp_path,[],cl=3,owner_bundle=bundle,ask=False)
    e=reload(tmp_path,mid);actor=e.state.actors[OWNER]
    assert horizontal_jump_feet(e,actor)==24
    # 24 ft of jump reach covers four whole 5-ft squares (20 ft), never 25 ft.
    jump=max((row for row in e.legal_candidates() if row.kind.value=='MOVE'
        and row.metadata.get('movement_mode')=='jump' and row.destination.z==0),
        key=lambda row:e.grid.distance_ft(actor.position,row.destination))
    assert e.grid.distance_ft(actor.position,jump.destination)==20
    settle(t,mid,jump.candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].position==jump.destination
    verify(c,mid)


@pytest.mark.parametrize('remaining',[1,4])
def test_wind_partial_round_duration_is_not_rounded_up_on_combat_entry(tmp_path,remaining):
    from combat.tabletop_service import TabletopService
    cold,jid,act,aid,bid=journey_game(tmp_path)
    act('cloud_wind_begin');act('wait',{'seconds':600});act('cloud_wind_finish')
    state=act('wait',{'seconds':3600-remaining})
    result=cold().journey_start_combat(jid,state['revision'],{aid:'team:a',bid:'team:b'},maximum_rounds=3)
    mid=result['match_id'];t=TabletopService(cold(),tmp_path)
    initial=cold()._load_session(mid).engine
    assert profile(initial,initial.state.actors[aid]).hover
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=cold()._load_session(mid).engine
    assert bool(next((c for c in e.state.actors[aid].conditions.values() if c.condition_id=='condition:typed.cloud_walker_form'),None))==(remaining>3)
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=cold()._load_session(mid).engine
    assert not any(c.condition_id=='condition:typed.cloud_walker_form' for c in e.state.actors[aid].conditions.values())
    verify(cold(),mid)


def test_heavenly_leap_physical_segment_does_not_grant_flight_or_hover(tmp_path,monkeypatch):
    from tests.test_lock_choices import install
    observed=[]
    def inspect(engine,mover,receipt):
        if mover.entity_id==OWNER:
            cap=profile(engine,mover);observed.append((cap.speed_ft,cap.hover))
    c,t,mid=fixture(tmp_path,[],cl=14,owner_features=[CLOUD+'heavenly_leap'],ask=True)
    install(monkeypatch,'movement_progress_committed',inspect)
    settle(t,mid,candidate(c,mid,'Heavenly Leap').candidate_id,
           choices={'choice:needle.cloud_leap_destination':['cell:3,3,2']})
    assert observed and all(speed==0 and not hover for speed,hover in observed)
    verify(c,mid)


@pytest.mark.parametrize('kind,opposing_cl',[('gravity',17),('gravity',10),('spatial',17)])
def test_native_source_pressure_and_interrupted_leap_replay(tmp_path,kind,opposing_cl):
    field={'id':'opposing-pressure','source_id':'scene:opposing-'+kind,
        'source_rule':'This '+kind+' field suppresses lower-authority cloud movement in its volume.',
        'source_cl':opposing_cl,'save_dc':16,'kind':kind,'absolute':False,
        'cells':[[x,y] for x in range(4,12) for y in range(14)],'min_z':0,'max_z':200}
    arena=authored_environment(tmp_path,fields=[field])
    c,t,mid=fixture(tmp_path,[],cl=14,owner_features=[CLOUD+'heavenly_leap'],ask=True,battlefield=arena)
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    selected=candidate(c,mid,'Heavenly Leap')
    settle(t,mid,selected.candidate_id,
        choices={'choice:needle.cloud_leap_destination':['cell:8,3,2']})
    e=reload(tmp_path,mid);actor=e.state.actors[OWNER]
    assert actor.resources['resource:core.qi']==before-3
    failures=[ev for ev in e.events if ev.event_type=='PASSIVE_TRIGGERED' and 'route_failure' in ev.payload]
    if opposing_cl<14-2:
        assert not failures
        move=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED'
            and ev.actor_id==OWNER and ev.source_definition_id==selected.source_definition_id)
        assert move.payload['interrupted'] is False
    else:
        assert failures and failures[-1].payload['route_failure']==('fall' if kind=='gravity' else 'origin_side')
        assert actor.position.z==0
        if kind=='spatial':
            assert any(ev.event_type=='DAMAGE_ROLLED' and ev.payload.get('reason')=='CLOUD_LEAP_INTERRUPTED_FORCE' for ev in e.events)
    assert not any(ev.event_type=='TELEPORT_COMMITTED' for ev in e.events)
    verify(c,mid)


def test_cloud_step_mist_support_ends_before_stationary_descent_checkpoint(tmp_path):
    mist={'id':'rain-cloud','kind':'mist','z':3,'capacity_lb':0,
        'cells':[[x,y] for x in range(12) for y in range(14)],'fragile':False,'trigger':'none'}
    arena=authored_environment(tmp_path,surfaces=[mist])
    c,t,mid=fixture(tmp_path,[],cl=6,owner_features=[CLOUD+'cloud_step'],ask=True,battlefield=arena)
    settle(t,mid,candidate(c,mid,'Cloud Step').candidate_id)
    e=reload(tmp_path,mid)
    move=next(row for row in e.legal_candidates() if row.kind.value=='MOVE' and row.destination==Position(x=3,y=5,z=3))
    settle(t,mid,move.candidate_id)
    turn(t,mid,ALLY);turn(t,mid,OWNER)
    # The next turn has no physical movement. Mist is own-turn support, so the
    # printed end checkpoint must withdraw it before checking stationary flight.
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].position.z==0
    assert not any(c.condition_id.endswith('prone') for c in e.state.actors[OWNER].conditions.values())
    verify(c,mid)


def test_native_anchor_authority_and_actual_destruction_withdraw_pressure(tmp_path):
    anchor={'id':1,'kind':'custom','name':'Pressure Anchor','x':3,'y':5,'ac':10,'hp':1,'blocks':False,
        'source_cl':17,'cultivation_asset':True,'asset_declaration':{'actor':'Scene GM','authority':'GM',
            'source_rule':'This cultivated Anchor maintains the spatial pressure field.','visibility':'public','expiry':'source_rule'}}
    field={'id':'anchor-pressure','source_id':'scene:anchor-pressure',
        'source_rule':'The active Anchor suppresses lower-authority cloud movement in this volume.',
        'source_cl':1,'save_dc':16,'kind':'spatial','absolute':False,'anchor_object_id':'object:map.1',
        'cells':[[x,y] for x in range(4,12) for y in range(14)],'min_z':0,'max_z':200}
    arena=authored_environment(tmp_path,fields=[field],objects=[anchor])
    c,t,mid=fixture(tmp_path,[],cl=14,owner_features=[CLOUD+'heavenly_leap'],ask=True,battlefield=arena)
    settle(t,mid,candidate(c,mid,'Heavenly Leap').candidate_id,
        choices={'choice:needle.cloud_leap_destination':['cell:8,3,2']})
    e=reload(tmp_path,mid)
    assert any(ev.payload.get('route_failure')=='origin_side' for ev in e.events)
    assert e.state.objects['object:map.1'].component['source_cl']==17
    # Destroy the real native map object through actual attack intents. The
    # family may not infer destruction from a name, damage label or inactivity.
    for _ in range(6):
        turn(t,mid,OWNER);e=reload(tmp_path,mid)
        if e.state.objects['object:map.1'].destroyed:break
        attack=next(row for row in e.legal_candidates() if row.target_ids==('object:map.1',))
        settle(t,mid,attack.candidate_id)
        settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=reload(tmp_path,mid)
    assert e.state.objects['object:map.1'].destroyed
    turn(t,mid,OWNER);before=len(reload(tmp_path,mid).events)
    selected=candidate(c,mid,'Heavenly Leap')
    settle(t,mid,selected.candidate_id,
        choices={'choice:needle.cloud_leap_destination':['cell:8,3,2']})
    e=reload(tmp_path,mid)
    move=next(ev for ev in reversed(e.events[before:]) if ev.event_type=='MOVEMENT_COMMITTED'
        and ev.actor_id==OWNER and ev.source_definition_id==selected.source_definition_id)
    assert move.payload['interrupted'] is False
    assert not any(ev.payload.get('route_failure') for ev in e.events[before:])
    verify(c,mid)


def test_native_private_asset_profile_remains_server_side_on_cold_table_view(tmp_path):
    anchor={'id':1,'kind':'custom','name':'Cultivated stone','x':3,'y':5,'ac':10,'hp':20,'blocks':False,
        'source_cl':17,'cultivation_asset':True,'asset_declaration':{'actor':'Scene GM','authority':'GM',
            'source_rule':'A cultivated world object.','visibility':'gm','expiry':'source_rule'}}
    arena=authored_environment(tmp_path,objects=[anchor])
    c,t,mid=fixture(tmp_path,[],cl=3,ask=False,battlefield=arena)
    e=reload(tmp_path,mid)
    assert e.state.objects['object:map.1'].component['source_cl']==17
    visible=t.state(mid)['map']['objects'][0]
    assert 'source_cl' not in visible and 'asset_declaration' not in visible and 'cultivation_asset' not in visible
    move=next(row for row in e.legal_candidates() if row.kind.value=='MOVE' and row.destination==Position(x=2,y=6))
    settle(t,mid,move.candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].position==Position(x=2,y=6)
    assert t.state(mid)['map']['objects'][0]==visible
    verify(c,mid)
