"""Black-Thorn native table commits, earned resources, cold reload and replay.

No saved balance, ownership receipt, or trigger event is inserted into a fight.
The character compiler admits the fixture's source features; hostile native
attacks earn each ordinary Spine used below.
"""
from combat.ext.black_thorn_demon_body import SUBPATH, SPINE, BRIAR, VIOLENCE
BLEEDING = 'condition:typed.thorn_bleeding'
from tests.worker2_support import (
    fixture, settle, reload, candidate, turn, sealed_native_attack, OWNER, ALLY, FOE,
)
from tests.h1_support import sheet
from tests.test_ns1r_non_sphere_authority import authority, insert_project, BODY
from tests.ns1r_evidence_helpers import commit_authority_event

FEATURES = [SUBPATH + name for name in (
    'thorn_flesh_armory', 'spines_answer_violence', 'impaling_garden',
    'crown_of_black_thorns', 'calamity_briar_incarnation',
)]


def setup(tmp_path, authority, features=FEATURES, prepare_extra=None, **kwargs):
    cl = 18
    if features:
        service, db = authority
        selected = SUBPATH.removesuffix('.feature.')
        cl = max((3,6,10,14,18)[FEATURES.index(feature)] for feature in features)
        insert_project(db, 'black-thorn-owner', target_cl=cl)
        method_access = commit_authority_event(db, service, 'black-thorn-owner', 'method_access',
            {'method_id':'METHOD-002'})
        service.initialize_for_project('black-thorn-owner', target_cl=cl,
            path_ids=[BODY], method_id='METHOD-002', path_attainment_by_id={BODY:cl},
            access_source_records=[method_access])
        access = commit_authority_event(db, service, 'black-thorn-owner', 'subpath_access',
            {'selection_id':selected, 'path_id':BODY})
        state = service.select_subpath('black-thorn-owner', BODY, selected, access_source_records=[access])
        assert next(p for p in state['paths'] if p['path_id']==BODY)['subpath_or_tradition_id'] == selected
        # Native acquisition chooses the one parent. Its authenticated printed
        # progression derives every lower row, never only the indexed leaf.
        record = service.project_locked_subpath_catalog_record(selected)
        progression = record['compatibility']['factory']['stage2_authority']['feature_progression']
        features = [row['canonical_id'] for row in progression if row['granted_at_cl'] <= cl]
        assert features == FEATURES[:(3,6,10,14,18).index(cl)+1]
    foe = sheet([], cl=18, name='Mara')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 600
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 1
    def prepare(bundles):
        sealed_native_attack(bundles[2], 'Hostile blade', damage_type='PIERCING',
                             count=1, sides=4, modifier=2, range_ft=5, attack_bonus=50)
        if prepare_extra:
            prepare_extra(bundles)
    return fixture(tmp_path, [], owner_features=features, owner_path='Body Refining',
        cl=cl, primary='Stamina', owner_dc=50, owner_ac=0, foe_sheet=foe,
        owner_pb=2+(cl-1)//4, named=True, bundle_transform=prepare,
        foe_position={'x':4,'y':6}, ally_position={'x':3,'y':9}, **kwargs)


def use(combat, table, mid, name, **kwargs):
    c = candidate(combat, mid, name, **kwargs)
    return settle(table, mid, c.candidate_id, choices={})


def earn(combat, table, mid, count=1):
    for _ in range(count):
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
        turn(table, mid, FOE)
        use(combat, table, mid, 'Hostile blade', target=OWNER)
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
        turn(table, mid, OWNER)


def strike(combat, table, mid):
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.target_ids == (FOE,)
             and 'unarmed' in engine.action_catalog[c.source_definition_id].display_name.lower()
             and 'extended reach' not in engine.action_catalog[c.source_definition_id].display_name.lower())
    return settle(table, mid, c.candidate_id, choices={'choice:needle.thorn_flesh_armory':['spend']})


def test_armory_earned_spine_delayed_movement_damage_and_reload(tmp_path, authority):
    combat, table, mid = setup(tmp_path, authority, FEATURES[:1])
    assert reload(tmp_path, mid).state.actors[OWNER].resources[SPINE] == 0
    earn(combat, table, mid)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[SPINE] == 1
    strike(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[SPINE] == 0
    assert any(c.data.get('thorn_bleeding') for c in engine.state.actors[FOE].conditions.values())
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, FOE)
    hp = reload(tmp_path, mid).state.actors[FOE].current_hp
    for x in (5, 6):
        engine = combat._load_session(mid).engine
        c = next(c for c in engine.legal_candidates() if c.kind == 'MOVE'
                 and c.destination.x == x and c.destination.y == 6 and c.destination.z == 0)
        settle(table, mid, c.candidate_id, choices={})
        engine = reload(tmp_path, mid)
        assert engine.state.actors[FOE].current_hp == hp - (2 if x == 6 else 0)
    assert not any(c.data.get('thorn_bleeding') for c in engine.state.actors[FOE].conditions.values())
    assert not any(e.event_type == 'GM_RIDER' and 'lock round 3' in str(e.payload) for e in engine.events)


