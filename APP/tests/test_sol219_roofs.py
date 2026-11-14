"""Roof map persistence and real production JS modules; no browser."""
import copy
import json
import os
import subprocess
import pytest
from pathlib import Path

from combat.tabletop import TabletopMapStore, normalize_map, table_section, to_battlefield, battlefield_as_map

ROOT = Path(__file__).resolve().parents[1]


def test_roof_modules():
    # Separate interpreters: editor entry points replace global DOM/timer stubs.
    for path in ['tests/sol219_roofs.test.mjs', 'tests/sol219_editor_roofs.test.mjs',
                 'static/tabletop/roofs.browser.test.mjs']:
        result = subprocess.run(['node', '--test', '--test-isolation=none', path],
                                cwd=ROOT, env={**os.environ, 'SOL219_BROWSER':'0'},
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('region', [
    {'x':4, 'y':4, 'enabled':False, 'style':'grey'},
    {'x':4, 'y':4, 'style':'red'},
    {'x':4, 'y':4, 'enabled':True},
])
def test_owner_map_roof_overrides_persist_and_project_on_cold_load(tmp_path, region):
    store = TabletopMapStore(tmp_path, ROOT / 'combat/maps')
    document = store.get('builtin-willow-village-compound')
    settings = {'enabled': True, 'style': 'red', 'regions': [region]}
    saved = store.save({**document, 'map_id': 'roof-copy', 'roofs': settings})
    loaded = TabletopMapStore(tmp_path, ROOT / 'combat/maps').get('roof-copy')
    assert saved == loaded
    assert loaded['roofs'] == settings
    arena = to_battlefield(loaded)
    assert arena['tabletop']['roofs'] == settings
    assert battlefield_as_map(arena)['roofs'] == settings
    bare = copy.deepcopy(loaded)
    del bare['roofs']
    expected = to_battlefield(bare)
    without_roofs = copy.deepcopy(arena)
    del without_roofs['tabletop']['roofs']
    without_roofs.pop('roof_cells')
    expected.pop('roof_cells')
    if region.get('enabled') is False:
        # P20261010-05 makes an authored roof a physical surface. Disabling a
        # building's roof now removes its slab and restores its open-air rules.
        assert len(without_roofs['roof_surfaces']) == len(expected['roof_surfaces']) - 1
        assert all({'x': region['x'], 'y': region['y']} not in row['cells']
                   for row in without_roofs['roof_surfaces'])
    else:
        assert without_roofs == expected, 'style-only roof edits retain identical geometry'


def test_no_roof_fields_added_to_old_maps_or_sealed_arenas():
    for path in (ROOT / 'combat/maps').glob('*.json'):
        original = path.read_bytes()
        document = normalize_map(json.loads(original))
        assert 'roofs' not in document
        assert 'roofs' not in table_section(document)
        assert 'roofs' not in to_battlefield(document)['tabletop']
        assert path.read_bytes() == original


def test_roof_validation_is_bounded_plain_data():
    document = normalize_map({'display_name':'Invalid roofs', 'roofs':{
        'style':'<script>', 'regions':[None, {'x':2.5,'y':3}, {'x':999,'y':3},
                                      {'x':2,'y':3,'enabled':False,'style':'red'}, {'x':2,'y':3}]}})
    assert document['roofs'] == {'enabled':True, 'style':'grey', 'regions':[{'x':2,'y':3,'enabled':False,'style':'red'}]}
    assert normalize_map({'roofs':{'regions':3}})['roofs'] == {'enabled':True,'style':'grey'}
    assert 'roofs' not in normalize_map({'roofs':None})


def test_roof_overrides_survive_real_table_commit_and_cold_reload(tmp_path):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_builtin_arenas import _fight

    combat = CombatService(ROOT, tmp_path)
    document = combat.tabletop_maps.get('builtin-willow-village-compound')
    settings = {'enabled':False, 'style':'grey', 'regions':[{'x':4,'y':4,'style':'red'}, {'x':15,'y':4,'enabled':True}]}
    combat.tabletop_maps.save({**document, 'map_id':'roof-table', 'roofs':settings})
    combat, mid = _fight(tmp_path, 'battlefield:map.roof-table', size=1, rounds=1)
    table = TabletopService(combat, tmp_path)
    initial = table.state(mid)
    assert initial['map']['roofs'] == settings
    assert table.auto_step(mid, initial['last_sequence'])['status'] == 'COMMITTED'
    cold = CombatService(ROOT, tmp_path)
    assert TabletopService(cold, tmp_path).state(mid)['map']['roofs'] == settings
    assert cold._load_session(mid).mechanical.replay()['status'] == 'PASS'
