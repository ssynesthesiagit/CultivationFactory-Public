"""All blocker families through integrated sight, effect, cover and clearance."""
import json
from pathlib import Path
import subprocess

import pytest

from combat import effect_cover, targeting
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate5_service import CombatService
from combat.map_heights import DEFAULTS, scenery_height_ft
from combat.tabletop import DECOR_RULE_LOOKS, TREE_LOOKS, TabletopError, normalize_map, rasterize, to_battlefield
from combat.tabletop_service import TabletopService
from tests.test_save_reload_equivalence import _install_factory

ROOT = Path(__file__).resolve().parents[1]

CASES = {
    'well': ('objects', {'kind': 'village_well', 'x': 3, 'y': 3}, 3, 0, True, True, False),
    'cart': ('objects', {'kind': 'produce_cart', 'x': 3, 'y': 3}, 5, 0, True, True, False),
    'door': ('objects', {'kind': 'door', 'x': 3, 'y': 3, 'interaction': 'simple_door',
                         'door_open': 0, 'door_locked': 0, 'door_jammed': 0}, 10, 0, True, True, False),
    'open-door': ('objects', {'kind': 'door', 'x': 3, 'y': 3, 'interaction': 'simple_door',
                         'door_open': 1, 'door_locked': 0, 'door_jammed': 0}, 10, 0, False, False, False),
    'gate': ('objects', {'kind': 'gate', 'x': 3, 'y': 3}, 10, 0, True, True, False),
    'solid-window': ('objects', {'kind': 'window', 'x': 3, 'y': 3, 'blocks': True}, 10, 0, True, True, False),
    'window': ('objects', {'kind': 'window', 'x': 3, 'y': 3}, 10, 0, False, False, False),
    'open-window': ('objects', {'kind': 'window', 'x': 3, 'y': 3, 'blocks': False}, 10, 0, False, False, False),
    'raised-crate': ('objects', {'kind': 'crate', 'x': 3, 'y': 3, 'z': 2,
                               'height_ft': 11, 'blocks': True}, 11, 10, True, True, False),
    'overlap-raised-object': ('objects', {'kind': 'crate', 'x': 3, 'y': 3, 'z': 2,
                               'height_ft': 11, 'blocks': True}, 11, 10, True, True, False),
    'zero-object': ('objects', {'kind': 'village_well', 'x': 3, 'y': 3, 'height_ft': 0}, 0, 0, True, True, False),
    'tree': ('trees', {'x': 3, 'y': 3, 'size': 1, 'look': 'broadleaf'}, 30, 0, True, True, False),
    'great-tree': ('trees', {'x': 3, 'y': 3, 'size': 2, 'height_ft': 15}, 15, 0, True, True, False),
    'raised-tree': ('trees', {'x': 3, 'y': 3, 'size': 1, 'height_ft': 11,
                            'base_altitude_ft': 10}, 11, 10, True, True, False),
    'zero-tree': ('trees', {'x': 3, 'y': 3, 'size': 1, 'height_ft': 0}, 0, 0, True, True, False),
    'cover': ('terrain', {'type': 'SIMPLE_COVER', 'look': 'water_well', 'cells': [[3, 3]]},
              3, 0, False, False, True),
    'raised-cover': ('terrain', {'type': 'SIMPLE_COVER', 'look': 'handcart', 'height_ft': 11,
                                'base_altitude_ft': 10, 'cells': [[3, 3]]}, 11, 10, False, False, True),
    'bamboo': ('materials', {'material': 'terrain:bamboo thicket',
                            'cells': [[3, 3], [4, 3], [3, 4], [4, 4]]}, 20, 0, False, True, False),
    'raised-bamboo': ('materials', {'material': 'terrain:bamboo thicket', 'height_ft': 11,
        'base_altitude_ft': 10, 'cells': [[3, 3], [4, 3], [3, 4], [4, 4]]}, 11, 10, False, True, False),
}


