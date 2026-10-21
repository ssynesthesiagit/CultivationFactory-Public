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
        add_action(bundles[1], 'Guard flight', [{'type': 'general_flight', 'speed_ft': 30, 'hover': True,
            'duration': {'kind': 'minutes', 'amount': 1}}], target='SELF')
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