def test_garden_earned_spines_field_restraint_and_expiry(tmp_path, authority):
    combat, table, mid = setup(tmp_path, authority, [FEATURES[2]])
    earn(combat, table, mid, 2)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.stamina']
    use(combat, table, mid, 'Impaling Garden')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[SPINE] == 0
    assert engine.state.actors[OWNER].resources['resource:core.stamina'] == before - 3
    assert any(c.condition_id.endswith('.restrained') for c in engine.state.actors[FOE].conditions.values())
    assert any(c.data.get('thorn_bleeding') for c in engine.state.actors[FOE].conditions.values())
    assert any(z.trigger_profile.get('follows_owner') and z.trigger_profile.get('difficult') == 'hostile'
               for z in engine.state.zones.values())
    assert not engine.state.actors[ALLY].conditions
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id.endswith('.restrained') for c in engine.state.actors[FOE].conditions.values())


def test_incarnation_and_forest_native_capacity_reach_lift_and_reload(tmp_path, authority):
    from combat.ext.reach_bonus import natural_reach_ft
    combat, table, mid = setup(tmp_path, authority)
    use(combat, table, mid, 'Calamity Briar Incarnation')
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[SPINE] == actor.resource_maximums[SPINE] == 9
    assert natural_reach_ft(engine, actor) == 15
    assert engine._footprint(actor).width_cells == 2
    # Query guard on the actual native transformed body: a Large creature's
    # reaction reach starts at its occupied volume, not its anchor square.
    from combat.gate2_runtime_models import Position
    from combat.typed_reactions import _rows, _generic_in_range
    row = next(r for r in _rows(engine, OWNER, 'generic') if r.get('feature_id') == VIOLENCE)
    boundary = next(Position(x=x,y=y) for x in range(engine.grid.width) for y in range(engine.grid.height)
        if engine.grid.distance_ft(actor.position, Position(x=x,y=y)) > 15
        and engine._distance_actor_to_cell(actor, Position(x=x,y=y)) <= 15)
    source = engine.state.actors[FOE].model_copy(update={'position':boundary})
    assert _generic_in_range(engine, actor, source, row)
    use(combat, table, mid, 'Forest of Impalement')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[SPINE] == 5
    assert engine.state.actors[FOE].position.z == 2
    assert any(c.data.get('forest_lift') for c in engine.state.actors[FOE].conditions.values())
    restraint = next(c for c in engine.state.actors[FOE].conditions.values() if c.data.get('forest_lift'))
    assert restraint.expires_on == 'UNTIL_REMOVED' and restraint.data['repeat_save']['ability'] == 'DEX'
    assert not any(c.kind == 'ACTION' and engine.action_catalog[c.source_definition_id].display_name == 'Calamity Briar Incarnation'
                   for c in engine.legal_candidates())


