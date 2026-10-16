"""Native compatibility checks and default-inert contract guards."""
import pytest
from tests import test_riders_c7 as c
from combat.ext import body_modes_scene_resources as common


def finish_setup(engine):
    for _ in range(5):
        candidates=engine.legal_candidates()
        setup=next((x for x in candidates if x.source_definition_id=='system:combat.fight_setup'),None)
        if setup is None:return
        engine.execute_intent(c.ActionIntent(intent_id='body-setup-'+str(len(engine.events)),decision_id=setup.decision_id,
            candidate_id=setup.candidate_id,state_version=setup.state_version,actor_id=setup.actor_id))
    raise AssertionError('Setup did not finish')


def test_furnace_initiative_selection_and_native_paid_guard():
    engine=c.fight(c.bundle([c.VISCERA+'five_viscera_circuit',c.STAMINA_GUARD]),foe=c._typed_foe())
    c.answers(engine,{'organ_furnaces':['liver']})
    finish_setup(engine)
    owner=engine.state.actors[c.ME]
    assert common.scene_record(engine,owner,c.VISCERA.removesuffix('.feature.'))
    assert any(x.data.get('active')==['liver'] for x in owner.conditions.values())
    owner.current_hp-=20
    c.hostile_packet(engine,c.ME,10,'SLASHING')
    assert any(e.event_type=='HEALING_APPLIED' and e.source_definition_id==c.VISCERA+'five_viscera_circuit' for e in engine.events)


def test_unrelated_native_character_has_no_modes_or_scene_edits():
    engine=c.fight(c.bundle([]),foe=c._typed_foe())
    assert not any(x.condition_id==common.SCENE for a in engine.state.actors.values() for x in a.conditions.values())
    assert not any(a.parameters.get('body_mode_source') for a in engine.action_catalog.values())


@pytest.mark.parametrize('seed',('GATE4-TEST','GATE4-AN-1','GATE4-LEE','LOCK5-A','LOCK5-B','LOCK5-C'))
def test_exact_base_six_stock_replays(tmp_path,monkeypatch,seed):
    from tests import test_a2_glass_stock as stock
    from tests.replay_base import replay_base
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock,'EVIDENCE',__import__('pathlib').Path('/var/tmp/auto-audit/fix/MGR-T14-sol-reserve-nine-star-meridian-body-star-lit-acupoints-1-evidence/stock'))
    stock.test_six_stock_captures_equal_main(tmp_path,seed)


def test_native_incarnation_payment_receipt_diagnostics():
    engine,actor,foe=c._nine(['nine_star_incarnation'],marks=5)
    c.use(engine,'Nine-Star Incarnation')
    from combat.ext.ability_source import mechanic_at
    events=[(e.sequence,e.event_type,e.source_definition_id,mechanic_at(engine,e.source_definition_id),e.actor_id,e.payload) for e in engine.events if e.event_type in ('INTENT_ACCEPTED','RESOURCE_SPENT','RESOURCE_GAINED')]
    receipt=common.paid_receipt(engine,actor,c.NINE+'nine_star_incarnation','INTENT_ACCEPTED')
    assert actor.resources[c.MARKS]==1,(receipt,events)


def test_native_light_setting_reaches_ordinary_space_perception():
    engine,actor,foe=c._nine(['star_lit_acupoints'])
    before=actor.resources[c.MARKS]
    c.use(engine,'Star-Lit Acupoints: Emit Dim Light')
    assert actor.resources[c.MARKS]==before
    from combat.illumination import sources
    assert any(r['holder_id']==actor.entity_id and r['level']=='dim' and r['radius_ft']==5 for r in sources(engine))
    assert not any(x.display_name.startswith('Star-Lit Acupoints:') for x in engine.legal_candidates())


def test_native_journey_lung_clock_and_suppression_guard(tmp_path):
    from tests.test_body_modes_native import journey_game,journey_do,declare_source,OWNER
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    doc=c.sheet([c.VISCERA+'five_viscera_circuit'],cl=3)
    service,jid=journey_game(tmp_path,doc)
    journey_do(service,jid,'furnace_select',{'furnace':'lung'})
    journey_do(service,jid,'furnace_breath',{'operation':'hold'})
    declare_source(service,jid,'breathing_exposure','airless',{'source_rule':'An airless sealed chamber.', 'source_cl':3,'no_air':1})
    journey_do(service,jid,'wait',{'seconds':3599})
    assert service.journey_state(jid)['actors'][OWNER]['incapacitated']==0
    journey_do(service,jid,'wait',{'seconds':61})
    cold=CombatService(ROOT,tmp_path)
    state=cold.journey_state(jid)['actors'][OWNER]
    assert state['exhaustion']==6 and state['encounter_snapshot']['active']==0


