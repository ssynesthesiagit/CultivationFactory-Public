"""Waiting Large mounts are off-map bookkeeping, even beside a wall."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_mounts import rider_bundle, ME


@pytest.mark.parametrize('ai', [False, True])
def test_waiting_mount_at_6_3_commits_and_reloads(tmp_path, ai):
    svc = CombatService(ROOT, tmp_path)
    ids = [ME, *[f'actor:factory.screen{i}' for i in range(5)]]
    bundles = [rider_bundle(), *[compile_character(sheet([]), actor_id=aid) for aid in ids[1:]]]
    svc.tabletop_maps.save({'display_name': 'Screen regression', 'width_squares': 10, 'height_squares': 8,
        'walls': [{'shape': 'rect', 'points': [[7, 2], [8, 4]], 'filled': True}],
        'starts': {'team1': [[3, 3], [3, 4], [3, 5]], 'team2': [[6, 3], [6, 4], [6, 5]]}})
    arena = svc.factory_arenas()['battlefield:map.screen-regression']
    positions = dict(zip(ids, [{'x':6,'y':3}, {'x':6,'y':2}, {'x':6,'y':4},
                               {'x':3,'y':3}, {'x':3,'y':4}, {'x':3,'y':5}]))
    mid = svc._finish_factory_match(bundles, ids, {aid:'a' if i<3 else 'b' for i,aid in enumerate(ids)},
        positions, arena, ids[:3], ids[3:], control_modes={aid:'LOCAL_AUTO' if ai else 'MANUAL' for aid in ids},
        match_seed='HUNT23-5', display_name='Screen regression', maximum_rounds=3)['match_id']
    engine = svc._load_session(mid).engine
    horse = next(a for a in engine.state.actors.values() if a.summon)
    assert not horse.active and horse.summon['status'] == 'waiting'
    assert (horse.position.x, horse.position.y) == (6,3)
    assert (7,3) in engine._actor_cells(horse)
    table = TabletopService(svc, tmp_path)
    state = table.state(mid); menu = state['menu']
    result = table.auto_step(mid, state['last_sequence']) if ai else table.act(
        mid, menu['end_turn'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not loaded.engine.state.actors[horse.entity_id].active
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