def test_unowned_default_inert_and_normal_hp_only_pool(tmp_path, authority):
    combat, table, mid = setup(tmp_path, authority, [])
    earn(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert SPINE not in engine.state.actors[OWNER].resources
    assert not any(c.data.get('thorn_bleeding') for a in engine.state.actors.values() for c in a.conditions.values())


def test_crown_willing_distance_stops_first_qualifying_space(tmp_path, authority):
    combat, table, mid = setup(tmp_path, authority, [FEATURES[3]])
    earn(combat, table, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    # Two separately committed five-foot steps inside reach share the same
    # distance record, including a cold reload between the steps.
    for cell in ((4,5), (3,5)):
        c = next(c for c in engine.legal_candidates() if c.kind == 'MOVE'
                 and (c.destination.x,c.destination.y,c.destination.z) == (*cell,0))
        prompts = settle(table, mid, c.candidate_id,
            choices={'choice:needle.black_thorn_crown':['spend']})
        engine = reload(tmp_path, mid)
    assert any('Mara' in p.get('moment','') and 'Crown of Black Thorns' in p.get('moment','') for p in prompts)
    assert engine.state.actors[OWNER].resources[SPINE] == 0
    assert any(c.data.get('thorn_bleeding') for c in engine.state.actors[FOE].conditions.values())
    committed = next(e for e in reversed(engine.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE)
    assert committed.payload.get('interruptions')
    held = next(c for c in engine.state.actors[FOE].conditions.values() if c.data.get('thorn_bleeding'))
    assert held.data['thorn_bleeding']['moved_ft'] == 0, 'Movement before Crown applied Bleeding must not count'


def test_violence_earned_spine_reaction_precedes_hostile_damage(tmp_path, authority):
    combat, table, mid = setup(tmp_path, authority, [FEATURES[1]])
    earn(combat, table, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, FOE)
    c = candidate(combat, mid, 'Hostile blade', target=OWNER)
    prompts = settle(table, mid, c.candidate_id, choices={'reaction:typed.'+VIOLENCE:'first'})
    engine = reload(tmp_path, mid)
    assert prompts
    # Find the final retaliation and blade packets regardless of the final
    # transaction bookkeeping event's intent identity.
    retaliation = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER)
    incoming = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == FOE)
    assert retaliation.sequence < incoming.sequence
    assert not engine.state.actors[OWNER].reaction_available
    # Spines Answer Violence applies Bleeding before the triggering hit's damage. The hit is itself an attack by
    # the Bleeding creature, so Bleeding ends on that attack: its delayed damage is committed after the hit, and
    # the record is gone at the end (it is not still held).
    applied = next(e for e in engine.events if e.event_type == 'CONDITION_APPLIED' and FOE in e.target_ids
                   and e.payload.get('condition_id') == BLEEDING)
    removed = next(e for e in engine.events if e.event_type == 'CONDITION_REMOVED' and FOE in e.target_ids
                   and e.payload.get('condition_id') == BLEEDING)
    pulse = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER
             and e.target_ids == (FOE,) and e.sequence > removed.sequence]
    assert applied.sequence < incoming.sequence < removed.sequence
    assert pulse, 'Bleeding must deal its delayed damage after the attack it ends on'
    assert pulse[0].payload['hp_damage'] == engine.state.actors[OWNER].proficiency_bonus
    assert not any(c.data.get('thorn_bleeding') for c in engine.state.actors[FOE].conditions.values())


def test_temporary_hp_only_damage_does_not_generate_a_spine(tmp_path, authority):
    from tests.cw2_service_support import add_action
    def prepare(bundles):
        add_action(bundles[0], 'Test temporary buffer', [
            {'type':'temp_hp','applies_to':'self','flat':30}], target='SELF')
    combat, table, mid = setup(tmp_path, authority, FEATURES[:1], prepare_extra=prepare)
    use(combat, table, mid, 'Test temporary buffer')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 30
    hp = engine.state.actors[OWNER].current_hp
    earn(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == hp
    assert engine.state.actors[OWNER].resources[SPINE] == 0


def test_successful_grapple_offers_violence_and_keeps_the_hold(tmp_path, authority):
    from tests.cw2_service_support import seal
    def prepare(bundles):
        for action in bundles[2]['action_catalog']:
            typed = action.get('parameters',{}).get('typed',{})
            if typed.get('unarmed_option') == 'grapple':
                typed['numbers']['save_dc'] = 100
        seal(bundles[2])
    combat, table, mid = setup(tmp_path, authority, FEATURES[:2], prepare_extra=prepare)
    earn(combat, table, mid, 2)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, FOE)
    c = candidate(combat, mid, 'Grapple', target=OWNER)
    prompts = settle(table, mid, c.candidate_id, choices={'reaction:typed.'+VIOLENCE:'first'})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'reaction:typed.'+VIOLENCE for p in prompts)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == VIOLENCE
               and e.payload.get('checkpoint') == 'GRAPPLE_ESTABLISHED' for e in engine.events)
    assert any(c.condition_id == 'condition:typed.grappled' and c.source_actor_id == FOE
               for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[FOE].position.x == 4
    assert not engine.state.actors[OWNER].reaction_available
    # One new round renews the limit, without fabricating another Grapple.
    # The actual end-turn caller must pause for the manual owner on the
    # grappler's turn before it can move the held creature.
    later = settle(table, mid, table.state(mid)['menu']['end_turn'],
                   choices={'reaction:typed.'+VIOLENCE:'first'})
    for _ in range(6):
        if table.state(mid)['menu']['actor_id'] == FOE:
            break
        later += settle(table, mid, table.state(mid)['menu']['end_turn'],
                        choices={'reaction:typed.'+VIOLENCE:'first'})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'reaction:typed.'+VIOLENCE for p in later)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == VIOLENCE
               and e.payload.get('checkpoint') == 'GRAPPLER_TURN_START' for e in engine.events)
    assert sum(e.event_type == 'CONDITION_APPLIED' and e.payload.get('condition_id') == 'condition:typed.grappled'
               for e in engine.events) == 1
    assert engine.state.actors[OWNER].resources[SPINE] == 0


