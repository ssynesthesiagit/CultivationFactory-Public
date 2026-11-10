"""Review seams through table execute_intent, CombatService and cold replay."""
import pytest
from combat.canonical import canonical_sha256
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_source_second_pass import LOCK, PULSE, THREAD, arena, seal_zones, checks, high_attacks

GRAVITY = 'tianxia.talent.gravity.gravity_domain'
SERPENT = 'tianxia.subpath.body.seven_coiled_serpent_spine.feature.'


def reseal(bundle):
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def ordered_attacks(bundles):
    high_attacks(bundles)
    for index, bundle in enumerate(bundles):
        bundle['actor_template']['initiative_bonus'] = 100 - 40 * index
        bundle['actor_template']['maximum_hp'] = 500
        reseal(bundle)


def gravity_setup(bundles):
    ordered_attacks(bundles)
    for action in bundles[1]['action_catalog']:
        typed = action.get('parameters', {}).get('typed') or {}
        if typed.get('source') == GRAVITY:
            typed['numbers']['save_dc'] = 100
    reseal(bundles[1])


def test_pulse_then_actual_gravity_domain_sets_ten_speed_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [PULSE], ally_talents=[GRAVITY],
                                battlefield=arena(), bundle_transform=gravity_setup)
    settle(table, mid, candidate(combat, mid, 'Source Pulse', target=FOE).candidate_id)
    before = reload(tmp_path, mid)
    assert before._effective_speed(before.state.actors[FOE]) == 20
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Gravity Domain').candidate_id)
    turn(table, mid, FOE)
    after = reload(tmp_path, mid)
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE and not e.payload['success'] for e in after.events)
    assert any(c.data.get('speed_penalty_group') for c in after.state.actors[FOE].conditions.values())
    assert after._effective_speed(after.state.actors[FOE]) == 10
    turn(table, mid, ALLY)
    turn(table, mid, FOE)
    refreshed = reload(tmp_path, mid)
    assert refreshed._effective_speed(refreshed.state.actors[FOE]) == 10


def coil_setup(bundles):
    from combat.typed_executor import mark_condition_id
    ordered_attacks(bundles)
    # A recorded ordinary Speed floor can become active after the Pulse lands.
    bundles[2]['typed_passives'].append({'block': 'motion', 'kind': 'speed_floor',
        'while': mark_condition_id('source_r3_floor', ALLY), 'feature_id': 'test:source_r3_floor'})
    source = 'action:test.source_r3.floor'
    bundles[1]['action_catalog'].append({
        'source_definition_id': source, 'display_name': 'Activate recorded Speed floor', 'owner_id': ALLY,
        'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE', 'range_ft': 30,
        'costs': [], 'parameters': {'typed': {'source': source, 'numbers': {}, 'effects': [
            {'type': 'mark', 'mark': 'source_r3_floor', 'applies_to': 'target',
             'duration': {'kind': 'until_removed'}}], 'riders': [], 'duration': {'kind': 'instant'}}}})
    bundles[1]['actor_template']['action_ids'].append(source)
    reseal(bundles[1])
    reseal(bundles[2])


@pytest.mark.parametrize('floor', [False, True])
def test_pulse_then_seventh_coil_doubles_adjusted_walking_speed_after_reload(tmp_path, floor):
    foe = sheet([], cl=15, primary='Stamina')
    foe['identity']['path'] = 'Body Refining'
    foe['path_and_subpath'] = {'path_feature_record_ids': [SERPENT + name for name in
        ('first_and_second_coils', 'third_and_fourth_coils', 'sixth_coil_crowned_serpent',
         'seventh_coil_heaven_swallowing_serpent')]}
    combat, table, mid = fixture(tmp_path, [PULSE], foe_sheet=foe, battlefield=arena(),
                                bundle_transform=coil_setup)
    settle(table, mid, candidate(combat, mid, 'Source Pulse', target=FOE).candidate_id)
    before = reload(tmp_path, mid)
    assert before._effective_speed(before.state.actors[FOE]) == 20
    turn(table, mid, ALLY)
    if floor:
        settle(table, mid, candidate(combat, mid, 'Activate recorded Speed floor', target=FOE).candidate_id)
        active = reload(tmp_path, mid)
        from combat.motion import floors_speed
        assert floors_speed(active, active.state.actors[FOE])
        assert active._effective_speed(active.state.actors[FOE]) == 30
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'], {'choice:needle.serpent_coils': '7'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.serpent_coils' for p in prompts)
    after = reload(tmp_path, mid)
    from combat.ext.serpent_coils import open_coils
    assert open_coils(after.state.actors[FOE]) == 7
    assert after._effective_speed(after.state.actors[FOE]) == (80 if floor else 60)  # (30 - live penalty + 10) * 2
    settle(table, mid, table.state(mid)['menu']['end_turn'], {'choice:needle.coil_upkeep': 'pay'})
    assert table.state(mid)['menu']['actor_id'] == OWNER
    clean = reload(tmp_path, mid)
    assert open_coils(clean.state.actors[FOE]) == 7
    assert clean._effective_speed(clean.state.actors[FOE]) == 80


