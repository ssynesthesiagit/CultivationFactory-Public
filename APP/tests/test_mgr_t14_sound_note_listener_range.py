"""Note's targeting range must not limit its committed sound-hiding rider."""
import pytest

from combat.canonical import canonical_sha256
from combat import speech, typed_executor
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.test_mgr_t14_sound_note import NOTE, BLOCK, scene_setup


@pytest.mark.parametrize('inaudible', [None, 'deafened', 'wall'], ids=['audible', 'deafened', 'wall'])
def test_note_blocks_distant_audible_listener_only_after_table_reload(tmp_path, inaudible):
    metadata = {'purpose': 'conceal_sound', 'senses': ['hearing'], 'ordinary': 1,
                'source_actor_id': FOE, 'observer_id': ALLY}

    def setup(bundles):
        scene_setup(metadata)(bundles)
        for bundle in bundles:
            # Keep the listener's condition and the target's check before Note expires.
            bundle['actor_template']['initiative_bonus'] = {OWNER: 20, ALLY: 0, FOE: -20}[bundle['actor_id']]
            if bundle['actor_id'] == ALLY:
                action_id = 'action:test.distant_listener.deafened'
                bundle['action_catalog'].append({
                    'source_definition_id': action_id, 'display_name': 'Scene: become deafened',
                    'owner_id': ALLY, 'economy': 'ACTION', 'resolution_kind': 'TYPED',
                    'target_kind': 'SELF', 'costs': [], 'parameters': {'typed': {'effects': [
                        {'type': 'condition', 'condition': 'deafened', 'applies_to': 'self',
                         'duration': {'kind': 'rounds', 'amount': 5}}]}}})
                bundle['actor_template']['action_ids'].append(action_id)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    def arena(battlefield):
        battlefield['terrain_regions'] = []
        if inaudible == 'wall':
            battlefield['terrain_regions'].append({
                'region_id': 'test.sound_wall', 'terrain_type': 'BLOCKED',
                'movement_cost': 0, 'description': 'Solid stone blocks sound.',
                'cells': [{'x': 10, 'y': 6}]})

    foe = sheet([])
    foe['ability_scores_and_statistics']['armor_class']['base_value'] = 0
    combat, table, mid = fixture(tmp_path, [NOTE], foe_sheet=foe, named=True, ask=False,
        positions={OWNER: {'x': 4, 'y': 6}, FOE: {'x': 3, 'y': 6}, ALLY: {'x': 16, 'y': 6}},
        bundle_transform=setup, battlefield_transform=arena, seed='T14-Note')
    settle(table, mid, candidate(combat, mid, 'Scene: pre-existing Resonance', target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Resonant Note: Prevent ordinary sound-based hiding', target=FOE).candidate_id)
    turn(table, mid, ALLY)
    if inaudible == 'deafened':
        settle(table, mid, candidate(combat, mid, 'Scene: become deafened').candidate_id)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    source, observer = engine.state.actors[FOE], engine.state.actors[ALLY]
    assert engine._distance_actor_to_actor(source, observer) == 65
    assert any(c.condition_id == BLOCK for c in source.conditions.values())
    assert typed_executor.cant_hear(observer) == (inaudible == 'deafened')
    assert speech.can_hear_from(engine, source, observer, NOTE) == (inaudible != 'deafened')
    assert engine.grid.line_of_sight_between_cell_sets(
        engine._actor_volume(source), engine._actor_volume(observer)) == (inaudible != 'wall')

    settle(table, mid, candidate(combat, mid, 'Scene check').candidate_id)
    check = next(event for event in reversed(reload(tmp_path, mid).events)
                 if event.event_type == 'CHECK_ROLLED' and 'sound_scene' in event.source_definition_id)
    assert check.payload['actor']['total'] >= 0
    assert check.payload['check_metadata'] == metadata
    assert check.payload['success'] == (inaudible is not None)