def test_healing_threshold_changes_during_incarnation(tmp_path, authority):
    from tests.cw2_service_support import add_action
    def prepare(bundles):
        add_action(bundles[1], 'Test healing instance', [
            {'type':'healing','applies_to':'target','flat':10}])
    combat, table, mid = setup(tmp_path, authority, prepare_extra=prepare)
    earn(combat, table, mid, 3)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[SPINE] == 3
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, ALLY)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    before, maximum = actor.current_hp, actor.maximum_hp
    use(combat, table, mid, 'Test healing instance', target=OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp == min(maximum, before+4)
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Calamity Briar Incarnation')
    use(combat, table, mid, 'Forest of Impalement')
    assert reload(tmp_path, mid).state.actors[OWNER].resources[SPINE] == 5
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid).state.actors[OWNER].current_hp
    use(combat, table, mid, 'Test healing instance', target=OWNER)
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp == min(maximum, before+10)


def test_native_checkpoint_requires_an_owned_row_filter():
    import pytest
    from combat.typed_reactions import on_own_event
    with pytest.raises(ValueError, match='owned-row filter'):
        on_own_event(None, None, None, 'hit', checkpoint='GRAPPLE_ESTABLISHED')
    from combat.movement_steps import checkpoint
    with pytest.raises(ValueError, match='entered willing movement'):
        checkpoint(None, None, None, None, None, travelled_ft=0, remaining_ft=0,
                   point='forced_movement_step', settled_only=True)


def test_same_team_hostility_is_source_declared_private_and_replayed(tmp_path, authority):
    from tests.cw2_service_support import seal
    from combat.fact_consent_admission import combat_records
    def prepare(bundles):
        sid = sealed_native_attack(bundles[1], 'Ally needle', damage_type='PIERCING',
            count=1, sides=4, modifier=2, range_ft=60, attack_bonus=50)
        next(a for a in bundles[1]['action_catalog'] if a['source_definition_id'] == sid)['target_kind'] = 'ANY_CREATURE'
        seal(bundles[1])
    combat, table, mid = setup(tmp_path, authority, FEATURES[:1], prepare_extra=prepare)
    turn(table, mid, ALLY)
    choice = 'choice:needle.fact_admission.qualifying_hostility'
    c = candidate(combat, mid, 'Ally needle', target=OWNER)
    prompts = settle(table, mid, c.candidate_id, choices={choice:['excluded']})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reactor_id'] == ALLY and p['context']['reaction_source_id'] == choice for p in prompts)
    assert engine.state.actors[OWNER].resources[SPINE] == 0
    assert combat_records(engine, engine.state.actors[ALLY], kind='qualifying_hostility')[-1]['value'] == 'excluded'
    assert combat_records(engine, engine.state.actors[OWNER], kind='qualifying_hostility') == []
    assert combat_records(engine, engine.state.actors[FOE], kind='qualifying_hostility') == []
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, ALLY)
    c = candidate(combat, mid, 'Ally needle', target=OWNER)
    settle(table, mid, c.candidate_id, choices={choice:['hostile']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[SPINE] == 1
    record = combat_records(engine, engine.state.actors[ALLY], kind='qualifying_hostility')[-1]
    assert record['authority'] == ALLY and record['subject'] == ALLY
    assert record['intent_id'] and record['receipt_id'] and record['readers'] == []


def test_normal_gain_is_reserved_before_nested_native_subscribers(tmp_path, authority, monkeypatch):
    from combat import ext
    from combat.ext.subpath_pools import gain
    combat, table, mid = setup(tmp_path, authority, FEATURES[:1])
    observed = []
    def nested(engine, event):
        if event.event_type == 'RESOURCE_GAINED' and event.payload.get('resource_id') == SPINE:
            observed.append(gain(engine, engine.state.actors[OWNER], SPINE, 'test:nested-normal-gain'))
    monkeypatch.setitem(ext._HOOKS, 'state_event', [*ext._HOOKS.get('state_event', ()), nested])
    earn(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert observed and all(amount == 0 for amount in observed)
    assert engine.state.actors[OWNER].resources[SPINE] == 1
