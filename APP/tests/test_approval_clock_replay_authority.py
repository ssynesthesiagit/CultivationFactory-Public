"""Deterministic replay issuance versus live clock authority.

A character-creation replay freezes ``TIANXIA_DETERMINISTIC_UTC`` at the run's
creation time and seeds the monotonic clock.  Those frozen values are challenge
*content* so scratch and live compilations produce identical bytes.  The clock
rollback guard, however, protects against the *machine* clocks moving backward
and must therefore observe the real clocks even during a replay; otherwise any
later live approval permanently blocks every earlier run's replay/finalization.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings, sha256_bytes
from security.approval_challenges import ApprovalChallengeService
from security.clock_authority import DeterministicTestProcessEpochProvider
from security.integrity import create_test_integrity_service
from security.local_identity import DeterministicTestPrincipalProvider

FROZEN_RUN_CLOCK = "2026-09-10T18:25:07Z"
REPLAY_SEED = "17b0afd831800eb61ba1bf7a96845c4af86f6ff2962c68b92f02aefc3a03e16e"
LIVE_APPROVAL_AT = dt.datetime(2026, 9, 11, 3, 45, 14, 40897, tzinfo=dt.timezone.utc)
SEEDED_MONOTONIC_NS = int(sha256_bytes(REPLAY_SEED.encode("utf-8"))[:15], 16)


class _Clocks:
    def __init__(self, wall: dt.datetime, monotonic: float) -> None:
        self.wall = wall
        self.monotonic = monotonic

    def now(self) -> dt.datetime:
        return self.wall

    def mono(self) -> float:
        return self.monotonic


def _db(tmp_path: Path, name: str = "data") -> Database:
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / name)
    db = Database(settings)
    db.migrate()
    return db


def _service(db: Database, clocks: _Clocks) -> ApprovalChallengeService:
    return ApprovalChallengeService(
        db,
        principal_provider=DeterministicTestPrincipalProvider(),
        integrity=create_test_integrity_service(),
        clock=clocks.now,
        monotonic_clock=clocks.mono,
        process_epoch_provider=DeterministicTestProcessEpochProvider("test-process-epoch:replay"),
    )


_REPLAY = {
    "operation": "stage2_approve",
    "subject_type": "stage2_proposal",
    "subject_id": "proposal-1",
    "exact_bytes": b"exact-proposal-bytes",
    "binding": {"kind": "test"},
}


def _live_gm_approval(service: ApprovalChallengeService) -> None:
    issued = service.issue(
        operation="character_creation_candidate_gm_promote",
        subject_type="character_creation_gm_candidate",
        subject_id="run-1",
        exact_bytes=b"receipt",
    )["challenge"]
    service.consume(
        challenge_id=issued["challenge_id"],
        nonce=issued["nonce"],
        operation="character_creation_candidate_gm_promote",
        subject_type="character_creation_gm_candidate",
        subject_id="run-1",
        exact_bytes=b"receipt",
    )


def _authority(db: Database) -> tuple[str, int]:
    with db.connection() as conn:
        wall = conn.execute(
            "SELECT wall_high_water_at FROM approval_clock_authority_state WHERE singleton_id=1"
        ).fetchone()["wall_high_water_at"]
        mono = conn.execute(
            "SELECT monotonic_high_water_ns FROM approval_process_epochs WHERE process_epoch_id=?",
            ("test-process-epoch:replay",),
        ).fetchone()["monotonic_high_water_ns"]
    return wall, int(mono)


@pytest.fixture
def frozen_replay(monkeypatch):
    monkeypatch.setenv("TIANXIA_DETERMINISTIC_UTC", FROZEN_RUN_CLOCK)
    monkeypatch.setenv("TIANXIA_DETERMINISTIC_APPROVAL_SEED", REPLAY_SEED)


def test_frozen_replay_issues_and_consumes_after_a_later_live_approval(tmp_path, monkeypatch):
    clocks = _Clocks(LIVE_APPROVAL_AT, 100.0)
    db = _db(tmp_path)
    service = _service(db, clocks)
    _live_gm_approval(service)
    assert _authority(db) == ("2026-09-11T03:45:14.040897Z", 100_000_000_000)

    # The replay starts seven real minutes later with the run clock frozen
    # before the live approval.
    clocks.wall = LIVE_APPROVAL_AT + dt.timedelta(minutes=7)
    clocks.monotonic = 520.0
    monkeypatch.setenv("TIANXIA_DETERMINISTIC_UTC", FROZEN_RUN_CLOCK)
    monkeypatch.setenv("TIANXIA_DETERMINISTIC_APPROVAL_SEED", REPLAY_SEED)

    challenge = service.issue(**_REPLAY)["challenge"]

    assert challenge["issued_at"] == FROZEN_RUN_CLOCK
    assert challenge["expires_at"] == "2026-09-10T18:30:07Z"
    assert challenge["clock_authority"]["issued_monotonic_ns"] == SEEDED_MONOTONIC_NS
    # Durable authority follows the real clocks and never moves backward.
    assert _authority(db) == ("2026-09-11T03:52:14.040897Z", 520_000_000_000)

    evidence = service.consume(challenge_id=challenge["challenge_id"], nonce=challenge["nonce"], **_REPLAY)
    assert evidence["consumed_at"] == FROZEN_RUN_CLOCK
    assert evidence["clock_authority"]["consumed_monotonic_ns"] == SEEDED_MONOTONIC_NS


def test_real_wall_rollback_is_still_refused_during_a_frozen_replay(tmp_path, frozen_replay):
    clocks = _Clocks(LIVE_APPROVAL_AT, 100.0)
    db = _db(tmp_path)
    service = _service(db, clocks)
    clocks.wall = LIVE_APPROVAL_AT + dt.timedelta(hours=1)
    service.issue(**_REPLAY)["challenge"]

    clocks.wall = LIVE_APPROVAL_AT
    clocks.monotonic = 200.0
    with pytest.raises(FoundryError) as caught:
        service.issue(**{**_REPLAY, "subject_id": "proposal-2"})
    assert caught.value.code == "APPROVAL_CLOCK_AUTHORITY_ROLLBACK"
    assert caught.value.details == {"wall_rollback": True, "monotonic_rollback": False}


def test_real_monotonic_rollback_is_still_refused_during_a_frozen_replay(tmp_path, frozen_replay):
    clocks = _Clocks(LIVE_APPROVAL_AT, 500.0)
    db = _db(tmp_path)
    service = _service(db, clocks)
    service.issue(**_REPLAY)["challenge"]

    clocks.wall = LIVE_APPROVAL_AT + dt.timedelta(minutes=1)
    clocks.monotonic = 400.0
    with pytest.raises(FoundryError) as caught:
        service.issue(**{**_REPLAY, "subject_id": "proposal-2"})
    assert caught.value.code == "APPROVAL_CLOCK_AUTHORITY_ROLLBACK"
    assert caught.value.details == {"wall_rollback": False, "monotonic_rollback": True}


def test_frozen_replay_challenge_bytes_do_not_depend_on_the_live_clocks(tmp_path, frozen_replay):
    first = _service(_db(tmp_path, "first"), _Clocks(LIVE_APPROVAL_AT, 100.0)).issue(**_REPLAY)["challenge"]
    second = _service(
        _db(tmp_path, "second"),
        _Clocks(LIVE_APPROVAL_AT + dt.timedelta(days=3), 90_000.0),
    ).issue(**_REPLAY)["challenge"]

    assert first == second
