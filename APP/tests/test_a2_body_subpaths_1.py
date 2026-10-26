"""Printed Body flight/terrain through genuine table commits and cold reload."""
import pytest
from combat import flight
from combat.ext import sky_treading
from tests.worker2_support import fixture, settle, reload, candidate, turn, OWNER, ALLY, FOE

NINE = 'tianxia.subpath.body.nine_star_meridian_body.feature.'
SKY = 'tianxia.subpath.body.sky_treading_tendon_school.feature.'
MARK = 'resource:named.celestial_mark'
STAMINA = 'resource:core.stamina'


def setup(tmp_path, features, **kwargs):
    return fixture(tmp_path, [], owner_features=features, owner_path='Body Refining', primary='Stamina',
                   cl=18, seed='A2GBODSUB1', **kwargs)


def commit(combat, table, mid, name):
    c = candidate(combat, mid, name)
    settle(table, mid, c.candidate_id)


def test_constellation_flight_and_hover_commit_and_reload(tmp_path):
    combat, table, mid = setup(tmp_path, [NINE+'constellation_circuit'])
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert actor.resources[MARK] == 3
    assert actor.resource_maximums[MARK] == actor.proficiency_bonus+3
    assert flight.profile(engine, actor).speed_ft == 30
    c = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination.z == 1)
    settle(table, mid, c.candidate_id)
    loaded = reload(tmp_path, mid)
    actor = loaded.state.actors[OWNER]
    assert actor.position.z == 1 and flight.profile(loaded, actor).hover
    assert flight.profile(loaded, loaded.state.actors[ALLY]).speed_ft == 0


def test_nine_star_incarnation_flight_persists_without_marks(tmp_path):
    # Earn the two additional Marks through real Stamina activations.
    features=[NINE+'constellation_circuit',NINE+'nine_star_incarnation',
              'tianxia.subpath.body.flesh_crucible.feature.titan_s_frame']
    combat, table, mid = setup(tmp_path/'form', features)
    for _ in range(2):
        commit(combat, table, mid, "Titan's Frame")
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
    # Start the costly replacement-flight activation in genuine unsupported
    # flight. Constellation's native Hover keeps this altitude between turns.
    engine = combat._load_session(mid).engine
    lift = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination.z == 1)
    settle(table, mid, lift.candidate_id)
    engine = reload(tmp_path/'form', mid)
    assert engine.state.actors[OWNER].position.z == 1
    before = combat._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    commit(combat, table, mid, 'Nine-Star Incarnation')
    loaded=reload(tmp_path/'form',mid);actor=loaded.state.actors[OWNER]
    assert actor.resources[STAMINA] == before-6
    assert actor.resources[MARK] < 3
    assert actor.position.z == 1, 'Mark payment must not settle the fall before replacement flight resolves'
    assert flight.profile(loaded,actor).speed_ft == 60 and flight.profile(loaded,actor).hover
    assert flight.profile(loaded,loaded.state.actors[ALLY]).speed_ft == 0


def test_plain_constellation_mark_spend_still_settles_unsupported_flight(tmp_path):
    from tests.cw2_service_support import add_action
    def prepare(bundles):
        add_action(bundles[0], 'Spend one Mark', [{'type':'spend_resource','resource_id':MARK,'flat':1,'applies_to':'self'}], target='SELF')
    combat,table,mid=setup(tmp_path,[NINE+'constellation_circuit'],bundle_transform=prepare)
    engine=combat._load_session(mid).engine
    lift=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.z==1)
    settle(table,mid,lift.candidate_id)
    c=candidate(combat,mid,'Spend one Mark');settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.resources[MARK]==2 and actor.position.z==0


