"""Native scene and map boundaries from the F5 independent review."""
from copy import deepcopy

import pytest

from combat import carry
from combat.ext import formations, placed
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE, candidate, settle, turn
from tests.test_mgr_t14_pattern_rituals import game


def finish(service, table, mid, jid):
    for _ in range(12):
        if service._load_session(mid).engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    cold = CombatService(ROOT, service.userdata_root)
    session = cold._load_session(mid)
    assert session.engine.state.terminal_result is not None
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return cold.journey_resume(jid, cold.journey_state(jid)['revision'])


def test_prepared_components_enter_native_scene_and_cold_replay(tmp_path):
    cold, jid, act = game(tmp_path)
    state = act('prepare_array', {'pattern': 'locking_gate', 'center': {'x': 4, 'y': 6},
                                  'site': '', 'damage_type': 'force'})
    service = cold()
    result = service.journey_start_scene(jid, state['revision'], {OWNER: 'party', FOE: 'party'})
    mid = result['match_id']
    engine = cold()._load_session(mid).engine
    array, = formations.arrays(engine, OWNER)
    objects = formations.objects_of(engine, array)
    assert len(objects) == 4
    assert {o.component['role'] for o in objects} == {'eye', 'node'}
    assert all(o.flammable is False for o in objects)
    assert sorted(o.maximum_hp for o in objects) == [15, 15, 15, 25]
    finish(service, TabletopService(service, tmp_path), mid, jid)


def test_journey_trap_has_a_physical_device_in_gate2_genesis(tmp_path):
    cold, jid, act = game(tmp_path)
    state = act('construct_trap', {'form': 'tripwire', 'cells': [{'x': 4, 'y': 6}], 'aim': 'e'})
    result = cold().journey_start_scene(jid, state['revision'], {OWNER: 'party', FOE: 'party'})
    session = cold()._load_session(result['match_id'])
    trap, = placed.of(session.engine, 'trap')
    device = session.engine.state.objects['object:trap:' + trap.zone_id]
    assert device.component['trap_zone'] == trap.zone_id
    assert device.current_hp == device.maximum_hp == 10
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('item,area', [('ball_bearings', 4), ('caltrops', 1)])
def test_activated_scatter_survives_scene_resume_and_reopen(tmp_path, item, area):
    item_id = 'tianxia.mortal.gear.' + item
    doc = sheet(['TRAP_BASE_ACTIVATION_TRAP'], cl=5, kit={'starting_kit': {'items': [
        {'item_id': item_id, 'name': item.replace('_', ' '), 'quantity': 1},
        {'item_id': 'tianxia.mortal.tool.thieves_tools', 'name': 'Thieves tools', 'quantity': 1}]}})
    bundles = [compile_character(doc, actor_id=OWNER), compile_character(sheet([], cl=5), actor_id=FOE)]
    service = CombatService(ROOT, tmp_path)
    arena = {'display_name': 'Scatter scene', 'stable_id': 'scatter:map-a', 'width_squares': 15,
             'height_squares': 12, 'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []}
    positions = {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 5}}
    state = service.journeys.create(bundles, arena, positions, {OWNER: 30, FOE: 30})
    jid = state['journey_id']
    result = service.journey_start_combat(jid, state['revision'], {OWNER: 'a', FOE: 'b'}, maximum_rounds=2)
    mid = result['match_id']
    table = TabletopService(service, tmp_path)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(service, mid, 'Trap form: Activation Trap').candidate_id)
    settle(table, mid, candidate(service, mid, 'Set Trap', at=(4, 6)).candidate_id)
    turn(table, mid, FOE)
    engine = service._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                and c.destination and (c.destination.x, c.destination.y) == (4, 6))
    settle(table, mid, move.candidate_id)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    hazard, = placed.of(engine, 'ordinary_scatter')
    assert len(hazard.affected_cells) == area
    original = hazard.model_dump(mode='json')
    state = finish(service, table, mid, jid)
    cold = CombatService(ROOT, tmp_path)
    # A resumed journey remains bound to its immutable encounter. Its native
    # mechanical replay is checked by finish(); command-only journey replay
    # deliberately refuses encounter continuations.
    assert cold.journey_state(jid)['phase'] == 'travel'
    assert 'ordinary_scatter_areas' not in cold.journey_state(jid, viewer_id=FOE)['actors'][OWNER]
    assert cold.journey_state(jid, viewer_id=OWNER)['actors'][OWNER]['ordinary_scatter_areas']
    result = cold.journey_start_scene(jid, state['revision'], {OWNER: 'party', FOE: 'party'})
    mid = result['match_id']
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    restored, = placed.of(engine, 'ordinary_scatter')
    assert restored.zone_id == original['zone_id']
    assert restored.affected_cells == hazard.affected_cells
    assert restored.trigger_profile == hazard.trigger_profile
    assert restored.duration_rounds is None
    carried = next(i for i in carry.carrying_of(engine, OWNER)['items'] if i['item_id'] == item_id)
    assert carry.remaining_quantity(engine, engine.state.actors[OWNER], carried) == 0
    assert not placed.of(engine, 'ordinary_scatter', owner_id=FOE)
    state = finish(cold, TabletopService(cold, tmp_path), mid, jid)
    state = cold.journey_act(jid, state['revision'], OWNER, 'finish', {})
    next_map = {**arena, 'stable_id': 'scatter:map-b'}
    state = cold.journeys.create(bundles, next_map, positions, {OWNER: 30, FOE: 30})
    jid2 = state['journey_id']
    assert not cold.journey_state(jid2, viewer_id=OWNER)['actors'][OWNER]['ordinary_scatter_areas']
    result = cold.journey_start_scene(jid2, state['revision'], {OWNER: 'party', FOE: 'party'})
    assert not placed.of(CombatService(ROOT, tmp_path)._load_session(result['match_id']).engine, 'ordinary_scatter')
    state = finish(cold, TabletopService(cold, tmp_path), result['match_id'], jid2)
    state = cold.journey_act(jid2, state['revision'], OWNER, 'finish', {})
    state = cold.journeys.create(bundles, arena, positions, {OWNER: 30, FOE: 30})
    result = cold.journey_start_scene(state['journey_id'], state['revision'], {OWNER: 'party', FOE: 'party'})
    session = CombatService(ROOT, tmp_path)._load_session(result['match_id'])
    assert len(placed.of(session.engine, 'ordinary_scatter')) == 1
    assert session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
