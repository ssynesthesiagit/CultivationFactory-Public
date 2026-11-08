"""Maple last-seen scenery through the real board, without a GUI or model server."""
import subprocess

from test_foggrey3 import FIXTURES, STATIC, board_data, historical_harness, raster_board
from test_fogedge_frontier import _absolute_imports


def test_maple_memory_keeps_dimmed_canopy_without_blue_cell_outline():
    data = board_data(STATIC / 'fog_memory_board.test.mjs', 'FOGMEM1 Maple')
    image = raster_board(data)
    # The canopy occupies both the trunk square and neighbouring crown overhang.
    for x in (1, 2):
        colors = list(image.crop((x * 64 + 8, 72, x * 64 + 56, 120)).getdata())
        assert sum(r > g * 1.3 and r > b * 1.6 for r, g, b in colors) > 80, \
            'remembered maple crown must retain orange/red pixels under the common fog wash'
    assert 'tt-zone-outline' not in data['markup']
    assert 'tt-mark-move' not in data['markup']
    for y in range(64, 128):
        for x in (127, 128, 191, 192):
            assert data['gridAlpha'][y * data['width'] + x] == 0, \
                'no remembered grid stroke, including the edge of neighbouring canopy cells'


def test_maple_regression_rejects_floor_only_reconstruction(tmp_path):
    # The historical floor-only renderer proves the Maple-specific assertion
    # detects the symptom, rather than merely passing.
    source = (FIXTURES / 'board_eddb793e.js').read_text()
    mutant = tmp_path / 'floor-only-board.mjs'
    mutant.write_text(_absolute_imports(source, STATIC))
    check_source = _absolute_imports((STATIC / 'fog_memory_board.test.mjs').read_text(), STATIC)
    check_source = historical_harness(check_source.replace((STATIC / 'board.js').as_uri(), mutant.as_uri()))
    check_source = check_source.replace('  const store = {getItem:',
        '  board.sceneryRecordAt ||= () => null;\n  const store = {getItem:')
    check = tmp_path / 'maple-memory-check.mjs'
    check.write_text(check_source)
    result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap',
                             '--test-name-pattern=FOGMEM1 Maple', str(check)],
                            text=True, capture_output=True, timeout=120)
    assert result.returncode != 0, 'floor-only reconstruction must fail the Maple canopy regression'
    assert 'remembered Maple cells must restore scenery above the saved floor' in result.stdout, result.stdout + result.stderr