def test_falling_star_descent_resolves_from_altitude_before_mark_loss_fall(tmp_path):
    combat,table,mid=setup(tmp_path,[NINE+'constellation_circuit',NINE+'falling_star_descent'],owner_dc=50)
    engine=combat._load_session(mid).engine
    lift=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.z==1)
    settle(table,mid,lift.candidate_id)
    before=reload(tmp_path,mid);hp=before.state.actors[FOE].current_hp
    c=candidate(combat,mid,'Falling-Star Descent',at=(5,5))
    settle(table,mid,c.candidate_id,choices={'choice:needle.area_recipients':[FOE]})
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    # The paid Body activation spends all three Marks, then earns the printed
    # once-per-round Stamina-generated Mark after resolution.
    assert actor.position.z==0 and actor.resources[MARK]==1
    assert any(e.event_type=='RESOURCE_SPENT' and e.actor_id==OWNER
               and e.payload.get('resource_id')==MARK and e.payload.get('amount')==3 for e in engine.events)
    assert engine.state.actors[FOE].current_hp<hp


def test_body_crosses_heaven_native_flight(tmp_path):
    combat, table, mid=setup(tmp_path,[SKY+'body_crosses_heaven'])
    engine=combat._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.z==1)
    settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.position.z==1 and flight.profile(engine,actor).speed_ft==engine._effective_speed(actor)
    assert flight.profile(engine,actor).hover


def test_body_crosses_heaven_flight_ends_on_unconsciousness_not_incapacitation(tmp_path):
    from tests.cw2_service_support import add_action
    def prepare(bundles):
        add_action(bundles[0], 'Become incapacitated', [{'type':'condition','condition':'incapacitated','applies_to':'self'}], target='SELF')
        add_action(bundles[0], 'Become unconscious', [{'type':'condition','condition':'unconscious','applies_to':'self'}], target='SELF')
    features=[SKY+'body_crosses_heaven']
    combat,table,mid=setup(tmp_path/'incap',features,bundle_transform=prepare)
    engine=combat._load_session(mid).engine
    lift=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.z==1)
    settle(table,mid,lift.candidate_id)
    commit(combat,table,mid,'Become incapacitated')
    engine=reload(tmp_path/'incap',mid);actor=engine.state.actors[OWNER]
    assert actor.position.z==1 and flight.profile(engine,actor).hover

    combat,table,mid=setup(tmp_path/'unconscious',features,bundle_transform=prepare)
    engine=combat._load_session(mid).engine
    lift=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.z==1)
    settle(table,mid,lift.candidate_id)
    commit(combat,table,mid,'Become unconscious')
    engine=reload(tmp_path/'unconscious',mid)
    assert engine.state.actors[OWNER].position.z==0


def test_tread_free_activation_once_and_suspension_deadline(tmp_path):
    combat, table, mid=setup(tmp_path,[SKY+'tread_the_empty_sky'],owner_speed=50)
    engine=combat._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.z==1)
    # A native high jump opens the pre-fall optional Stamina choice.
    prompts=settle(table,mid,c.candidate_id)
    assert any(p['context']['reaction_source_id']=='choice:needle.sky_tread' for p in prompts)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.resources[STAMINA]==99 and actor.position.z==1
    assert flight.profile(engine,actor).speed_ft==50
    assert not any(c.source_definition_id==sky_treading.TREAD for c in engine.legal_candidates())
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    # Decline the newly offered renewal; this test exercises the old hold's
    # printed deadline, rather than accepting renewed flight by default.
    if table.state(mid)['menu']['actor_id'] != OWNER:
        for _ in range(12):
            settle(table,mid,table.state(mid)['menu']['end_turn'], choices={'choice:needle.sky_tread':None})
            if table.state(mid)['menu']['actor_id'] == OWNER:
                break
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.position.z==1 and flight.profile(engine,actor).suspended
    assert flight.profile(engine,actor).speed_ft==0
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].position.z==0


