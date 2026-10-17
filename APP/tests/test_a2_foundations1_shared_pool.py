"""r13: unrelated movement stays identical to main, through service/table/replay.

The lead explicitly replaced r12's new 0/20 reconciliation expectations with
main's existing shared-pool contract (10/30). No new ordinary counter survives.
"""
import pytest
import json
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests import test_riders_c13 as C
from tests.worker2_support import OWNER, fixture, settle, candidate, reload, turn


def setup(tmp_path):
    owner = compile_character(C._sheet(C.DRUNKEN, items=C.AXE_ITEMS), actor_id=OWNER)
    for name, effects in [
        ('Reduce Speed', [{'type': 'speed', 'flat': -10, 'applies_to': 'self', 'duration': 'until_end_of_turn'}]),
        ('Hold self', [{'type': 'condition', 'condition': 'grappled', 'applies_to': 'self', 'duration': 'until_removed'}]),
        ('Free self', [{'type': 'remove_condition', 'condition': 'grappled', 'applies_to': 'self'}]),
    ]:
        source = 'action:test.shared_pool.' + name.lower().replace(' ', '_')
        owner['action_catalog'].append({'source_definition_id': source, 'display_name': name,
            'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
            'parameters': {'free_primary': True, 'typed': {'source': source, 'numbers': {}, 'effects': effects,
                                     'riders': [], 'duration': {'kind': 'instant'}}}})
        owner['actor_template']['action_ids'].append(source)
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)
    return fixture(tmp_path, [], owner_bundle=owner, seed='A2GFOU1-SHARED',
                   ally_position={'x': 4, 'y': 7}, foe_position={'x': 8, 'y': 6})


def check(tmp_path, combat, mid, expected, *, final=False):
    live = combat._load_session(mid).engine
    cold = reload(tmp_path, mid)
    for engine in [live, cold]:
        actor = engine.state.actors[OWNER]
        assert actor.movement_remaining_ft == expected
        if final:
            assert 'ordinary_movement_remaining_ft' not in actor.turn_flags
            assert 'ordinary_movement_shortfall_ft' not in actor.turn_flags
            assert not any(e.event_type in {'MOVEMENT_ALLOWANCE_ADJUSTED', 'MOVEMENT_ALLOWANCE_BASIS_ADJUSTED'}
                           for e in engine.events)
    assert live.state.model_dump(mode='json') == cold.state.model_dump(mode='json')
    receipt = tmp_path / 'movement-snapshots.json'
    snapshots = json.loads(receipt.read_text()) if receipt.exists() else []
    snapshots.append({'state': cold.state.model_dump(mode='json'),
                      'events': [e.model_dump(mode='json') for e in cold.events]})
    receipt.write_text(json.dumps(snapshots, sort_keys=True))


def test_separate_grant_then_walk_then_speed_change_matches_main(tmp_path):
    combat, table, mid = setup(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Reeling Step').candidate_id,
           choices={'choice:needle.drunken_reeling_move': 'cell:3,4'})
    engine = reload(tmp_path, mid)
    granted = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER]
    assert granted and len(granted[-1].payload['path']) == 3
    check(tmp_path, combat, mid, 30)
    c = next(c for c in combat._load_session(mid).engine.legal_candidates()
             if c.kind.value == 'MOVE' and c.movement_cost_ft == 20)
    settle(table, mid, c.candidate_id)
    check(tmp_path, combat, mid, 10)
    settle(table, mid, candidate(combat, mid, 'Reduce Speed').candidate_id)
    assert reload(tmp_path, mid)._effective_speed(reload(tmp_path, mid).state.actors[OWNER]) == 20
    check(tmp_path, combat, mid, 10, final=True)


def test_restored_initial_movement_then_speed_change_matches_main(tmp_path):
    combat, table, mid = setup(tmp_path)
    settle(table, mid, candidate(combat, mid, 'Hold self').candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    check(tmp_path, combat, mid, 0)
    assert reload(tmp_path, mid).state.actors[OWNER].turn_flags['movement_withheld_ft'] == 30
    settle(table, mid, candidate(combat, mid, 'Free self').candidate_id)
    check(tmp_path, combat, mid, 30)
    assert 'movement_withheld_ft' not in reload(tmp_path, mid).state.actors[OWNER].turn_flags
    settle(table, mid, candidate(combat, mid, 'Reduce Speed').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[OWNER]) == 20
    check(tmp_path, combat, mid, 30, final=True)