def yard(tmp_path, key, altitude):
    family, row, *_ = CASES[key]
    ids, bundles = _install_factory(tmp_path, 'height-family', [], None)
    combat = CombatService(ROOT, tmp_path)
    extra = {'walls': [{'shape': 'rect', 'points': [[3, 3], [4, 4]], 'height_ft': 3}],
             'trees': [{'x': 3, 'y': 3, 'height_ft': 3}]} if key == 'overlap-raised-object' else {}
    saved = combat.tabletop_maps.save({'map_id': 'height-family', 'width_squares': 10, 'height_squares': 8,
        family: [row], **extra, 'starts': {'team1': [[2, 3]], 'team2': [[5, 3]]}})
    reloaded = CombatService(ROOT, tmp_path).tabletop_maps.get(saved['map_id'])
    assert saved == reloaded
    for bundle in bundles:
        bundle['actor_template'].update(fly_speed_ft=30, hover=True)
        bundle.pop('bundle_sha256')
        bundle['bundle_sha256'] = canonical_sha256(bundle)
    mid = combat._finish_factory_match(bundles, ids, {ids[0]: 'team:a', ids[1]: 'team:b'},
        {ids[0]: {'x': 2, 'y': 3, 'z': altitude // 5}, ids[1]: {'x': 5, 'y': 3, 'z': altitude // 5}},
        to_battlefield(reloaded), [ids[0]], [ids[1]], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='HEIGHT-FAMILY', display_name='Scenery height yard', maximum_rounds=10)['match_id']
    return combat, TabletopService(combat, tmp_path), mid, ids


@pytest.mark.parametrize('key', CASES)
@pytest.mark.parametrize('sample', ['below', 'within', 'above'])
def test_family_consumers_and_cold_table_reload(tmp_path, key, sample):
    family, row, height, bottom, solid, opaque, cover = CASES[key]
    altitude = {'below': 0, 'within': bottom + (height // 2 // 5) * 5, 'above': 40}[sample]
    intersects = bottom <= altitude < bottom + height
    if key == 'overlap-raised-object':
        intersects = intersects or altitude < 3
    # Fog cells describe the floor at z=0, not the creature standing/flying
    # above that square. A descending sight line can still hit the scenery.
    ground_visible = not (opaque and intersects)
    # raised-tree: the 40 ft viewer's descending ray to floor square (5,3) is at 20 ft at the
    # arm's far tip (x=4), inside the 10-21 ft canopy, so the floor is hidden (fog-altitude
    # whole-arm intersection; the old midpoint check missed it). The creature at 40 ft stays visible.
    if sample == 'above' and key in {'raised-crate', 'overlap-raised-object',
                                    'tree', 'great-tree', 'bamboo', 'raised-bamboo', 'raised-tree'}:
        ground_visible = False
    combat, table, mid, (viewer_id, target_id) = yard(tmp_path, key, altitude)

    def check(service, ui):
        session = service._load_session(mid)
        engine = session.engine
        viewer, target = (engine.state.actors[aid] for aid in (viewer_id, target_id))
        state = ui.state(mid, fog=True)
        assert (target_id in state['fog_perception'][viewer_id]['creatures']) == (not (opaque and intersects))
        assert ([5, 3] in state['fog_perception'][viewer_id]['cells']) == ground_visible
        assert engine.grid.line_of_sight(viewer.position, Position(x=5, y=3)) == ground_visible
        assert engine.grid.line_of_sight(viewer.position, target.position) == (not (opaque and intersects))
        assert engine.grid.volume_legal(Position(x=3, y=3, z=altitude // 5)) == (not (solid and intersects))
        assert targeting.line_of_effect(engine, viewer, target=target) == (not (solid and intersects))
        result = effect_cover.query(engine, (viewer.position,), viewer_id, target,
                                    purpose='effect', target_cells=(target.position,))
        assert result == {'blocked': solid and intersects, 'bonus': 2 if cover and intersects else 0}
        arena = engine.battlefield_document
        represented = arena['map_objects'] if family == 'objects' else arena['tabletop'][family]
        assert represented[0]['height_ft'] == height
        if family == 'objects':
            obj = next(iter(engine.state.objects.values()))
            assert obj.height_ft == height and obj.position.z * 5 == bottom
        if key == 'overlap-raised-object':
            assert sorted(engine.grid.terrain_spans['BLOCKED'][3, 3]) == [(0, 3), (0, 3), (10, 21)]
            assert engine.grid.volume_legal(Position(x=3, y=3, z=1)), 'the 5-to-10 ft gap remains clear'
            assert engine.grid.line_of_sight(Position(x=2, y=3, z=1), Position(x=5, y=3, z=1))
        return session

    check(combat, table)
    state = table.state(mid)
    menu = state['menu']
    assert table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                     state['last_sequence'])['status'] == 'COMMITTED'
    # Exercise the explicitly requested session transaction API as well.
    session = combat._load_session(mid)
    end = next(c for c in session.engine.legal_candidates() if c.kind == 'END_TURN')
    session.mechanical.execute_intent(ActionIntent(intent_id='height-family-end', candidate_id=end.candidate_id,
        decision_id=end.decision_id, state_version=end.state_version, actor_id=end.actor_id))
    cold = CombatService(ROOT, tmp_path)
    session = check(cold, TabletopService(cold, tmp_path))
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_catalog_is_complete_and_python_js_defaults_agree():
    from combat.object_rules import presets
    assert set(presets()) <= DEFAULTS['object_ft'].keys()
    assert set(TREE_LOOKS) == DEFAULTS['tree_ft'].keys()
    assert set(DECOR_RULE_LOOKS) <= DEFAULTS['terrain_ft'].keys()
    rows = [(row, family) for family, catalog, name in [
        ('object', presets(), 'kind'), ('tree', TREE_LOOKS, 'look'),
        ('terrain', DEFAULTS['terrain_ft'], 'look')]
        for key in catalog for row in [{name: key, 'type': 'SIMPLE_COVER'}]]
    rows += [({}, 'object'), ({'kind': 'future-furniture'}, 'object'), ({'size': 2}, 'tree'),
             ({'height_ft': 0}, 'object'), ({'type': 'DIFFICULT'}, 'terrain'),
             ({'material': 'terrain:bamboo thicket'}, 'material'), ({'material': 'floor:stone'}, 'material')]
    script = """
import {sceneryHeightFt} from './static/tabletop/map-heights.js';
import {readFileSync} from 'node:fs';
console.log(JSON.stringify(JSON.parse(readFileSync(0,'utf8')).map(([r,f])=>sceneryHeightFt(r,f))));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                            input=json.dumps(rows), text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [scenery_height_ft(row, family) for row, family in rows]


@pytest.mark.parametrize('bad', [True, -1, 1.5, '3', None])
@pytest.mark.parametrize('family', ['objects', 'trees', 'terrain', 'materials'])
@pytest.mark.parametrize('field', ['height_ft', 'base_altitude_ft'])
def test_invalid_heights_are_rejected_consistently(bad, family, field):
    row = {'objects': {'kind': 'crate', 'x': 2, 'y': 2}, 'trees': {'x': 2, 'y': 2},
           'terrain': {'type': 'SIMPLE_COVER', 'cells': [[2, 2]]},
           'materials': {'material': 'terrain:bamboo thicket', 'cells': [[2, 2]]}}[family]
    with pytest.raises(TabletopError, match='whole numbers'):
        normalize_map({family: [{**row, field: bad}]})


def test_overlapping_sources_and_bamboo_override_groups_survive():
    from combat.gate2_grid import SquareGrid
    document = normalize_map({'walls': [{'shape': 'rect', 'points': [[3, 3], [4, 4]], 'height_ft': 3}],
        'trees': [{'x': 3, 'y': 3, 'size': 2, 'height_ft': 11, 'base_altitude_ft': 10}],
        'terrain': [{'type': 'SIMPLE_COVER', 'cells': [[3, 3]], 'height_ft': 5}],
        'materials': [{'material': 'terrain:bamboo thicket', 'cells': [[8, 3], [9, 3]], 'height_ft': 0},
                      {'material': 'terrain:bamboo thicket', 'cells': [[8, 4], [9, 4]], 'height_ft': 25}]})
    assert normalize_map(document) == document
    grid = SquareGrid(to_battlefield(document))
    assert grid.terrain_spans['BLOCKED'][3, 3] == [(0, 3), (10, 21)]
    for z, blocked in [(0, True), (1, False), (2, True), (4, True), (5, False), (8, False)]:
        assert grid.terrain_at((3, 3, z), 'BLOCKED') == blocked
    assert grid.terrain_spans['SIGHT_BLOCKED'][8, 3] == [(0, 0)]
    assert grid.terrain_spans['SIGHT_BLOCKED'][8, 4] == [(0, 25)]
    assert (3, 3) in rasterize(document)[0] and (4, 3) not in rasterize(document)[0]
    assert grid.volume_legal(Position(x=3, y=3, z=8))
    assert grid.volume_legal(Position(x=5, y=3)), 'the decorative canopy adds no solid cells'


def test_ground_paint_stays_a_surface_and_zero_tree_is_nonblocking():
    document = normalize_map({'trees': [{'x': 3, 'y': 3, 'height_ft': 0}],
        'materials': [{'material': 'floor:wood', 'cells': [[3, 3]]}],
        'terrain': [{'type': 'DIFFICULT', 'cells': [[3, 3]]}]})
    assert document['terrain'][0]['height_ft'] == 0
    assert 'height_ft' not in document['materials'][0]
    assert not rasterize(document)[0]


def test_production_scenery_node_checks():
    result = subprocess.run(['node', '--test', '--test-isolation=none', 'tests/map_height_scenery.test.mjs'],
                            cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('look', [[], {}, True, 5, None, 'not-a-look'])
def test_height_defaults_use_only_normalized_looks(look):
    document = normalize_map({'trees': [{'x': 3, 'y': 3, 'look': look}],
        'terrain': [{'type': 'SIMPLE_COVER', 'look': look, 'cells': [[3, 3]]}]})
    assert document['trees'][0]['height_ft'] == 30
    assert document['terrain'][0]['height_ft'] == 3