@pytest.mark.parametrize('scenario',('star_move','star_push','star_pull','star_ac','light','orbital_dex','circuit_heart','circuit_lung','circuit_liver','circuit_kidney','circuit_spleen','lung_clock','authority','human_ai','liver_guard','kidney_guard','spleen_guard'))
def test_captured_source_contract_native_play(tmp_path,monkeypatch,scenario,catalog_environment):
    """Retained actual owner capsules, followed by real native transactions.

    Fresh source acquisition tests remain separate. Every scenario below still
    drives service/table/journey commit, cold reload and mechanical replay.
    """
    from tests import test_body_modes_native as n
    proof=n.EVIDENCE/('nine_star_meridian_body-cl18-acquisition.json' if scenario.startswith('star_') or scenario in ('light','orbital_dex') else 'five_viscera_immortal_furnace-cl3-acquisition.json')
    env=catalog_environment
    if scenario.startswith('star_'):
        result={'star_move':'Move 5 feet','star_push':'Push 5 feet','star_pull':'Pull 5 feet','star_ac':'+1 AC against it'}[scenario]
        n.test_native_star_lit_all_printed_results(env,monkeypatch,tmp_path,result)
    elif scenario=='light':n.test_native_light_no_cost_and_once_during_owner_turn(env,monkeypatch,tmp_path)
    elif scenario=='orbital_dex':n.test_native_orbital_after_failed_dexterity_damage_save(env,monkeypatch,tmp_path)
    elif scenario.startswith('circuit_'):n.test_native_circuit_initiative_all_furnaces_and_cosmetic_setting(env,monkeypatch,tmp_path,scenario.removeprefix('circuit_'))
    elif scenario=='lung_clock':n.test_native_lung_one_hour_clock_and_no_air_lifecycle(env,monkeypatch,tmp_path)
    elif scenario=='authority':n.test_native_effective_cl_authority_and_source_isolation(env,monkeypatch,tmp_path)
    elif scenario=='human_ai':n.test_native_circuit_human_choice_during_automatic_first_actor(env,monkeypatch,tmp_path)
    else:n.test_native_circuit_actual_paid_guard_benefits(env,monkeypatch,tmp_path,scenario.removesuffix('_guard'))


@pytest.mark.parametrize('family',('nine','furnace'))
def test_actual_source_native_combat_authority_and_light(tmp_path,monkeypatch,family,catalog_environment):
    from tests import test_body_modes_native as n
    from combat.ext import body_modes_scene_resources as body
    from combat.combat_world_facts import clock
    from combat import illumination,senses
    parent,cl=(n.NINE,18) if family=='nine' else (n.FURNACE,3)
    doc=n.acquire(catalog_environment,monkeypatch,parent,cl)
    service,table,mid=n.game(tmp_path,doc,seed='COMBAT-WORLD-'+family)
    picks={'choice:needle.organ_furnaces':['lung']}
    n.advance(service,table,mid,n.OWNER,picks)
    engine=n.loaded(service,mid);actor=engine.state.actors[n.OWNER]
    if family=='nine':
        n.play(service,table,mid,'Star-Lit Acupoints: Emit Dim Light')
        engine=n.loaded(service,mid);actor=engine.state.actors[n.OWNER]
        payload={'source':'system:scene.fields','subject':n.OWNER,'kind':'lighting','scope':'room',
            'value':{'cells':[[actor.position.x,actor.position.y,actor.position.z]],'level':'darkness'},
            'expires_at':int(clock(engine))+60,'readers':[]}
        assert table.world_fact(mid,engine.state.state_version,payload,'mapped-room')['status']=='COMMITTED'
        engine=n.loaded(service,mid)
        assert illumination.level_at(engine,engine.state.actors[n.FOE],engine.state.actors[n.OWNER].position)=='dim'
        assert senses.ordinary_sight_perceives(engine,engine.state.actors[n.FOE],engine.state.actors[n.OWNER])
        assert not senses.pinpoints(engine,engine.state.actors[n.FOE],engine.state.actors[n.OWNER])
    engine=n.loaded(service,mid);marks=engine.state.actors[n.OWNER].resources.get(n.MARKS)
    payload={'source':body.AUTHORITY,'subject':n.OWNER,'kind':'cultivation_suppression','scope':'seal',
        'value':{'source_rule':'This sealed chamber reduces effective Body CL to 2 for six seconds.','source_cl':18,'system':'body','effective_cl':2},
        'expires_at':int(clock(engine))+6,'readers':[]}
    response=table.world_fact(mid,engine.state.state_version,payload,'native-body-seal')
    assert response['status']=='COMMITTED'
    assert table.world_fact(mid,engine.state.state_version,payload,'native-body-seal')==response
    engine=n.loaded(service,mid);actor=engine.state.actors[n.OWNER]
    assert body.effective_body_cl(engine,actor)==2 and actor.resources.get(n.MARKS)==marks
    assert not body.available(engine,actor,parent+'.feature.'+('star_lit_acupoints' if family=='nine' else 'five_viscera_circuit'),3)
    assert body.effective_body_cl(engine,engine.state.actors[n.FOE])==18
    if family=='nine':assert not illumination.sources(engine)
    n.next_actor(service,table,mid,n.OWNER,picks)
    n.next_actor(service,table,mid,n.OWNER,picks)
    engine=n.loaded(service,mid)
    assert body.effective_body_cl(engine,engine.state.actors[n.OWNER])==cl


