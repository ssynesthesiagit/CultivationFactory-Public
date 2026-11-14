"""A saved fight's deletion shares the durable writer reservation."""
from pathlib import Path

import pytest

from agent_seats.runner import SeatRunner
from combat.diagnostics import CombatGate1Error
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]


def test_delete_respects_writer_and_retained_store(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="DELETE-OWNERSHIP-PROBE", maximum_rounds=3)
    combat._read_metadata(session.match_id, session)
    table = TabletopService(combat, tmp_path)
    seats = SeatRunner.__new__(SeatRunner)
    seats.table = table

    with session.store.writer_lock():
        with pytest.raises(TabletopError) as error:
            table.delete_match(session.match_id)
        assert error.value.code == "TABLETOP_BUSY"
        assert session.store.match_dir.is_dir()
        assert session.store.genesis_path.is_file()
        assert session.store.match_lock_path.is_file()
        with pytest.raises(CombatGate1Error) as metadata_error:
            combat._write_metadata(session.match_id, {"match_id": session.match_id})
        assert metadata_error.value.diagnostic.code == "MATCH_STORAGE_LOCKED"
        with pytest.raises(CombatGate1Error) as seat_error:
            seats._write_playback(session.match_id, True)
        assert seat_error.value.diagnostic.code == "MATCH_STORAGE_LOCKED"

    table.delete_match(session.match_id)
    assert not session.store.match_dir.exists()
    with pytest.raises(FileNotFoundError):
        with session.store.writer_lock():
            pass
    with pytest.raises(FileNotFoundError):
        with session.mechanical.command_boundary():
            pass
    with pytest.raises(FileNotFoundError):
        session.mechanical.export()
    with pytest.raises(FileNotFoundError):
        seats._write_playback(session.match_id, True)
    assert not session.store.match_dir.exists()

    with pytest.raises(CombatServiceError) as error:
        combat._read_metadata(session.match_id, session)
    assert error.value.diagnostic.code == "COMBAT_MATCH_NOT_FOUND"
    with pytest.raises(CombatServiceError) as error:
        combat._write_metadata(session.match_id, {"match_id": session.match_id})
    assert error.value.diagnostic.code == "COMBAT_MATCH_NOT_FOUND"
    assert not session.store.match_dir.exists()
