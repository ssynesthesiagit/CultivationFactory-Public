"""Deterministic software raster gate; no browser or live model services."""
from pathlib import Path
import subprocess
import pytest
import re


def absolute_imports(static, source):
    def resolve(match):
        name, sep, query = match[2].partition('?')
        return match[1] + (static / name).resolve().as_uri() + (sep + query if sep else '') + match[1]
    return re.sub(r"(['\"])(\.?\.?/[^'\"]+)\1", resolve, source)


@pytest.mark.parametrize('name', [
    'static/tabletop/fog_memory_board.test.mjs',
    'static/tabletop/board.test.mjs',
    'static/tabletop/occluders.test.mjs',
    'tests/fog_mask.test.mjs',
    'static/tabletop/fog_polygon.test.mjs',
    'tests/fog_altitude.test.mjs',
])
def test_foglook_software_raster(name, capsys):
    app = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', '--test-reporter=tap', str(app / name)],
        capture_output=True, text=True, timeout=180,
    )
    with capsys.disabled():
        for line in result.stdout.splitlines():
            if line.lstrip('# ').startswith('FOGLOOK3'):
                print(line, flush=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_foglook_rejects_old_sharp_cut(tmp_path):
    static = Path(__file__).resolve().parents[1] / 'static/tabletop'

    board = (static / 'board.js').read_text()
    start = board.index('    context.drawImage(fogPresentationCut(')
    end = board.index(';', start) + 1
    board = board[:start] + '    context.drawImage(mask, 0, 0);' + board[end:]
    mutant = tmp_path / 'sharp-board.mjs'
    mutant.write_text(absolute_imports(static, board))
    checks = (static / 'fog_memory_board.test.mjs').read_text()
    checks = checks.replace("from './board.js'", f"from '{mutant.as_uri()}'")
    checks = absolute_imports(static, checks)
    check_file = tmp_path / 'sharp-check.mjs'
    check_file.write_text(checks)
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', '--test-reporter=tap',
         '--test-name-pattern=FOGLOOK3: one modest', str(check_file)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0, 'sharp edges unexpectedly passed'
    assert 'gradient width 0px' in result.stdout, result.stdout + result.stderr


def test_foglook_partial_overlap_rejects_accumulated_opacity(tmp_path):
    """Both board pixel regressions reject the reviewed per-viewer alpha fill."""
    static = Path(__file__).resolve().parents[1] / 'static/tabletop'
    polygon = (static / 'fog_polygon.js').read_text()
    start = polygon.index('  // Union opaque viewer cuts')
    end = polygon.index('  paintFogMask(context,width,height,seen,{...sight,polygons},scale);', start)
    polygon = polygon[:start] + (
        '  paintFogMask(context,width,height,seen,{...sight,polygons:polygons.map(p=>'
        '({...p,shadows:p.wideShadows ?? p.shadows})),opacity:0.58},scale);\n'
    ) + polygon[end:]
    mutant = tmp_path / 'overlap-polygon.mjs'
    mutant.write_text(absolute_imports(static, polygon))
    presentation = absolute_imports(static, (static / 'fog_presentation.js').read_text())
    presentation = re.sub(r"file:[^'\"]*/fog_polygon.js\?[^'\"]+", mutant.as_uri(), presentation)
    cut = tmp_path / 'overlap-presentation.mjs'
    cut.write_text(presentation)
    board = absolute_imports(static, (static / 'board.js').read_text())
    board = re.sub(r"file:[^'\"]*/fog_presentation.js\?[^'\"]+", cut.as_uri(), board)
    board_file = tmp_path / 'overlap-board.mjs'
    board_file.write_text(board)
    checks = absolute_imports(static, (static / 'fog_memory_board.test.mjs').read_text())
    checks = checks.replace((static / 'board.js').as_uri(), board_file.as_uri())
    check_file = tmp_path / 'overlap-check.mjs'
    check_file.write_text(checks)
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', '--test-reporter=tap',
         '--test-name-pattern=FOGLOOK3F: partial shadow', str(check_file)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0, 'per-viewer opacity unexpectedly passed'
    assert '# fail 2' in result.stdout, result.stdout + result.stderr
    assert result.stdout.count('redundant partial sight must leave every wash pixel identical') == 2, result.stdout


def test_foglook_rejects_round2(tmp_path):
    """The round-3 floor/outline checks reject the owner's rejected round 2."""
    app = Path(__file__).resolve().parents[1]
    static = app / 'static/tabletop'
    board = (static / 'board.js').read_text()
    fixture = app / 'tests/fixtures/foglook_round2_cut.mjs'
    original = "import {softFogCut, fogPresentationCut} from './fog_presentation.js?v=foglook3f';"
    assert original in board
    board = board.replace(original, f"import {{softFogCut}} from '{fixture.as_uri()}';")
    start = board.index('    context.drawImage(fogPresentationCut(')
    end = board.index(';', start) + 1
    board = board[:start] + '    context.drawImage(softFogCut(mask, scale, fog), 0, 0);' + board[end:]
    mutant = tmp_path / 'round2-board.mjs'
    mutant.write_text(absolute_imports(static, board))
    checks = (static / 'fog_memory_board.test.mjs').read_text()
    checks = checks.replace("from './board.js'", f"from '{mutant.as_uri()}'")
    check_file = tmp_path / 'round2-check.mjs'
    check_file.write_text(absolute_imports(static, checks))
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', '--test-reporter=tap',
         '--test-name-pattern=FOGLOOK3: one modest', str(check_file)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0, 'round 2 unexpectedly passed'
    assert 'gradient width' in result.stdout, result.stdout + result.stderr


def test_foglook3_fixture_metrics(capsys):
    app = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', '--test-reporter=tap',
         '--test-name-pattern=FOGLOOK3: (bundled|fortress|shrine|waterfall)',
         str(app / 'static/tabletop/fog_memory_board.test.mjs')],
        capture_output=True, text=True, timeout=180,
    )
    with capsys.disabled():
        for line in result.stdout.splitlines():
            if line.lstrip('# ').startswith('FOGLOOK3'):
                print(line, flush=True)
    assert result.returncode == 0, result.stdout + result.stderr