def test_falling_star_rubble_commit_reload_and_enemy_recipients(tmp_path):
    combat, table, mid=setup(tmp_path,[NINE+'constellation_circuit',NINE+'falling_star_descent'],
                            owner_dc=50,ally_position={'x':5,'y':6})
    before=combat._load_session(mid).engine
    hp={a:before.state.actors[a].current_hp for a in (OWNER,ALLY,FOE)}
    c=candidate(combat,mid,'Falling-Star Descent',at=(5,5))
    settle(table,mid,c.candidate_id,choices={'choice:needle.area_recipients':[FOE]})
    engine=reload(tmp_path,mid)
    zones=[z for z in engine.state.zones.values() if z.active and z.source_definition_id.endswith('falling_star_descent')]
    assert zones and any(z.trigger_profile.get('difficult')=='all' and z.duration_rounds is None for z in zones)
    assert engine.state.actors[OWNER].current_hp==hp[OWNER]
    assert engine.state.actors[ALLY].current_hp==hp[ALLY]
    assert engine.state.actors[FOE].current_hp<hp[FOE]
    assert not any(e.event_type=='GM_RIDER' and e.source_definition_id.endswith('falling_star_descent') for e in engine.events)


def test_falling_star_manual_choice_includes_unseen_reachable_creature(tmp_path):
    from tests.cw2_service_support import add_action
    def prepare(bundles):
        add_action(bundles[0], 'Hide the foe', [{'type':'condition','condition':'invisible','applies_to':'target'}])
    combat,table,mid=setup(tmp_path,[NINE+'constellation_circuit',NINE+'falling_star_descent'],
                           bundle_transform=prepare,owner_dc=50)
    c=candidate(combat,mid,'Hide the foe',target=FOE);settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid);hp=engine.state.actors[FOE].current_hp
    c=candidate(combat,mid,'Falling-Star Descent',at=(5,5))
    settle(table,mid,c.candidate_id,choices={'choice:needle.area_recipients':[FOE]})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[FOE].current_hp<hp


def test_calamity_capacity_growth_expiry_and_reload(tmp_path):
    source='tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation'
    combat, table, mid=setup(tmp_path,[source])
    before=combat._load_session(mid).engine.state.actors[OWNER]
    base=before.resource_maximums['resource:named.demon_spine']
    commit(combat,table,mid,'Calamity Briar Incarnation')
    loaded=reload(tmp_path,mid);actor=loaded.state.actors[OWNER]
    assert actor.resource_maximums['resource:named.demon_spine']==base+3
    assert actor.resources['resource:named.demon_spine']==base+3
    assert actor.transformed_size_category=='Large'
    assert actor.resources[STAMINA]==93
    # Ten real rounds expire the minute; no clock or state mutation.
    for _ in range(10):
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        turn(table,mid,OWNER)
    loaded=reload(tmp_path,mid);actor=loaded.state.actors[OWNER]
    assert actor.resource_maximums['resource:named.demon_spine']==base
    assert actor.resources['resource:named.demon_spine']<=base
    assert not actor.transformed_size_category


def test_huge_stomp_after_titanic_choice_commits_and_reloads(tmp_path):
    flesh='tianxia.subpath.body.flesh_crucible.feature.'
    combat,table,mid=setup(tmp_path,[flesh+'titan_s_frame',flesh+'titanic_frame',flesh+'world_shaking_stomp'],
                           ally_position={'x':1,'y':1},foe_position={'x':6,'y':6},owner_dc=50)
    c=candidate(combat,mid,"Titan's Frame")
    settle(table,mid,c.candidate_id,choices={'choice:needle.titan_size':'Huge'})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].transformed_size_category=='Huge'
    assert not any(c.display_name.startswith('World-Shaking Stomp at') for c in engine.legal_candidates())
    c=candidate(combat,mid,'World-Shaking Stomp (40-foot cone)')
    settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid)
    assert any(z.active and z.trigger_profile.get('size_ft')==40 for z in engine.state.zones.values())


