"""Authored non-wall spans through real maps, table transactions and cold reload."""
from pathlib import Path

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.tabletop_service import TabletopService
from tests.test_save_reload_equivalence import _install_factory

ROOT = Path(__file__).resolve().parents[1]


def test_forty_foot_table_flight_sees_over_well_and_cart_after_cold_reload(tmp_path):
    ids, bundles = _install_factory(tmp_path, 'mapheights', [], None)
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save(normalize_map({
        'map_id': 'height-yard', 'width_squares': 10, 'height_squares': 8,
        'objects': [{'kind': 'village_well', 'x': 3, 'y': 3, 'id': 1},
                    {'kind': 'produce_cart', 'x': 4, 'y': 3, 'id': 2}],
        'starts': {'team1': [[2, 3]], 'team2': [[5, 3]]}}))
    loaded_map = CombatService(ROOT, tmp_path).tabletop_maps.get(saved['map_id'])
    arena = to_battlefield(loaded_map)
    bundles[0]['actor_template'].update(fly_speed_ft=30, hover=True)
    bundles[0].pop('bundle_sha256')
    bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    mid = combat._finish_factory_match(bundles, ids, {ids[0]: 'team:a', ids[1]: 'team:b'},
        {ids[0]: {'x': 2, 'y': 3, 'z': 8}, ids[1]: {'x': 5, 'y': 3, 'z': 8}},
        arena, [ids[0]], [ids[1]], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='MAPHEIGHTS', display_name='Height yard', maximum_rounds=10)['match_id']
    table = TabletopService(combat, tmp_path)
    state = table.state(mid, fog=True)
    assert ids[1] in state['fog_perception'][ids[0]]['creatures']
    for _ in range(4):
        state = table.state(mid)
        if state['menu']['actor_id'] == ids[0]:
            break
        menu = state['menu']
        assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                         state['last_sequence'])['status'] == 'COMMITTED'
    session = combat._load_session(mid)
    move = next(c for c in session.engine.legal_candidates()
                if c.kind == 'MOVE' and c.destination == Position(x=3, y=3, z=8))
    # table.act constructs the CandidateIntent and calls session.execute_intent;
    # this crosses the production transaction/persistence boundary.
    assert table.act(mid, move.candidate_id, move.decision_id, move.state_version,
                     table.state(mid)['last_sequence'])['status'] == 'COMMITTED'
    cold = CombatService(ROOT, tmp_path)
    fresh = TabletopService(cold, tmp_path).state(mid, fog=True)
    session = cold._load_session(mid)
    assert session.engine.state.actors[ids[0]].position == Position(x=3, y=3, z=8)
    assert ids[1] in fresh['fog_perception'][ids[0]]['creatures']
    assert sorted(o.height_ft for o in session.engine.state.objects.values()) == [3, 5]
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
