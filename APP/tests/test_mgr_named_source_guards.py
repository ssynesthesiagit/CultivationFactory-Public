"""Native table guard tests for the general suppression/debit interfaces.

These scenario-authored sources test the shared contract only; they are not
acquisition evidence or whole-row certification for a cultivation feature.
"""
from combat.ext.general_flight_skills import FLIGHT_CONDITION
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, fixture, candidate, reload, settle, turn

QI = 'resource:core.qi'


def test_volume_teleport_query_adds_elevated_landings_without_changing_default(tmp_path):
    from combat.ext.teleport_steps import destinations, destination_allowed
    from combat.gate2_runtime_models import Position
    combat, table, mid = fixture(tmp_path, [], seed='MGR-VOLUME-TELEPORT')
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    above = Position(x=actor.position.x, y=actor.position.y, z=actor.position.z + 1)
    assert above not in destinations(engine, actor, 5)
    assert above in destinations(engine, actor, 5, volume=True)
    assert destination_allowed(engine, actor, above, 5, volume=True)
    assert not destination_allowed(engine, actor, Position(x=above.x, y=above.y, z=above.z + 2), 5, volume=True)


def source_id(bundle, name):
    return next(a['source_definition_id'] for a in bundle['action_catalog'] if a['display_name'] == name)


def test_named_source_suspends_and_restores_original_instance_without_refresh(tmp_path):
    def prepare(bundles):
        # applies_to is required by the general_flight grant's own validation (main 93e9ef7a); this branch-only
        # guard predates it and cannot run against current main without the named recipient.
        add_action(bundles[1], 'Guard flight', [{'type': 'general_flight', 'applies_to': 'self', 'speed_ft': 30,
            'hover': True, 'duration': {'kind': 'minutes', 'amount': 1}}], target='SELF')
        flying = source_id(bundles[1], 'Guard flight')
        add_action(bundles[0], 'Guard named suppression', [{'type': 'cultivation_suppression',
            'suppressed_sources': [flying], 'applies_to': 'target',
            'duration': 'until_start_of_your_next_turn', 'label': 'Guard flight is suppressed'}])
    combat, table, mid = fixture(tmp_path, [], bundle_transform=prepare, seed='MGR-NAMED-SOURCE')
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Guard flight').candidate_id)
    before = reload(tmp_path, mid)
    original = next(c for c in before.state.actors[ALLY].conditions.values() if c.condition_id == FLIGHT_CONDITION)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Guard named suppression', target=ALLY).candidate_id)
    paused = reload(tmp_path, mid)
    assert not any(c.condition_id == FLIGHT_CONDITION for c in paused.state.actors[ALLY].conditions.values())
    assert any(c.condition_id == 'condition:typed.benefit_suppressed' for c in paused.state.actors[ALLY].conditions.values())
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert not any(getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Guard flight'
                   for c in engine.legal_candidates())
    turn(table, mid, OWNER)
    restored = reload(tmp_path, mid).state.actors[ALLY].conditions[original.instance_id]
    assert restored.expires_on == original.expires_on
    assert restored.source_definition_id == original.source_definition_id
    assert restored.source_actor_id == original.source_actor_id


def test_blocked_pool_hides_paid_commands_only_for_the_bound_actor(tmp_path):
    def prepare(bundles):
        for bundle in bundles[:2]:
            add_action(bundle, 'Guard paid technique', [{'type': 'temp_hp', 'applies_to': 'self', 'flat': 1}], target='SELF')
            action = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Guard paid technique')
            action['costs'] = [[QI, 1]]
            seal(bundle)
        add_action(bundles[0], 'Guard resource seal', [{'type': 'cultivation_suppression',
            'suppressed_sources': ['source:guard.unrelated'], 'blocked_pools': [QI], 'applies_to': 'target',
            'duration': 'until_start_of_your_next_turn', 'label': 'Guard: spending and regaining Qi blocked'}])
    combat, table, mid = fixture(tmp_path, [], bundle_transform=prepare, seed='MGR-BLOCKED-POOL')
    settle(table, mid, candidate(combat, mid, 'Guard resource seal', target=ALLY).candidate_id)
    before = reload(tmp_path, mid)
    own_qi = before.state.actors[OWNER].resources[QI]
    ally_qi = before.state.actors[ALLY].resources[QI]
    settle(table, mid, candidate(combat, mid, 'Guard paid technique').candidate_id)
    after = reload(tmp_path, mid)
    assert after.state.actors[OWNER].resources[QI] == own_qi - 1
    assert after.state.actors[ALLY].resources[QI] == ally_qi
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert not any(getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Guard paid technique'
                   for c in engine.legal_candidates())