def test_mountain_demon_might_grows_active_frame_and_lengthens_push(tmp_path):
    flesh='tianxia.subpath.body.flesh_crucible.feature.'
    from tests.cw2_service_support import add_action
    def prepare(bundles):
        add_action(bundles[0],'End Might',[{'type':'remove_condition','condition':'state.mountain_demon_might','applies_to':'self'}],target='SELF')
    combat,table,mid=setup(tmp_path,[flesh+'titan_s_frame',flesh+'mountain_demon_might',flesh+'world_shaking_stomp'],
                           ally_position={'x':1,'y':1},foe_position={'x':3,'y':3},owner_dc=50,bundle_transform=prepare)
    commit(combat,table,mid,"Titan's Frame")
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    commit(combat,table,mid,'Mountain-Demon Might')
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].transformed_size_category=='Huge'
    assert engine.state.actors[OWNER].temporary_hp==36
    c=candidate(combat,mid,'World-Shaking Stomp (40-foot cone)',at=(3,3))
    settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid)
    movements=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==FOE and e.payload.get('forced')]
    assert movements
    assert sum((len(e.payload.get('path') or [])-1)*5 for e in movements)>=15


    commit(combat,table,mid,'End Might')
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert not actor.transformed_size_category
    assert not any(c.condition_id=='condition:typed.state.titan_s_frame' for c in actor.conditions.values())


def test_mountain_demon_might_lengths_body_crosses_heaven_push_on_both_saves(tmp_path):
    flesh='tianxia.subpath.body.flesh_crucible.feature.'
    from combat.ext.sky_treading import PREFIX as SKY_PREFIX
    from tests.cw2_service_support import seal
    def prepare(bundles):
        # This regression needs a hit to exercise the printed after-hit rider.
        # Seal a high native attack bonus; do not replace the roller or attack.
        strike=next(a for a in bundles[0]['action_catalog']
                    if a['source_definition_id'].endswith('.natural.unarmed_strike'))
        strike['parameters']['typed']['numbers']['attack_bonus']=100
        seal(bundles[0])
    for case, dc, expected, choices in [('failed',50,35,{'choice:needle.crosses_heaven_direction':['cell:11,0']}),
                                        ('successful',1,15,{})]:
        combat,table,mid=setup(tmp_path/case,[flesh+'mountain_demon_might',SKY_PREFIX+'body_crosses_heaven'],
                               owner_dc=dc,owner_speed=30,bundle_transform=prepare,positions={OWNER:{'x':3,'y':6},ALLY:{'x':1,'y':1},FOE:{'x':4,'y':0}})
        commit(combat,table,mid,'Mountain-Demon Might')
        settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
        engine=combat._load_session(mid).engine
        # Keep the ally clear of growth and choose an airborne endpoint explicitly:
        # six actual five-foot steps, with no overlap of the ground-level foe.
        move=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.x==3 and c.destination.y==0 and c.destination.z==1)
        settle(table,mid,move.candidate_id)
        engine=reload(tmp_path/case,mid)
        from combat.ext.sky_treading import moved_this_turn
        assert moved_this_turn(engine,engine.state.actors[OWNER]) == 30
        stamina_before=engine.state.actors[OWNER].resources['resource:core.stamina']
        strike=next(c for c in engine.legal_candidates() if c.display_name.startswith('Unarmed Strike') and c.target_ids==(FOE,))
        choices['choice:needle.body_crosses_heaven']=['use']
        settle(table,mid,strike.candidate_id,choices=choices)
        engine=reload(tmp_path/case,mid)
        attack=next(e for e in reversed(engine.events) if e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER)
        assert attack.payload.get('provisional_hit')
        assert engine.state.actors[OWNER].resources['resource:core.stamina'] == stamina_before-2
        saved=next(e for e in reversed(engine.events) if e.event_type=='SAVE_ROLLED'
                   and e.actor_id==FOE and e.source_definition_id==SKY_PREFIX+'body_crosses_heaven')
        assert (saved.payload['total'] >= saved.payload['dc']) == (case == 'successful')
        # The public forced-path resolver commits individual steps so reactions
        # can stop a route. Sum this intent's movement, rather than one segment.
        forced=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==FOE
                and e.payload.get('forced') and e.trigger_or_intent_id==attack.trigger_or_intent_id]
        assert forced and sum((len(e.payload.get('path') or [])-1)*5 for e in forced)==expected
        foe=engine.state.actors[FOE]
        assert (foe.position.x,foe.position.y,foe.position.z)==(4+expected//5,0,0)


def test_calamity_forest_lifts_enemies_and_releases_safely(tmp_path):
    from tests.cw2_service_support import add_action
    source='tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation'
    def prepare(bundles):
        add_action(bundles[0],'Release restraint',[{'type':'remove_condition','condition':'restrained','applies_to':'target'}])
    combat,table,mid=setup(tmp_path,[source],owner_dc=50,bundle_transform=prepare,
                           ally_position={'x':1,'y':1},foe_position={'x':6,'y':6})
    commit(combat,table,mid,'Calamity Briar Incarnation')
    ally_hp=combat._load_session(mid).engine.state.actors[ALLY].current_hp
    commit(combat,table,mid,'Forest of Impalement')
    engine=reload(tmp_path,mid);foe=engine.state.actors[FOE]
    assert foe.position.z==2
    assert any(c.condition_id=='condition:typed.restrained' for c in foe.conditions.values())
    assert engine.state.actors[ALLY].current_hp==ally_hp
    hp=foe.current_hp
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    c=candidate(combat,mid,'Release restraint',target=FOE)
    settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid);foe=engine.state.actors[FOE]
    assert foe.position.z==0 and foe.current_hp==hp