@pytest.mark.parametrize('scenario',('heart_fire','heart_radiant','lung_hazard','spleen_push','spleen_prone','orbital_low','orbital_high','incarnation','falling_star','overflow_hp','overflow_move','overflow_save'))
def test_source_capsule_remaining_native_play(tmp_path,monkeypatch,scenario,catalog_environment):
    from tests import test_body_modes_native as n
    if scenario.startswith('heart_'):n.test_native_circuit_heart_declared_hit_packet(catalog_environment,monkeypatch,tmp_path,scenario.removeprefix('heart_'))
    elif scenario=='lung_hazard':n.test_native_circuit_lung_ranged_ac_and_real_smoke_save(catalog_environment,monkeypatch,tmp_path)
    elif scenario.startswith('spleen_'):n.test_native_spleen_successful_hostile_shove_boundary(catalog_environment,monkeypatch,tmp_path,scenario.removeprefix('spleen_'))
    elif scenario.startswith('orbital_'):n.test_native_orbital_attack_packet_zero_and_nonzero(catalog_environment,monkeypatch,tmp_path,3 if scenario=='orbital_low' else 18)
    elif scenario=='incarnation':n.test_native_incarnation_paid_form_hit_and_exact_duration(catalog_environment,monkeypatch,tmp_path)
    elif scenario=='falling_star':n.test_native_falling_star_arrival_cost_area_and_ground(catalog_environment,monkeypatch,tmp_path)
    else:n.test_native_constellation_capped_real_gain_and_overflow(catalog_environment,monkeypatch,tmp_path,{'overflow_hp':'temp_hp','overflow_move':'move','overflow_save':'save'}[scenario])


def test_source_capsule_actual_sleep_and_recovery(tmp_path,monkeypatch,catalog_environment):
    from tests.test_body_modes_native import test_native_circuit_actual_unconscious_dormancy_and_resumption
    test_native_circuit_actual_unconscious_dormancy_and_resumption(catalog_environment,monkeypatch,tmp_path)


@pytest.mark.parametrize('end',('expiry','suppression','death'))
def test_source_capsule_actual_journey_form_continuation(tmp_path,monkeypatch,end,catalog_environment):
    from tests.test_body_modes_native import test_native_journey_incarnation_clock_flight_and_fall
    test_native_journey_incarnation_clock_flight_and_fall(catalog_environment,monkeypatch,tmp_path,end)


@pytest.mark.parametrize('scenario',('air','objects'))
def test_source_capsule_falling_star_route_and_object_consumers(tmp_path,monkeypatch,scenario,catalog_environment):
    from tests import test_body_modes_native as n
    (n.test_native_falling_star_open_air_without_flight if scenario=='air' else n.test_native_falling_star_classified_objects_double_once)(catalog_environment,monkeypatch,tmp_path)


