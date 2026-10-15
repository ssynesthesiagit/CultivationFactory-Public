"""Run the production-table identity harness without private seat fixtures."""
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ElementTree


APP = Path(__file__).resolve().parents[1]


def test_production_table_rebinds_private_findings_for_both_initial_players():
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
