"""Merge contracts: shared hostile endpoints and authored journey materials."""
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import TabletopMapStore
from tests.auto8f1_table_support import OWNER, FOE, reload_identical
from tests.h1_support import ROOT
from tests.test_mgr_t16_athletics import GLIDE, SHARK, game, move_at, commit


def test_material_swim_keeps_close_quarters_endpoint_and_reload(tmp_path, monkeypatch):
    # A visible hostile stands on an authored soil floor. Native
    # swim routing must retain the same entry option as walk/climb/flight.
    def prepare(bundles):
        for bundle in bundles:
            bundle['actor_template']['speed_ft'] = 150
            bundle.setdefault('skills', {}).update(
                Acrobatics=100 if bundle['actor_id'] == OWNER else -100,
                Athletics=-100,
            )
    service, table, mid = game(
        tmp_path, [SHARK, GLIDE, 'TAL_ATHLETICS_CLOSE_QUARTERS_TRAINING'],
        floor_material='grass', prepare=prepare,
    )
    engine = service._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    destination = engine.state.actors[FOE].position
    for seat in ('MANUAL', 'LOCAL_AUTO', 'API_AUTO'):
        with monkeypatch.context() as patch:
            patch.setitem(engine.typed_control_modes, OWNER, seat)
            assert any(row.destination == destination and row.metadata.get('movement_mode') == 'swim'
                       for row in engine._movement_candidates(actor))
    move = move_at(table, mid, destination.x, mode='swim')
    prompts = commit(table, mid, move, lambda prompt: ['athletics'])
    assert any('Close Quarters Training' in str(prompt) for prompt in prompts)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.actors[OWNER].position == Position(x=15, y=6)
    assert fresh._shared_occupancy_pair(OWNER, FOE)
    reload_identical(service, mid, tmp_path)


def test_map_reload_retains_travel_kind_material_and_seal_together(tmp_path):
    store = TabletopMapStore(tmp_path / 'maps')
    store.save({
        'display_name': 'Merged movement scene', 'width_squares': 20, 'height_squares': 14,
        'terrain': [{'type': 'DIFFICULT', 'travel_kind': 'forest', 'material': 'loose_earth',
                     'sealed': True, 'cells': [[4, 6]]}],
        'materials': [{'material': 'floor:grass', 'cells': [[5, 6]]}],
    })
    arena = TabletopMapStore(tmp_path / 'maps').arenas()['battlefield:map.merged-movement-scene']
    row = next(row for row in arena['terrain_regions'] if row.get('travel_kind') == 'forest')
    assert row['material'] == 'loose earth' and row['sealed'] is True
    assert any(row.get('material') == 'soil' and row.get('material_only')
               for row in arena['terrain_regions'])