def test_overlapping_named_suppressions_keep_captures_until_the_last_ends(tmp_path):
    """F6R fix 3: two overlapping named suppressions cover one system of the same creature. When the first
    ends, the captured benefit must stay suppressed through the remaining marker, because the release check
    matches the captured action's typed parent (option_of) and not only its raw action id. The old raw-id-only
    check found the action id in no remaining scope and restored the second suppressor's capture early."""
    parent = 'source:guard.storm_core'

    def prepare(bundles):
        add_action(bundles[1], 'Guard flight', [{'type': 'general_flight', 'applies_to': 'self', 'speed_ft': 30,
            'hover': True, 'duration': {'kind': 'minutes', 'amount': 1}}], target='SELF', typed={'option_of': parent})
        add_action(bundles[0], 'Guard short suppression', [{'type': 'cultivation_suppression',
            'suppressed_sources': [parent], 'applies_to': 'target',
            'duration': 'until_start_of_your_next_turn', 'label': 'Guard: storm core suppressed'}])
        add_action(bundles[0], 'Guard long suppression', [{'type': 'cultivation_suppression',
            'suppressed_sources': [parent], 'applies_to': 'target',
            'duration': {'kind': 'rounds', 'amount': 6}, 'label': 'Guard: storm core suppressed longer'}])
    combat, table, mid = fixture(tmp_path, [], bundle_transform=prepare, seed='MGR-TWO-MARKERS')
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Guard flight').candidate_id)
    before = reload(tmp_path, mid)
    original = next(c for c in before.state.actors[ALLY].conditions.values() if c.condition_id == FLIGHT_CONDITION)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Guard short suppression', target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Guard long suppression', target=ALLY).candidate_id)
    paused = reload(tmp_path, mid)
    assert not any(c.condition_id == FLIGHT_CONDITION for c in paused.state.actors[ALLY].conditions.values())
    assert any(c.condition_id == 'condition:typed.benefit_suppressed' for c in paused.state.actors[ALLY].conditions.values())
    # The short marker ends at the start of the OWNER's next turn; the remaining long marker keeps the capture.
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    between = reload(tmp_path, mid)
    assert not any(c.condition_id == FLIGHT_CONDITION for c in between.state.actors[ALLY].conditions.values())
    assert any(c.condition_id == 'condition:typed.benefit_suppressed'
               and (c.data or {}).get('until') == 'cultivation_source'
               for c in between.state.actors[ALLY].conditions.values())
    # Only the last remaining marker's ending releases the benefit, with its original clock.
    engine = None
    for _ in range(10):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, ALLY)
        engine = reload(tmp_path, mid)
        if any(c.condition_id == FLIGHT_CONDITION for c in engine.state.actors[ALLY].conditions.values()):
            break
    else:
        raise AssertionError('flight never returned')
    restored = engine.state.actors[ALLY].conditions[original.instance_id]
    assert restored.expires_on == original.expires_on
    assert restored.source_definition_id == original.source_definition_id
    assert restored.source_actor_id == original.source_actor_id


def test_overlapping_named_suppressions_keep_the_area_suppressed(tmp_path):
    """F6R fix 3, area side: two overlapping named suppressions take the same creature's area. The first
    capture holds the only suppression record (the second took nothing: the cells were already gone), so
    when the first ends early its captured areas must be handed to the remaining marker instead of being
    restored. The old code restored the first marker's record outright, freeing a still-suppressed area."""
    def prepare(bundles):
        add_action(bundles[1], 'Guard ground fire', [], target='SELF', typed={'zone_spec': {
            'name': 'Guard ground fire', 'centered_on_self': True, 'shape': 'radius', 'size_ft': 5, 'height_ft': 5}})
        ground = next(a['source_definition_id'] for a in bundles[1]['action_catalog'] if a['display_name'] == 'Guard ground fire')
        add_action(bundles[0], 'Guard short area seal', [{'type': 'cultivation_suppression',
            'suppressed_sources': [ground], 'applies_to': 'target',
            'duration': 'until_start_of_your_next_turn', 'repeat_save': {'ability': 'CHA', 'dc': 1},
            'label': 'Guard: ground fire suppressed (short)'}])
        add_action(bundles[0], 'Guard long area seal', [{'type': 'cultivation_suppression',
            'suppressed_sources': [ground], 'applies_to': 'target',
            'duration': {'kind': 'rounds', 'amount': 5},
            'label': 'Guard: ground fire suppressed (long)'}])
    combat, table, mid = fixture(tmp_path, [], bundle_transform=prepare, seed='MGR-TWO-AREA-MARKERS')
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Guard ground fire').candidate_id)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Guard short area seal', target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Guard long area seal', target=ALLY).candidate_id)
    before = reload(tmp_path, mid)
    from combat.ext.area_suppression import records as area_records
    zone = next(z for z in before.state.zones.values() if z.active and z.owner_id == ALLY)
    assert area_records(zone) and not zone.affected_cells
    # The first marker ends early (repeat save succeeds) on the ALLY's turn end; the remaining long marker
    # keeps the area's squares out of play.
    turn(table, mid, ALLY)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    between = reload(tmp_path, mid)
    between_zone = next(z for z in between.state.zones.values() if z.active and z.owner_id == ALLY)
    assert area_records(between_zone) and not between_zone.affected_cells
    # Only the last remaining marker's ending frees the area again.
    engine = None
    for _ in range(10):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, ALLY)
        engine = reload(tmp_path, mid)
        zone_now = next(z for z in engine.state.zones.values() if z.active and z.owner_id == ALLY)
        if not area_records(zone_now) and zone_now.affected_cells:
            break
    else:
        raise AssertionError('ground fire never returned')