@pytest.mark.parametrize('dc,passes', [(1, True), (40, False)])
def test_sealed_loose_object_checks_explicit_thread_move_after_reload(tmp_path, dc, passes):
    combat, table, mid = fixture(tmp_path, [LOCK], ally_talents=[THREAD], dc=dc,
        battlefield=arena(door=True, object_overrides={'kind': 'custom', 'interaction': None,
                                                     'blocks': False, 'structure': False}))
    settle(table, mid, candidate(combat, mid, 'Source Lock: object', target='object:map.1').candidate_id)
    before = reload(tmp_path, mid)
    assert seal_zones(before)
    original = before.state.objects['object:map.1'].position
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Thread the Object: move object', target='object:map.1').candidate_id,
                     {'choice:needle.thread_object': 'cell:4,4'})
    after = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.thread_object' for p in prompts)
    assert len(checks(after)) == 1 and checks(after)[0].actor_id == ALLY
    assert checks(after)[0].payload['success'] is passes
    obj = after.state.objects['object:map.1']
    assert (obj.position.x, obj.position.y) == ((4, 4) if passes else (original.x, original.y))
    assert seal_zones(after), 'moving permits this attempt, not dispelling'


def push_setup(bundles):
    bundle = bundles[1]
    source = 'action:test.source_r3.push'
    bundle['action_catalog'].append({
        'source_definition_id': source, 'display_name': 'Recorded push', 'owner_id': ALLY,
        'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY',
        'range_ft': 30, 'costs': [], 'parameters': {'typed': {'source': source, 'numbers': {},
        'effects': [{'type': 'forced_movement', 'distance_ft': 10, 'direction': 'away', 'applies_to': 'target'}],
        'riders': [], 'duration': {'kind': 'instant'}}}})
    bundle['actor_template']['action_ids'].append(source)
    reseal(bundle)


@pytest.mark.parametrize('dc,passes', [(1, True), (40, False)])
def test_forced_passage_checks_mover_and_one_traversal_after_reload(tmp_path, dc, passes):
    combat, table, mid = fixture(tmp_path, [LOCK], dc=dc, battlefield=arena(), bundle_transform=push_setup,
        positions={OWNER: {'x': 5, 'y': 5}, ALLY: {'x': 3, 'y': 6}, FOE: {'x': 5, 'y': 6}})
    settle(table, mid, candidate(combat, mid, 'Source Lock: surface', at=(6, 6)).candidate_id)
    assert seal_zones(reload(tmp_path, mid))
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Recorded push', target=FOE).candidate_id)
    after = reload(tmp_path, mid)
    assert len(checks(after)) == 1 and checks(after)[0].actor_id == FOE
    assert checks(after)[0].payload['success'] is passes
    assert (after.state.actors[FOE].position.x, after.state.actors[FOE].position.y) == ((7, 6) if passes else (5, 6))
    assert seal_zones(after)


def test_destroying_sealed_target_removes_seal_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [LOCK], ally_talents=[PULSE], dc=1,
        battlefield=arena(door=True, object_overrides={'hp': 1}), bundle_transform=high_attacks)
    settle(table, mid, candidate(combat, mid, 'Source Lock: object', target='object:map.1').candidate_id)
    before = reload(tmp_path, mid)
    [zone] = seal_zones(before)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Source Pulse', target='object:map.1').candidate_id)
    after = reload(tmp_path, mid)
    assert len(checks(after)) == 1 and checks(after)[0].payload['success']
    assert after.state.objects['object:map.1'].destroyed
    assert not seal_zones(after)
    assert any(e.event_type == 'ZONE_REMOVED' and e.payload.get('zone_id') == zone.zone_id
               and e.payload.get('reason') == 'SEALED_TARGET_DESTROYED' for e in after.events)
