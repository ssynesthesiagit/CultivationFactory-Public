"""Ground fog regression gate: offline production geometry and software board mask."""
from pathlib import Path
import subprocess

import pytest

from tests.test_foglook import absolute_imports

APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('name', [
    'tests/fog_mask.test.mjs',
    'static/tabletop/fog_polygon.test.mjs',
])
def test_ground_fog_regressions(name):
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', str(APP / name)],
        cwd=APP, text=True, capture_output=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_obscures_regressions_reject_bound_source_early_return(tmp_path):
    """Both production cases must fail with only the supplemental-cell fix removed."""
    static = APP / 'static/tabletop'
    source = (static / 'fog_polygon.js').read_text()
    start = source.index('    // Bound physical geometry omits obscures-only ability walls.')
    end = source.index('    for(const [x,y] of centerlineCells)', start)
    mutant = tmp_path / 'missing-dynamic.mjs'
    mutant.write_text(absolute_imports(static, source[:start] + source[end:]))
    checks = (APP / 'tests/fog_mask.test.mjs').read_text()
    checks = checks.replace("'../static/tabletop/fog_polygon.js'", repr(mutant.as_uri()))
    checks = absolute_imports(APP / 'tests', checks)
    check = tmp_path / 'missing-dynamic-check.mjs'
    check.write_text(checks)
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', '--test-reporter=tap',
         '--test-name-pattern=LOSLINES3F5: production', str(check)],
        cwd=APP, text=True, capture_output=True, timeout=90,
    )
    assert result.returncode != 0, 'missing dynamic walls unexpectedly passed'
    assert result.stdout.count('not ok ') == 2, result.stdout + result.stderr
    assert result.stdout.count('smoke hides distant floor') == 2, result.stdout + result.stderr
