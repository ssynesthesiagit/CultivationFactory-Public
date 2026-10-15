"""Exercise the actual map normalize/store path offline, with task-owned temporary data."""
import json
import os
import subprocess
import sys
import types
from collections import deque
from pathlib import Path

from combat import tabletop

APP = Path(__file__).resolve().parents[1]


def _source(path):
    if os.environ.get('MAPART2_BASELINE') == '1':
        ref = os.environ.get('MAPART2_BASELINE_REF', 'HEAD')
        return subprocess.check_output(['git', 'show', f'{ref}:APP/{path}'], cwd=APP, text=True)
    return (APP / path).read_text()


def _api():
    if os.environ.get('MAPART2_BASELINE') != '1':
        return tabletop
    module = types.ModuleType('combat.mapart2_baseline')
    module.__file__ = str(APP / 'combat/tabletop.py')
    sys.modules[module.__name__] = module
    exec(compile(_source('combat/tabletop.py'), module.__file__, 'exec'), module.__dict__)
    return module


def _map(name):
    return json.loads(_source(f'combat/maps/builtin-{name}.json'))


def test_cliff_look_survives_normalization_and_store_reload(tmp_path):
    api = _api()
    document = _map('mountain-pass')
    normalized = api.normalize_map(document)
    assert all(w.get('look') == 'rock_cliff' for w in normalized['walls'])
    store = api.TabletopMapStore(tmp_path)
    store.save(document)
    reloaded = store.get(document['map_id'])
    assert all(w.get('look') == 'rock_cliff' for w in reloaded['walls'])
    assert api.rasterize(normalized) == api.rasterize(api.normalize_map(reloaded))


def test_rice_look_survives_normalization_without_changing_difficult_cells():
    api = _api()
    document = _map('ricefield-bamboo-valley')
    normalized = api.normalize_map(document)
    before_cells = {tuple(c) for t in document['terrain'] if t['type'] == 'DIFFICULT' for c in t['cells']}
    after = next(t for t in normalized['terrain'] if t['type'] == 'DIFFICULT')
    assert after.get('look') == 'rice_tufts'
    after_cells = {tuple(c) for t in normalized['terrain'] if t['type'] == 'DIFFICULT' for c in t['cells']}
    assert after_cells == before_cells
    assert len(after_cells) == 336
    assert len(after['cells']) == 208


def test_reauthored_maps_keep_cached_geometry_and_all_starts_and_huts_reachable():
    for name in ['realm-maple-shrine', 'ricefield-bamboo-valley']:
        document = _map(name)
        normalized = tabletop.normalize_map(document)
        blocked, sight = tabletop.rasterize(normalized)
        assert blocked == {tuple(c) for c in document['cells']['blocked']}
        assert sight == {tuple(c) for c in document['cells']['sight']}
        starts = [tuple(c) for cs in document['starts'].values() for c in cs]
        assert not blocked.intersection(starts)
        seen = {starts[0]}
        queue = deque(seen)
        while queue:
            x, y = queue.popleft()
            for nx, ny in [(x-1, y), (x+1, y), (x, y-1), (x, y+1)]:
                if 0 <= nx < document['width_squares'] and 0 <= ny < document['height_squares'] and (nx, ny) not in seen | blocked:
                    seen.add((nx, ny))
                    queue.append((nx, ny))
        assert set(starts) <= seen
        if name == 'ricefield-bamboo-valley':
            for group in ['nw', 'ne', 'sw', 'se']:
                points = [p for w in document['walls'] if w['id'].startswith(f'hut-{group}-') for p in w['points']]
                center = (int((min(p[0] for p in points) + max(p[0] for p in points))/2),
                          int((min(p[1] for p in points) + max(p[1] for p in points))/2))
                assert center in seen, f'{group}: hut entrance remains reachable'


def test_offline_node_art_and_map_regressions():
    if os.environ.get('MAPART2_BASELINE') == '1':
        files = ['tests/mapart2_round2.test.mjs']
    else:
        files = [str(p.relative_to(APP)) for p in sorted((APP / 'static/tabletop').glob('*.test.mjs'))]
        files += ['tests/mapart2_round2.browser.test.mjs',
                  'tests/sol214_wall_rotation.test.mjs', 'tests/sol217_wall_runs.test.mjs',
                  'tests/wall_height_cards.test.mjs', 'tests/wall_height_editor.test.mjs']
    commands = [['node', '--test', '--test-reporter=tap', *files]] if os.environ.get('MAPART2_BASELINE') != '1' else []
    # Node 26's isolated runner hides this module's dynamic-import failure details in the sandbox.
    # Run this self-contained file without a child test runner; existing tests retain their isolation.
    commands.append(['node', '--test', '--test-isolation=none', '--test-reporter=tap', 'tests/mapart2_round2.test.mjs'])
    for command in commands:
        result = subprocess.run(command, cwd=APP, text=True, capture_output=True, check=False)
        print('\n'.join(line for line in result.stdout.splitlines() if line.startswith('MAPART2') or line.startswith('# ') and
                        any(word in line for word in ['MAPART2', 'tests ', 'pass ', 'fail ', 'skipped ', 'duration_ms '])) )
        assert result.returncode == 0, result.stdout + result.stderr