@pytest.mark.parametrize('release_newest', [False, True])
def test_calamity_forest_independent_release_preserves_other_hold(tmp_path, monkeypatch, release_newest):
    """Two genuine Forest intents; exact-instance release uses the public cleanup helper.

    A sealed setup effect removes only the selected receipt's restraint, like a
    successful repeat save. It never replaces engine or production methods.
    """
    from combat import ext
    from combat.ext.condition_ownership import remove_instance
    from tests.cw2_service_support import add_action
    def release_one(ctx, row):
        holds = [c for c in ctx.target.conditions.values()
                 if c.condition_id == 'condition:typed.forest_lift']
        held = holds[-1 if release_newest else 0]
        remove_instance(ctx.engine, ctx.target, held.data['restraint'], ctx.source)
    monkeypatch.setitem(ext.effects(), 'test_release_one_hold', release_one)
    def prepare(bundles):
        add_action(bundles[0], 'Release one hold',
                   [{'type':'test_release_one_hold','applies_to':'target'}])
        add_action(bundles[0], 'Protect target for repeated Forest',
                   [{'type':'temp_hp','flat':1000,'applies_to':'target'}])
        add_action(bundles[0], 'Restore Spines',
                   [{'type':'gain_resource','resource_id':'resource:named.demon_spine','flat':10,'applies_to':'self'}], target='SELF')
    source='tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation'
    combat,table,mid=setup(tmp_path,[source],owner_dc=50,bundle_transform=prepare,
                           ally_position={'x':1,'y':1},foe_position={'x':6,'y':6})
    c=candidate(combat,mid,'Protect target for repeated Forest',target=FOE)
    settle(table,mid,c.candidate_id)
    commit(combat,table,mid,'Calamity Briar Incarnation')
    commit(combat,table,mid,'Forest of Impalement')
    first=reload(tmp_path,mid).state.actors[FOE]
    assert first.position.z == 2
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    commit(combat,table,mid,'Restore Spines')
    commit(combat,table,mid,'Forest of Impalement')
    engine=reload(tmp_path,mid);foe=engine.state.actors[FOE]
    holds=[c for c in foe.conditions.values() if c.condition_id=='condition:typed.forest_lift']
    assert len(holds)==2 and foe.position.z==4
    assert len({c.data['restraint'] for c in holds})==2
    assert all(c.data['restraint'] in foe.conditions for c in holds)
    removed=holds[-1 if release_newest else 0]
    survivor=holds[0 if release_newest else -1]
    hp=foe.current_hp; temporary_hp=foe.temporary_hp
    c=candidate(combat,mid,'Release one hold',target=FOE);settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid);foe=engine.state.actors[FOE]
    assert foe.position.z==4
    assert removed.instance_id not in foe.conditions and removed.data['restraint'] not in foe.conditions
    assert survivor.instance_id in foe.conditions and survivor.data['restraint'] in foe.conditions
    assert flight.profile(engine,foe).suspended
    assert not any(e.event_type=='MOVEMENT_COMMITTED' and e.payload.get('safe_landing') for e in engine.events)
    c=candidate(combat,mid,'Release one hold',target=FOE);settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid);foe=engine.state.actors[FOE]
    assert foe.position.z==0 and foe.current_hp==hp and foe.temporary_hp==temporary_hp
    assert not any(c.condition_id=='condition:typed.forest_lift' for c in foe.conditions.values())
    landings=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.payload.get('safe_landing')]
    assert len(landings)==1

