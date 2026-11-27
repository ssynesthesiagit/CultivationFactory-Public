"""Native paid-teleport fixtures retain the compiled Earth response on reload."""
import pytest

from combat.ext.earth_responses import rows
from combat.gate5_service import CombatService
from tests.test_mmx86_paid_teleport_variant import ROOT, FOE, GRAVE, _table


@pytest.mark.parametrize("unbind_paid", [False, True])
def test_paid_teleport_fixture_retains_grave_response_after_reload(tmp_path, unbind_paid):
    # The public exporter must discover the split-rule input through _table.
    # Do not name that file here: doing so would hide a broken helper contract.
    _, table, mid = _table(tmp_path, grave=True, unbind_paid=unbind_paid)
    assert table.state(mid)["menu"]
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    response_rows = rows(engine, engine.state.actors[FOE], "grave")
    assert len(response_rows) == 1, "fixture lost the printed teleport response"
    assert response_rows[0]["feature_id"] == GRAVE
