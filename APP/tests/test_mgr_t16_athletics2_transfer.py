"""Typed cover transfers retain their declaration's reach through table reload."""
from combat.gate5_service import CombatServiceError
from tests.test_mgr_t16_athletics_1_close import (
    test_cover_caused_miss_transfers_original_roll_through_table as transfer_case,
)


def test_shared_space_cover_transfer_keeps_legal_runtime_intent(tmp_path, monkeypatch):
    try:
        transfer_case(tmp_path, monkeypatch)
    except CombatServiceError as exc:
        raise AssertionError(exc.diagnostic.details) from exc