def test_calamity_forest_lift_respects_forced_movement_protection_after_reload(tmp_path):
    from tests.cw2_service_support import add_action
    source='tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation'
    def prepare(bundles):
        add_action(bundles[2], 'Become anchored',
                   [{'type':'state','name':'nine_star_incarnation','duration':'one_minute'},
                    {'type':'general_flight','speed_ft':30,'hover':True,'applies_to':'self',
                     'duration':{'kind':'minutes','amount':1}}], target='SELF')
        add_action(bundles[2], 'End original flight',
                   [{'type':'remove_condition','condition':'general_flight','applies_to':'self'}], target='SELF')
    combat,table,mid=setup(tmp_path,[source],owner_dc=50,bundle_transform=prepare,
                           ally_position={'x':1,'y':1},foe_position={'x':6,'y':6})
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,ALLY)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,FOE)
    c=candidate(combat,mid,'Become anchored');settle(table,mid,c.candidate_id)
    assert any(c.condition_id=='condition:typed.state.nine_star_incarnation'
               for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
    from combat.flight import profile
    assert profile(reload(tmp_path,mid),reload(tmp_path,mid).state.actors[FOE]).speed_ft == 30
    # Establish the edge case through the player's ordinary movement intent:
    # the target is already flying before Forest's protected lift is refused.
    airborne=next(c for c in combat._load_session(mid).engine.legal_candidates()
                  if c.kind=='MOVE' and c.destination.z==1)
    settle(table,mid,airborne.candidate_id)
    airborne_state=reload(tmp_path,mid);airborne_foe=airborne_state.state.actors[FOE]
    assert airborne_foe.position.z==1 and profile(airborne_state,airborne_foe).speed_ft == 30
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,ALLY)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    commit(combat,table,mid,'Calamity Briar Incarnation')
    commit(combat,table,mid,'Forest of Impalement')
    engine=reload(tmp_path,mid);foe=engine.state.actors[FOE]
    assert foe.position.z==1
    assert not any(c.condition_id=='condition:typed.forest_lift' for c in foe.conditions.values())
    assert not any(c.data.get('flight_suspended') for c in foe.conditions.values()), \
        'a blocked Forest lift must not leave its temporary flight suspension on the restraint'
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,FOE)
    c=candidate(combat,mid,'End original flight');settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid);foe=engine.state.actors[FOE]
    assert foe.position.z==0 and not any(c.data.get('flight_suspended') for c in foe.conditions.values())


@pytest.mark.parametrize('with_ceiling', [False, True])
def test_calamity_forest_ceiling_block_cleans_up_after_reload(tmp_path, monkeypatch, with_ceiling):
    """A sealed low ceiling blocks vertical occupancy through the actual service path."""
    import copy
    from tests.cw2_service_support import add_action
    from tests.worker2_support import CombatService
    original = CombatService.factory_arenas
    def low_ceiling(service, *, include_retired=False):
        arenas = copy.deepcopy(original(service, include_retired=include_retired))
        arenas['battlefield:factory_pillar_arena']['terrain_regions'].append({
            'terrain_type': 'BLOCKED', 'height_ft': 5, 'base_altitude_ft': 5,
            'movement_cost': 5, 'cells': [{'x': 6, 'y': 6}]})
        return arenas
    if with_ceiling:
        monkeypatch.setattr(CombatService, 'factory_arenas', low_ceiling)
    source='tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation'
    combat,table,mid=setup(tmp_path,[source],owner_dc=50,
                           ally_position={'x':1,'y':1},foe_position={'x':6,'y':6})
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,ALLY)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,FOE)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,ALLY)
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    commit(combat,table,mid,'Calamity Briar Incarnation')
    commit(combat,table,mid,'Forest of Impalement')
    foe=reload(tmp_path,mid).state.actors[FOE]
    assert foe.position.z==(0 if with_ceiling else 2)
    holds=[c for c in foe.conditions.values() if c.condition_id=='condition:typed.forest_lift']
    assert len(holds)==(0 if with_ceiling else 1)
    if holds:
        assert holds[0].data['restraint'] in foe.conditions
    else:
        assert not any(c.data.get('flight_suspended') for c in foe.conditions.values())

