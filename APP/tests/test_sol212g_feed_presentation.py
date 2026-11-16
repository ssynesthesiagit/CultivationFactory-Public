"""Read-only UI grouping tested with a real persisted table feed and cold reload."""
import json
import subprocess

import pytest

from combat.tabletop_service import TabletopService
from tests.test_builtin_arenas import ROOT, _fight


@pytest.mark.parametrize('map_id', ['builtin-willow-village-compound', 'builtin-jade-sutra-hall'])
def test_initial_breakables_default_log_keeps_all_events(tmp_path, map_id):
    combat, mid = _fight(tmp_path, 'battlefield:map.' + map_id, size=2, rounds=1)
    table = TabletopService(combat, tmp_path)
    feed = table.events(mid, 0)
    before = table.state(mid)
    result = subprocess.run(['node', str(ROOT / 'tests/sol212g_feed_check.mjs')],
                            input=json.dumps(feed['events']), text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    # Presentation only: repeated polling/cold load leaves the saved state and
    # complete per-object feed identical, including its sequence cursor.
    assert TabletopService(combat, tmp_path).events(mid, 0) == feed
    assert TabletopService(combat, tmp_path).state(mid) == before
