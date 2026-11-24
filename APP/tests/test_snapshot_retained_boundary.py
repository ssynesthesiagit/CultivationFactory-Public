"""An explicit checkpoint must describe the retained session's current boundary."""
import json
from pathlib import Path

import pytest

from combat.diagnostics import CombatGate1Error
from combat.gate3_reducer import canonical_state_sha256
from combat.gate4_persistence import Gate4Persistence
from tests.persistence_support import end_turn, inventory

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("prior_turns", [0, 1])
def test_retained_snapshot_refuses_an_advanced_durable_tail(tmp_path, prior_turns):
    persistence = Gate4Persistence(ROOT, tmp_path)
    retained = persistence.create_match(match_seed=f"RETAINED-SNAPSHOT-{prior_turns}")
    for _ in range(prior_turns):
        end_turn(retained)
    retained.mechanical.explicit_snapshot()

    current = persistence.load_match(retained.match_id)
    end_turn(current)
    expected = canonical_state_sha256(current.engine.state)
    saved = inventory(current.store.match_dir)

    with pytest.raises(CombatGate1Error) as caught:
        retained.mechanical.explicit_snapshot()
    assert caught.value.diagnostic.code == "MATCH_SESSION_STALE"
    assert inventory(current.store.match_dir) == saved

    # A fresh caller can still create a useful checkpoint, and the complete
    # saved state remains readable and replayable after the refusal.
    reopened = Gate4Persistence(ROOT, tmp_path).load_match(current.match_id)
    checkpoint = reopened.mechanical.explicit_snapshot()
    assert checkpoint.is_file()
    assert reopened.verify()["status"] == "PASS"
    assert reopened.mechanical.replay()["canonical_state_sha256"] == expected
    end_turn(reopened)
    continued = Gate4Persistence(ROOT, tmp_path).load_match(current.match_id)
    assert canonical_state_sha256(continued.engine.state) == canonical_state_sha256(reopened.engine.state)


def test_snapshot_uses_an_existing_command_reservation(tmp_path):
    session = Gate4Persistence(ROOT, tmp_path).create_match(match_seed="NESTED-SNAPSHOT")
    with session.mechanical.command_boundary():
        assert session.mechanical._command_reserved
        path = session.mechanical.explicit_snapshot()
        assert path.is_file()
    assert not session.mechanical._command_reserved
    assert session.verify()["status"] == "PASS"


@pytest.mark.parametrize("maximum_rounds", [5, 30])
@pytest.mark.parametrize("operation", ["command", "snapshot"])
def test_reused_match_id_does_not_authorize_a_retained_writer(tmp_path, monkeypatch, maximum_rounds, operation):
    from combat import gate3_storage
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    now = ["2026-11-13T00:00:00+00:00"]
    monkeypatch.setattr(gate3_storage, "_utc_display", lambda: now[0])
    persistence = Gate4Persistence(ROOT, tmp_path)
    retained = persistence.create_match(match_seed="RECREATED-IDENTITY", maximum_rounds=5)
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    table.delete_match(retained.match_id)
    now[0] = "2026-11-13T00:00:01+00:00"
    replacement = persistence.create_match(match_seed="RECREATED-IDENTITY", maximum_rounds=maximum_rounds)
    assert replacement.match_id == retained.match_id
    assert replacement.mechanical._records == retained.mechanical._records == []
    assert replacement.match_lock != retained.match_lock
    saved = inventory(replacement.store.match_dir)

    with pytest.raises(CombatGate1Error) as caught:
        if operation == "command":
            end_turn(retained)
        else:
            retained.mechanical.explicit_snapshot()
    assert caught.value.diagnostic.code == "MATCH_SESSION_STALE"
    assert inventory(replacement.store.match_dir) == saved
    loaded = Gate4Persistence(ROOT, tmp_path).load_match(replacement.match_id)
    assert loaded.engine.state.maximum_rounds == maximum_rounds
    end_turn(loaded)
    assert Gate4Persistence(ROOT, tmp_path).load_match(loaded.match_id).verify()["status"] == "PASS"


def test_lock_json_formatting_does_not_invalidate_the_retained_owner(tmp_path):
    session = Gate4Persistence(ROOT, tmp_path).create_match(match_seed="SAME-LOCK-DIFFERENT-JSON")
    path = session.store.match_lock_path
    path.write_text(json.dumps(json.loads(path.read_text()), indent=2) + "\n")
    session.mechanical.explicit_snapshot()
    end_turn(session)
    assert session.verify()["status"] == "PASS"