def test_source_capsule_native_breathing_check_provenance(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    from combat.combat_world_facts import clock
    doc=n.acquire(catalog_environment,monkeypatch,n.FURNACE,3)
    service,table,mid=n.game(tmp_path,doc,seed='LUNG-CHECK-PROVENANCE')
    picks={'choice:needle.organ_furnaces':['lung']}
    n.advance(service,table,mid,n.OWNER,picks)
    engine=n.loaded(service,mid)
    payload={'source':'system:scene.checks','subject':n.OWNER,'kind':'ability_check','scope':'choking-smoke',
        'value':{'ability':'CON','skill':'','dc':12,'purpose':'other','reference':'','source_rule':'Endure this inhaled choking smoke with a Constitution check.',
                 'source_cl':3,'breathing_hazards':['inhalation']},'expires_at':int(clock(engine))+60,'readers':[n.OWNER,n.FOE]}
    table.world_fact(mid,engine.state.state_version,payload,'lung-actual-check')
    engine=n.loaded(service,mid);start=len(engine.rolls)
    n.play(service,table,mid,'Resolve a requested ability check',picks)
    engine=n.loaded(service,mid)
    assert any(r.actor_id==n.OWNER and r.mode=='ADVANTAGE' and r.reason.startswith('CHECK:system:scene.checks') for r in engine.rolls[start:])
    payload={**payload,'scope':'ordinary-con-check','value':{'ability':'CON','skill':'','dc':12,'purpose':'other','reference':''}}
    table.world_fact(mid,engine.state.state_version,payload,'lung-ordinary-check')
    engine=n.loaded(service,mid);start=len(engine.rolls)
    n.play(service,table,mid,'Resolve a requested ability check',picks)
    assert all(r.mode=='NORMAL' for r in n.loaded(service,mid).rolls[start:] if r.actor_id==n.OWNER and r.reason.startswith('CHECK:system:scene.checks'))


def test_source_capsule_native_spleen_contested_shove(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    doc=n.acquire(catalog_environment,monkeypatch,n.FURNACE,3)
    foe=n.c7.sheet([],cl=3,mods={'STR':-4},spheres={'sphere_record_ids':['tianxia.sphere.brute'],
        'automatic_sphere_component_record_ids':['BRUTE_BASE_BRUTAL_SHOVE','BRUTE_BASE_BRUTE_MANEUVERS']})
    service,table,mid=n.game(tmp_path,doc,seed='CIRCUIT-CONTESTED-SHOVE',foe_doc=foe)
    picks={'choice:needle.organ_furnaces':['spleen']}
    n.advance(service,table,mid,n.FOE,picks)
    for _ in range(5):
        engine=n.loaded(service,mid);start=len(engine.events)
        if engine._distance_actor_to_actor(engine.state.actors[n.FOE],engine.state.actors[n.OWNER])>5:
            move=next(c for c in engine.legal_candidates() if c.kind.value=='MOVE' and c.destination and engine.grid.distance_ft(c.destination,engine.state.actors[n.OWNER].position)<=5)
            n.settle(table,mid,move.candidate_id,picks)
        n.play(service,table,mid,'Brutal Shove',picks,target=n.OWNER)
        engine=n.loaded(service,mid);events=engine.events[start:]
        if any(e.event_type=='CHECK_ROLLED' and e.payload.get('success') is False for e in events):break
        n.next_actor(service,table,mid,n.FOE,picks)
    else:raise AssertionError('The actual defender never won the native contest')
    grant=next(e for e in events if e.event_type=='TEMP_HP_GRANTED' and e.source_definition_id==n.FURNACE+'.feature.five_viscera_circuit')
    check=next(e for e in events if e.event_type=='CHECK_ROLLED' and e.payload.get('success') is False)
    assert check.sequence<grant.sequence


def test_source_capsule_lung_loss_is_prospective(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    doc=n.acquire(catalog_environment,monkeypatch,n.FURNACE,3)
    service,jid=n.journey_game(tmp_path,doc)
    n.journey_do(service,jid,'furnace_select',{'furnace':'lung'})
    n.declare_source(service,jid,'breathing_exposure','sealed-room',{'source_rule':'The sealed chamber has no breathable air.','source_cl':3,'no_air':1})
    n.journey_do(service,jid,'wait',{'seconds':3599})
    n.journey_do(service,jid,'furnace_select',{'furnace':'heart'})
    n.journey_do(service,jid,'wait',{'seconds':1})
    assert n.CombatService(n.ROOT,tmp_path).journey_state(jid)['actors'][n.OWNER]['incapacitated']==0
    n.journey_do(service,jid,'wait',{'seconds':60})
    assert n.CombatService(n.ROOT,tmp_path).journey_state(jid)['actors'][n.OWNER]['encounter_snapshot']['current_hp']==0


def test_source_capsule_lung_clock_crosses_encounter_cold(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    doc=n.acquire(catalog_environment,monkeypatch,n.FURNACE,3)
    service,jid=n.journey_game(tmp_path,doc)
    n.journey_do(service,jid,'furnace_select',{'furnace':'lung'})
    n.declare_source(service,jid,'breathing_exposure','sealed-room',{'source_rule':'The sealed chamber has no breathable air.','source_cl':3,'no_air':1})
    n.journey_do(service,jid,'wait',{'seconds':3599})
    state=service.journey_state(jid)
    mid=service.journey_start_combat(jid,state['revision'],{n.OWNER:'a',n.FOE:'b'},maximum_rounds=20)['match_id']
    table=n.TabletopService(service,tmp_path);picks={'choice:needle.organ_furnaces':['lung']}
    n.advance(service,table,mid,n.OWNER,picks)
    for _ in range(16):
        engine=n.loaded(service,mid)
        if not engine.state.actors[n.OWNER].active:break
        state=table.state(mid);n.settle(table,mid,state['menu']['end_turn'],picks)
    else:raise AssertionError('Native elapsed encounter clock did not exhaust held air')
    engine=n.loaded(service,mid);actor=engine.state.actors[n.OWNER]
    from combat.ext.forged_exhaustion import level
    assert actor.current_hp==0 and not actor.active and level(actor)==6
    from combat.ext.life_state import is_deceased
    assert is_deceased(actor)
    assert any(e.event_type=='SUFFOCATION_COMMITTED' for e in engine.events)


def test_source_capsule_native_ground_continuation_and_repair(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    doc=n.acquire(catalog_environment,monkeypatch,n.NINE,10)
    foe=n.c7.sheet([],cl=10,items=['tianxia.mortal.gear.shovel'],spheres={'sphere_record_ids':['tianxia.sphere.fire'],'learned_talent_record_ids':['FIRE_TAL_FLAME_LASH']})
    foe['ability_scores_and_statistics']['technique_attack_bonus']=50
    service,jid=n.journey_game(tmp_path,doc,foe_doc=foe,positions={n.OWNER:{'x':0,'y':6},n.FOE:{'x':1,'y':6}})
    state=service.journey_state(jid)
    mid=service.journey_start_combat(jid,state['revision'],{n.OWNER:'a',n.FOE:'b'},maximum_rounds=6)['match_id']
    table=n.TabletopService(service,tmp_path);picks={n.GUARD:['4'],'choice:needle.orbital_body':None}
    n.advance(service,table,mid,n.FOE,picks)
    for _ in range(5):
        engine=n.loaded(service,mid)
        if engine.state.actors[n.OWNER].resources[n.MARKS]>=3:break
        n.play(service,table,mid,n.source_action(engine,n.FOE,'FIRE_TAL_FLAME_LASH').display_name,picks,target=n.OWNER)
        n.next_actor(service,table,mid,n.FOE,picks)
    n.advance(service,table,mid,n.OWNER,picks)
    engine=n.loaded(service,mid)
    candidate=next(c for c in engine.legal_candidates() if c.display_name.startswith('Falling-Star Descent') and c.destination and (c.destination.x,c.destination.y,c.destination.z)==(2,6,0))
    n.settle(table,mid,candidate.candidate_id,picks)
    for _ in range(20):
        if n.loaded(service,mid).state.terminal_result is not None:break
        n.settle(table,mid,table.state(mid)['menu']['end_turn'],picks)
    state=service.journey_state(jid);service.journey_resume(jid,state['revision'])
    menu=service.journey_menu(jid,n.FOE)
    option=next(o for o in menu['options'] if o['kind']=='activity_start' and o['payload']['source']=='system:combat.repair_terrain')
    cell=option['payload']['parameters']['cell']
    before=service.journey_state(jid)['seconds']
    n.journey_do(service,jid,'activity_start',option['payload'],aid=n.FOE)
    n.journey_do(service,jid,'activity_work',{'seconds':59},aid=n.FOE)
    assert not any(e['kind']=='GROUND_REPAIRED' for e in service.journey_state(jid)['events'])
    n.journey_do(service,jid,'activity_work',{'seconds':1},aid=n.FOE)
    state=n.CombatService(n.ROOT,tmp_path).journey_state(jid)
    assert state['seconds']==before+60
    assert any(e['kind']=='GROUND_REPAIRED' and e['cell']==cell for e in state['events'])
    state=service.journey_state(jid)
    again=service.journey_start_combat(jid,state['revision'],{n.OWNER:'a',n.FOE:'b'},maximum_rounds=2)['match_id']
    engine=n.loaded(service,again)
    assert any(z.active for z in engine.state.zones.values())
    assert not any(c.model_dump(mode='json')==cell for z in engine.state.zones.values() if z.active for c in z.affected_cells)


@pytest.mark.parametrize('source_cl',(18,19))
def test_source_capsule_native_incarnation_resistance_gravity_and_authority(tmp_path,monkeypatch,source_cl,catalog_environment):
    from tests import test_body_modes_native as n
    from combat import typed_reactions,zones
    foe=n.c7.sheet([],cl=source_cl,mods={'STR':10},spheres={'sphere_record_ids':['tianxia.sphere.fire','tianxia.sphere.brute'],
        'learned_talent_record_ids':['FIRE_TAL_FLAME_LASH'],'automatic_sphere_component_record_ids':['BRUTE_BASE_BRUTAL_SHOVE','BRUTE_BASE_BRUTE_MANEUVERS']})
    service,table,mid,picks=n.charged_game(catalog_environment,monkeypatch,tmp_path,5,foe_doc=foe)
    n.advance(service,table,mid,n.OWNER,picks)
    n.play(service,table,mid,'Nine-Star Incarnation',picks)
    engine=n.loaded(service,mid);owner=engine.state.actors[n.OWNER];other=engine.state.actors[n.FOE]
    gravity=next(z for z in zones.typed_zones(engine) if z.source_definition_id==n.NINE+'.feature.nine_star_incarnation')
    assert zones.zone_is_difficult(engine,gravity,other) and not zones.zone_is_difficult(engine,gravity,owner)
    for kind in ('FIRE','COLD','FORCE','RADIANT','PSYCHIC','VOID'):
        profile=typed_reactions.resistance_profile(engine,owner,kind,{})
        assert profile['resist']==(kind not in ('PSYCHIC','VOID')),(kind,profile)
    picks={n.GUARD:None,'choice:needle.orbital_body':None,'choice:needle.brutal_shove_result':['prone']}
    n.advance(service,table,mid,n.FOE,picks)
    start=len(n.loaded(service,mid).events)
    for _ in range(4):
        n.play(service,table,mid,n.source_action(n.loaded(service,mid),n.FOE,'FIRE_TAL_FLAME_LASH').display_name,picks,target=n.OWNER)
        engine=n.loaded(service,mid)
        packet=next((e for e in engine.events[start:] if e.event_type=='DAMAGE_COMMITTED' and n.OWNER in e.target_ids),None)
        if packet is not None:break
        n.next_actor(service,table,mid,n.FOE,picks)
    assert packet is not None
    assert packet.payload['reduced_to']==packet.payload['rolled_or_pending_damage']//2
    n.next_actor(service,table,mid,n.FOE,picks)
    engine=n.loaded(service,mid);before=engine.state.actors[n.OWNER].position
    start=len(engine.events)
    for _ in range(4):
        start=len(n.loaded(service,mid).events)
        n.play(service,table,mid,'Brutal Shove',picks,target=n.OWNER)
        engine=n.loaded(service,mid);events=engine.events[start:]
        if any(e.event_type=='CHECK_ROLLED' and e.payload.get('success') is True for e in events):break
        n.next_actor(service,table,mid,n.FOE,picks)
    else:raise AssertionError('The actual hostile Brute never won its contest')
    prone=any(c.expires_on=='STAND_UP' for c in engine.state.actors[n.OWNER].conditions.values())
    if source_cl==18:
        assert not prone and engine.state.actors[n.OWNER].position==before
    else:assert prone
    # Consume the moving field through an actual hostile movement intent,
    # rather than only reading its projected zone profile.
    other=engine.state.actors[n.FOE];origin=other.position
    step=next(c for c in engine.legal_candidates() if c.kind.value=='MOVE' and c.destination and
        c.destination.z==origin.z and engine.grid.distance_ft(origin,c.destination)==5 and
        engine.grid.distance_ft(engine.state.actors[n.OWNER].position,c.destination)<=10 and c.movement_cost_ft==10)
    start=len(engine.events);n.settle(table,mid,step.candidate_id,picks)
    events=n.loaded(service,mid).events[start:]
    assert any(e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==n.FOE and e.payload['cost_ft']==10 for e in events)


def test_source_capsule_circuit_before_first_turn_and_new_turn_refresh(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    doc=n.acquire(catalog_environment,monkeypatch,n.FURNACE,3)
    foe=n.c7.sheet([],cl=3)
    foe['ability_scores_and_statistics']['armor_class']['base_value']=1
    service,table,mid=n.game(tmp_path,doc,seed='CIRCUIT-AI-FIRST-2',foe_doc=foe)
    picks={'choice:needle.organ_furnaces':['heart'],'choice:needle.furnace_heart':['radiant']}
    n.advance(service,table,mid,n.FOE,picks)
    engine=n.loaded(service,mid)
    assert not any(e.event_type=='TURN_STARTED' and e.actor_id==n.OWNER for e in engine.events)
    row=next(r for r in engine.typed_reaction_rows[n.OWNER] if r.get('block')=='opportunity')
    picks[row.get('consent_source_id') or 'reaction:typed.'+row['feature_id']]=['use']
    candidate=next(c for c in engine.legal_candidates() if c.kind.value=='MOVE' and c.destination and (c.destination.x,c.destination.y,c.destination.z)==(5,6,0))
    start=len(engine.events);n.settle(table,mid,candidate.candidate_id,picks)
    engine=n.loaded(service,mid)
    first=[e for e in engine.events[start:] if e.event_type=='DAMAGE_COMMITTED' and e.payload.get('display_source_id')==n.FURNACE+'.feature.five_viscera_circuit']
    assert len(first)==1 and first[0].payload['rolled_or_pending_damage']==engine.state.actors[n.OWNER].proficiency_bonus
    n.advance(service,table,mid,n.OWNER,picks)
    engine=n.loaded(service,mid)
    candidate=next(c for c in engine.legal_candidates() if c.kind.value=='MOVE' and c.destination and (c.destination.x,c.destination.y,c.destination.z)==(4,6,0))
    n.settle(table,mid,candidate.candidate_id,picks)
    engine=n.loaded(service,mid);start=len(engine.events)
    n.play(service,table,mid,n.strike_name(engine,n.OWNER),picks,target=n.FOE)
    engine=n.loaded(service,mid)
    again=[e for e in engine.events[start:] if e.event_type=='DAMAGE_COMMITTED' and e.payload.get('display_source_id')==n.FURNACE+'.feature.five_viscera_circuit']
    assert len(again)==1


def test_source_capsule_lung_recovers_only_its_suffocation_exhaustion(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    doc=n.acquire(catalog_environment,monkeypatch,n.FURNACE,3)
    service,jid=n.journey_game(tmp_path,doc)
    n.journey_do(service,jid,'travel_exhaustion',{'levels':2,'ordinary':False})
    n.journey_do(service,jid,'furnace_select',{'furnace':'lung'})
    n.declare_source(service,jid,'breathing_exposure','sealed-room',{'source_rule':'The sealed room has no breathable air.','source_cl':3,'no_air':1})
    n.journey_do(service,jid,'wait',{'seconds':3611})
    state=n.CombatService(n.ROOT,tmp_path).journey_state(jid)
    assert state['actors'][n.OWNER]['exhaustion']==4
    assert state['actors'][n.OWNER]['encounter_snapshot']['current_hp']>0
    n.declare_source(service,jid,'breathing_exposure','sealed-room',{'source_rule':'The room opens and breathable air returns.','source_cl':3,'no_air':0})
    state=n.CombatService(n.ROOT,tmp_path).journey_state(jid)
    assert state['actors'][n.OWNER]['exhaustion']==2
    assert state['actors'][n.OWNER]['encounter_snapshot']['current_hp']>0


@pytest.mark.parametrize('family',('nine','furnace'))
def test_source_capsule_wrong_owner_and_unrelated_actor_remain_inert(tmp_path,monkeypatch,family,catalog_environment):
    from tests import test_body_modes_native as n
    from combat.ext.body_modes_scene_resources import SCENE,AUTHORITY
    from combat.combat_world_facts import clock
    from combat.tabletop_service import TabletopError
    parent=n.NINE if family=='nine' else n.FURNACE
    doc=n.acquire(catalog_environment,monkeypatch,parent,3)
    service,table,mid=n.game(tmp_path,doc,seed='BODY-WRONG-OWNER-'+family)
    n.advance(service,table,mid,n.OWNER,{'choice:needle.organ_furnaces':['lung']})
    engine=n.loaded(service,mid);other=engine.state.actors[n.FOE]
    assert not any(c.condition_id==SCENE for c in other.conditions.values())
    assert n.MARKS not in other.resources
    name='Star-Lit Acupoints: Emit Dim Light' if family=='nine' else 'Organ Furnaces: Suppress cosmetic signs'
    setting=next(a.source_definition_id for a in engine.action_catalog.values() if a.owner_id==n.OWNER and a.display_name==name)
    before=n.canonical_sha256(engine.state.model_dump(mode='json'))
    with pytest.raises(TabletopError,match='owns|own'):
        table.save_settings(mid,n.FOE,[setting],'wrong-owner-setting')
    assert n.canonical_sha256(n.loaded(service,mid).state.model_dump(mode='json'))==before
    payload={'source':AUTHORITY,'subject':n.FOE,'kind':'cultivation_suppression','scope':'not-owned',
        'value':{'source_rule':'A Body seal with an actual printed source.','source_cl':18,'system':'body','effective_cl':2},
        'expires_at':int(clock(engine))+6,'readers':[]}
    with pytest.raises(TabletopError):table.world_fact(mid,engine.state.state_version,payload,'wrong-source-subject')
    assert n.canonical_sha256(n.loaded(service,mid).state.model_dump(mode='json'))==before


def test_source_capsule_ai_owner_selects_furnace_without_human_prompt(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    doc=n.acquire(catalog_environment,monkeypatch,n.FURNACE,3)
    service,table,mid=n.game(tmp_path,doc,seed='CIRCUIT-AI-FIRST-0',modes={n.OWNER:'LOCAL_AUTO',n.FOE:'MANUAL'})
    engine=n.loaded(service,mid)
    assert engine.state.current_actor_id==n.OWNER
    result=table.auto_step(mid,0,[])
    assert result['status']=='COMMITTED',result
    owner=n.loaded(service,mid).state.actors[n.OWNER]
    selected=next(c for c in owner.conditions.values() if c.condition_id=='condition:typed.organ_furnaces')
    assert len(selected.data['active'])==1 and selected.data['active'][0] in ('heart','lung','liver','kidney','spleen')


def test_source_capsule_actual_staged_source_and_feature_isolation(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    from combat.combat_world_facts import clock
    from combat.ext.body_modes_scene_resources import AUTHORITY
    doc=n.acquire(catalog_environment,monkeypatch,n.NINE,6)
    foe=n.c7.sheet([],cl=6,spheres={'sphere_record_ids':['tianxia.sphere.fire'],'learned_talent_record_ids':['FIRE_TAL_FLAME_LASH']})
    foe['ability_scores_and_statistics']['technique_attack_bonus']=50
    service,table,mid=n.game(tmp_path,doc,seed='MARK-QUALIFIED-SOURCE',foe_doc=foe)
    picks={n.GUARD:['1'],'choice:needle.orbital_body':None}
    n.advance(service,table,mid,n.FOE,picks)
    engine=n.loaded(service,mid);initial=engine.state.actors[n.OWNER].resources[n.MARKS]
    fact={'source':AUTHORITY,'subject':n.OWNER,'kind':'qualified_source','scope':'actual-opponent',
        'value':{'source_rule':'This deliberately staged opponent interaction cannot farm Celestial Marks.','source_cl':6,
                 'source_actor_id':n.FOE,'hostile':1,'staged':1},'expires_at':int(clock(engine))+120,'readers':[]}
    table.world_fact(mid,engine.state.state_version,fact,'staged-source')
    def paid_guard():
        for _ in range(4):
            engine=n.loaded(service,mid);stamina=engine.state.actors[n.OWNER].resources[n.STAMINA]
            n.play(service,table,mid,n.source_action(engine,n.FOE,'FIRE_TAL_FLAME_LASH').display_name,picks,target=n.OWNER)
            if n.loaded(service,mid).state.actors[n.OWNER].resources[n.STAMINA]<stamina:return
            n.next_actor(service,table,mid,n.FOE,picks)
        raise AssertionError('No actual paid Guard completed')
    paid_guard()
    assert n.loaded(service,mid).state.actors[n.OWNER].resources[n.MARKS]==initial
    engine=n.loaded(service,mid)
    fact['value']={**fact['value'],'staged':0,'source_rule':'The staged interaction ended; this opponent now attacks in a real hostile contest.'}
    table.world_fact(mid,engine.state.state_version,fact,'actual-hostile-source')
    engine=n.loaded(service,mid)
    seal={'source':AUTHORITY,'subject':n.OWNER,'kind':'cultivation_suppression','scope':'star-only',
        'value':{'source_rule':'This seal suppresses only Star-Lit Acupoints; the parent Celestial Mark record remains.','source_cl':6,
                 'system':'body','feature_id':n.NINE+'.feature.star_lit_acupoints'},'expires_at':int(clock(engine))+120,'readers':[]}
    table.world_fact(mid,engine.state.state_version,seal,'star-only-seal')
    n.next_actor(service,table,mid,n.FOE,picks);paid_guard()
    engine=n.loaded(service,mid)
    assert engine.state.actors[n.OWNER].resources[n.MARKS]==initial+1


def test_source_capsule_terminal_paid_activation_still_generates_mark(tmp_path,monkeypatch,catalog_environment):
    from tests import test_body_modes_native as n
    doc=n.acquire(catalog_environment,monkeypatch,n.NINE,18)
    foe=n.c7.sheet([],cl=1)
    service,table,mid=n.game(tmp_path,doc,seed='NINE-TERMINAL-ACTIVATION',foe_doc=foe,foe_hp=1)
    n.advance(service,table,mid,n.OWNER)
    engine=n.loaded(service,mid)
    assert engine.state.actors[n.OWNER].resources[n.MARKS]==3
    candidate=next(c for c in engine.legal_candidates() if c.display_name.startswith('Falling-Star Descent') and c.destination and
        (c.destination.x,c.destination.y,c.destination.z)==(2,6,0))
    n.settle(table,mid,candidate.candidate_id,{'choice:needle.area_recipients':[n.FOE]})
    engine=n.loaded(service,mid)
    assert engine.state.terminal_result is not None
    assert any(z.active and (z.trigger_profile.get('placed') or {}).get('tag')=='nine_star_rubble' for z in engine.state.zones.values())
    assert engine.state.actors[n.OWNER].resources[n.MARKS]==1
    assert any(e.event_type=='RESOURCE_GAINED' and e.payload.get('resource_id')==n.MARKS and e.sequence>next(x.sequence for x in engine.events if x.event_type=='RESOURCE_SPENT' and x.payload.get('resource_id')==n.MARKS) for e in engine.events)
