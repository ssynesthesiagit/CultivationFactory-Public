"""LIGHTS2F6 finding 1: a turn action that pauses for a reaction saves its pending action and a cold reload recovers it.

Without the atomic_write_bytes import in TabletopService._save_pending_action, every non-None save raised NameError.
"""
import json

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_hunt5_player_choices import fixture


def test_pending_action_is_written_to_disk_and_recovered_after_reload(tmp_path):
    data = tmp_path / "actual"
    _service, table, match_id, character_id, _send = fixture(data, "TAL_FENCING_FOOTWORK")
    initial = table.state(match_id)
    menu = initial["menu"]
    args = (match_id, character_id, menu["decision_id"], menu["state_version"], initial["last_sequence"], [])
    response = table.act(*args)
    assert response["status"] == "REACTION_REQUIRED"

    path = table._pending_action_path(match_id)
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["method"] == "act"

    reopened = TabletopService(CombatService(ROOT, data), data)
    assert reopened.state(match_id)["pending_action"]["reaction"] == response["reaction"]


def test_save_pending_action_writes_value_and_none_removes_it(tmp_path):
    data = tmp_path / "actual"
    _service, table, match_id, _character_id, _send = fixture(data, "TAL_FENCING_FOOTWORK")
    path = table._pending_action_path(match_id)
    table._save_pending_action(match_id, {"schema": "TabletopPendingAction.v2", "method": "act"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema": "TabletopPendingAction.v2", "method": "act"}
    table._save_pending_action(match_id, None)
    assert not path.exists()
