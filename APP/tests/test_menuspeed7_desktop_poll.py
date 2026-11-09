"""Real-service inspections crossing the desktop's normal unchanged-state poll."""
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_menuspeed7_assisted import offered


@pytest.mark.parametrize('inspection', ['source', 'move'])
def test_desktop_inspection_survives_in_flight_poll(offered, inspection):
    # The shared fixture uses an offline embedding transport, never a live server.
    result = subprocess.run(['node', 'tests/menuspeed7_desktop_poll.mjs', inspection],
        cwd=Path(__file__).resolve().parents[1], input=json.dumps(offered),
        capture_output=True, text=True, timeout=45)
    output = result.stdout + result.stderr
    # Put the Node assertion before stack frames so abbreviated failure
    # output describes what went wrong.
    diagnostic = ' | '.join(line.strip() for line in output.splitlines()
        if any(word in line for word in ('AssertionError', 'Error:', 'actual:', 'expected:')))
    assert result.returncode == 0, diagnostic + '\n' + output
