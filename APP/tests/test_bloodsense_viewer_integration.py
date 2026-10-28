"""Run the production-table identity harness without private seat fixtures."""
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ElementTree


APP = Path(__file__).resolve().parents[1]
# The public test exporter cannot infer cache-query import URLs yet. Declare
# the actual shipped JS dependencies explicitly; no image assets are needed.
RUNTIME_MODULES = (
    'static/tabletop/active.js',
    'static/tabletop/art-kit.js',
    'static/tabletop/map-height-cards.js',
    'static/tabletop/object-arrange.js',
    'static/tabletop/object-art-catalog.js',
    'static/tabletop/remembered_scenery.js',
    'static/tabletop/scenery-raster.js',
    'static/tabletop/wall-object-art.js',
)


def test_production_table_rebinds_private_findings_for_both_initial_players():
    for module in RUNTIME_MODULES:
        assert (APP / module).is_file(), f'Production table dependency missing: {module}'
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', '--test-reporter=junit',
         'tests/viewer_identity_dialog.test.mjs'],
        cwd=APP, capture_output=True, text=True, timeout=90,
        env={**os.environ, 'SOL219_BROWSER': '0'},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = ElementTree.fromstring(result.stdout)
    for chosen in ('a', 'b'):
        name = (f'the complete production table binds {chosen}, replaces private '
                'facts on rebinding, and clears them for GM')
        cases = [case for case in report.iter('testcase') if case.get('name') == name]
        assert len(cases) == 1 and not list(cases[0]), f'{name} must run without skips'