def test_calamity_healing_threshold_and_minimum(tmp_path):
    from tests.cw2_service_support import add_action
    source='tianxia.subpath.body.black_thorn_demon_body.feature.calamity_briar_incarnation'
    def prepare(bundles):
        add_action(bundles[0],'Prepare injury',[{'type':'damage','flat':30,'damage_types':['force'],'applies_to':'self'}])
        add_action(bundles[0],'Restore self ten',[{'type':'healing','flat':10,'applies_to':'self'}],target='SELF')
        add_action(bundles[0],'Spend six spines',[{'type':'spend_resource','resource_id':'resource:named.demon_spine','flat':6,'applies_to':'self'}],target='SELF')
        add_action(bundles[1],'Restore ten',[{'type':'healing','flat':10,'applies_to':'target'}])
        add_action(bundles[1],'Restore one',[{'type':'healing','flat':1,'applies_to':'target'}])
    combat,table,mid=setup(tmp_path,[source],bundle_transform=prepare,ally_position={'x':1,'y':1})
    commit(combat,table,mid,'Prepare injury')
    commit(combat,table,mid,'Calamity Briar Incarnation')
    before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,ALLY)
    c=candidate(combat,mid,'Restore ten',target=OWNER);settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.current_hp==before+10-actor.proficiency_bonus
    # At or above six Spines, the reduction never turns a one-point heal into zero.
    before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    c=candidate(combat,mid,'Restore one',target=OWNER);settle(table,mid,c.candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].current_hp==before+1
    # Self healing is exempt even above the special six-Spine threshold.
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    c=candidate(combat,mid,'Restore self ten');settle(table,mid,c.candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].current_hp==before+10
    # Below six Spines, healing from another creature is no longer reduced.
    engine=reload(tmp_path,mid);before_spines=engine.state.actors[OWNER].resources['resource:named.demon_spine']
    assert before_spines >= 6
    c=candidate(combat,mid,'Spend six spines');settle(table,mid,c.candidate_id)
    engine=reload(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.resources['resource:named.demon_spine'] == before_spines-6
    assert actor.resources['resource:named.demon_spine'] < 6
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,ALLY)
    before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    c=candidate(combat,mid,'Restore ten',target=OWNER);settle(table,mid,c.candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].current_hp==before+10
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,ALLY)
    before=reload(tmp_path,mid).state.actors[OWNER].current_hp
    c=candidate(combat,mid,'Restore one',target=OWNER);settle(table,mid,c.candidate_id)
    assert reload(tmp_path,mid).state.actors[OWNER].current_hp==before+1


def test_automatic_descent_recipient_choice_spares_allies(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat,table,mid=setup(tmp_path,[NINE+'constellation_circuit',NINE+'falling_star_descent'],
                           ally_position={'x':5,'y':6},owner_dc=50)
    before=reload(tmp_path,mid)
    hp={who:before.state.actors[who].current_hp for who in (OWNER,ALLY,FOE)}
    c=candidate(combat,mid,'Falling-Star Descent',at=(5,5))
    real=combat.controller
    combat.controller=ManualControllerAdapter(lambda context:(c.candidate_id,()),
        reaction_chooser=lambda context:real.choose_reaction(context).decision)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    settle(table,mid,c.candidate_id,auto=True)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].current_hp==hp[OWNER]
    assert engine.state.actors[ALLY].current_hp==hp[ALLY]
    assert engine.state.actors[FOE].current_hp<hp[FOE]
