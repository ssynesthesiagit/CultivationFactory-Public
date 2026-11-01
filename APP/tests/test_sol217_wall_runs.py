"""Production SVG/board regression; never launches a browser."""
import subprocess
import json
from types import SimpleNamespace
from pathlib import Path


def test_wall_runs_node():
    result = subprocess.run(['node', '--test', '--test-isolation=none',
                             'tests/sol217_wall_runs.test.mjs',
                             'static/tabletop/objects.test.mjs',
                             'static/tabletop/board.test.mjs',
                             'tests/object_catalog_board_ids.test.mjs'],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_authored_layout_is_projected_on_cold_table_read(tmp_path):
    from combat.tabletop_service import TabletopService

    match = tmp_path / 'matches' / 'wall-run'
    match.mkdir(parents=True)
    rows = [{'id': i, 'kind': 'wall_section', 'x': 3, 'y': i + 2} for i in range(3)]
    arena = {'tabletop': {'scale': 100, 'walls': []}, 'map_objects': rows}
    path = match / 'Arena_Battlefield.json'
    original = json.dumps(arena)
    path.write_text(original)
    # Fresh services read the immutable authored layout, not surviving engine objects.
    for _ in range(2):
        service = TabletopService(SimpleNamespace(_match_dir=lambda _: match), tmp_path)
        assert service._map_section('wall-run')['objects'] == rows
    assert path.read_text() == original
