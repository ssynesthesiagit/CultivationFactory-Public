"""A fight whose writer lock another request of this server holds for a moment is waited for, not refused (owner
2026-09-29: "Another local process currently owns this match directory")."""

import pytest

from combat.gate5_service import CombatService


class _Busy(ValueError):
    code = "MATCH_STORAGE_LOCKED"


class _Persistence:
    def __init__(self, busy_times, error=_Busy, message="Another local process currently owns this match directory."):
        self.calls, self.busy_times, self.error, self.message = 0, busy_times, error, message

    def load_match(self, match_id, recover=True):
        self.calls += 1
        if self.calls <= self.busy_times:
            raise self.error(self.message)
        return "session"


def _service(persistence):
    service = CombatService.__new__(CombatService)
    service.persistence = persistence
    return service


def test_a_busy_lock_is_waited_for():
    persistence = _Persistence(busy_times=3)
    assert _service(persistence)._load_waiting_for_lock("match:x") == "session" and persistence.calls == 4


def test_it_gives_up_after_the_wait():
    persistence = _Persistence(busy_times=10**6)
    with pytest.raises(_Busy):
        _service(persistence)._load_waiting_for_lock("match:x", wait_s=0.2)


def test_other_errors_are_not_retried():
    persistence = _Persistence(busy_times=1, error=FileNotFoundError, message="no such match")
    with pytest.raises(FileNotFoundError):
        _service(persistence)._load_waiting_for_lock("match:x")
    assert persistence.calls == 1
