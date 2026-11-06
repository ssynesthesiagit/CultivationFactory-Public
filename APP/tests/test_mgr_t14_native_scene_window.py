"""Bounded scenes share native turns without requiring an opposing creature.

Use ordinary acquired-free sheets: the scene contract also serves practice and
allied preparation with no Goruden features. All assertions cold-load/replay the
committed native match rather than mutating engine state.
"""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.cw2_service_support import add_action
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t14_goruden import ready
from tests.worker2_support import candidate, reload, settle


def native_scene(tmp_path, count, *, scene=True, teams=None):
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({
        'display_name': 'Bounded practice', 'width_squares': 12,
        'height_squares': 12, 'terrain': []})
    arena = next(a for a in combat.factory_arenas().values()
                 if a['display_name'] == 'Bounded practice')
    bundles = []
    for i in range(count):
        bundle = compile_character(sheet([], cl=3), actor_id=f'actor:factory.practice{i}',
                                   reaction_plan={'ask': True})
        add_action(bundle, 'Practice contact', [
            {'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}])
        bundles.append(bundle)
    ids = [b['actor_id'] for b in bundles]
    result = combat._finish_factory_match(
        bundles, ids, teams or {a: 'team:practice' for a in ids},
        {a: {'x': 3+i, 'y': 3} for i, a in enumerate(ids)}, arena, ids, [],
        control_modes={a: 'MANUAL' for a in ids}, match_seed='NATIVE-SCENE-REGRESSION',
        display_name='Bounded practice', maximum_rounds=1, scene_window=scene)
    mid = result['match_id']
    table = TabletopService(combat, tmp_path)
    ready(table, tmp_path, mid)
    return combat, table, mid


@pytest.mark.parametrize('count', [1, 2])
def test_scene_keeps_solo_and_allied_turns_until_native_round_limit(tmp_path, count):
    combat, table, mid = native_scene(tmp_path, count)
    engine = reload(tmp_path, mid)
    assert engine.state.rules['scene_window'] == 'elapsed_rounds_v1'
    assert engine.state.terminal_result is None
    actor = engine.state.current_actor_id
    hp = engine.state.actors[actor].current_hp
    settle(table, mid, candidate(combat, mid, 'Practice contact', target=actor).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[actor].current_hp == hp-1
    assert engine.state.terminal_result is None  # Damage must not end an allied scene.
    for _ in range(count):
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    assert engine.state.terminal_result.kind == 'DRAW_DURATION'
    assert engine.state.round_number == 2
    assert len([e for e in engine.events if e.event_type == 'TURN_ENDED']) == count


def test_ordinary_combat_still_rejects_a_solo_roster(tmp_path):
    with pytest.raises(ValueError, match='C3C_DYNAMIC_ROSTER_INVALID'):
        native_scene(tmp_path, 1, scene=False)


def test_ordinary_allied_combat_still_ends_by_victory(tmp_path):
    combat, table, mid = native_scene(tmp_path, 2, scene=False)
    engine = reload(tmp_path, mid)
    assert 'scene_window' not in engine.state.rules
    actor = engine.state.current_actor_id
    settle(table, mid, candidate(combat, mid, 'Practice contact', target=actor).candidate_id)
    assert reload(tmp_path, mid).state.terminal_result.kind == 'VICTORY'