def test_surveyed_site_cannot_supply_another_maps_footprint(tmp_path, mode):
    cold, jid, act = game(tmp_path)
    service = cold()
    site = {'id': 'bridge-a', 'name': 'Old bridge', 'kind': 'bridge',
            'cells': [{'x': x, 'y': 6} for x in range(3, 20)], 'known_to': [OWNER]}
    state = service.journey_admit(jid, 0, OWNER, 'construction_site', site, gm=True, reason='Actual surveyed bridge')
    state = act('finish', {})
    bundles = [state['actors'][a]['bundle'] for a in (OWNER, FOE)]
    positions = {a: state['actors'][a]['position'] for a in (OWNER, FOE)}
    other_map = {**state['battlefield'], 'stable_id': 'other-map', 'width_squares': 12}
    state = service.journeys.create(bundles, other_map, positions, {OWNER: 30, FOE: 30}, {OWNER: mode, FOE: 'MANUAL'})
    jid2 = state['journey_id']
    before = deepcopy(service.journey_state(jid2))
    with pytest.raises(ValueError, match='bounded physical site'):
        service.journey_act(jid2, state['revision'], OWNER, 'prepare_array', {
            'pattern': 'locking_gate', 'center': {'x': 3, 'y': 6}, 'site': 'bridge-a', 'damage_type': 'force'})
    assert service.journey_state(jid2) == before
    for field, value in [('family', 'array'), ('pattern', 'locking_gate'), ('layers', ['locking_gate']),
                         ('damage_type', 'force'), ('center', {'x': 3, 'y': 6})]:
        state = service.journey_act(jid2, service.journey_state(jid2)['revision'], OWNER,
                                    'construction_choice', {'field': field, 'value': value})
    options = service.journeys.load(jid2).menu(OWNER)['options']
    assert not any(r.get('payload') == {'field': 'site', 'value': 'bridge-a'} for r in options)
    assert any(r.get('payload') == {'field': 'site', 'value': ''} for r in options)
    assert cold().journeys.replay(jid2)['status'] == 'PASS'


def test_formation_source_fixture_uses_pytest_storage_and_named_map(tmp_path):
    from tests.test_formations import _approved_bundle, _sheet, ME
    bundle = _approved_bundle(_sheet([]), ME, storage=tmp_path)
    assert bundle['actor_id'] == ME
    assert bundle['construction_contract']['damage_types']
    assert not list(tmp_path.iterdir()), 'Temporary permission service must clean its pytest-owned directory'
