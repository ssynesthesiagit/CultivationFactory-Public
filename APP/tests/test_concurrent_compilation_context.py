"""Overlapping runs must not share replay clocks or approval identities."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import os
from threading import Event

import pytest

from app.core import deterministic_approval_seed, deterministic_replay, deterministic_utc, sha256_bytes, sha256_json, utcnow
from character_creation.service import CharacterCreationExecutionService
from security.approval_challenges import ApprovalChallengeService


def test_overlapping_compilations_keep_run_clock_and_approval_seed(monkeypatch):
    monkeypatch.delenv("TIANXIA_DETERMINISTIC_UTC", raising=False)
    monkeypatch.delenv("TIANXIA_DETERMINISTIC_APPROVAL_SEED", raising=False)
    first_inside, second_inside, first_sampled, second_done = (Event() for _ in range(4))
    runs = [
        {"run_id": "first", "created_at": "2026-09-24T22:49:35Z", "request": {"request_sha256": "a" * 64}},
        {"run_id": "second", "created_at": "2026-09-24T22:55:27Z", "request": {"request_sha256": "b" * 64}},
    ]
    approval = object.__new__(ApprovalChallengeService)
    approval._clock = lambda: dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)
    approval._monotonic_clock = lambda: 123.0

    def content():
        return {
            "created_at": utcnow(),
            "issued_at": approval._now().isoformat(),
            "issued_monotonic_ns": approval._monotonic_now_ns(),
        }

    def compile_once(run, plan, index, **kwargs):
        if run["run_id"] == "first" and index == 1:
            first_inside.set()
            assert second_inside.wait(10)
            observed = content()
            first_sampled.set()
            assert second_done.wait(10)
        elif run["run_id"] == "second" and index == 1:
            assert first_inside.wait(10)
            second_inside.set()
            assert first_sampled.wait(10)
            observed = content()
        else:
            observed = content()
        identity = sha256_json(observed)
        return {"candidate_identity": identity, "identities": {"projection": identity}, "artifacts": {"projection": observed}}

    service = object.__new__(CharacterCreationExecutionService)
    service._compile_once = compile_once
    service._write_compile_checkpoint = lambda *args, **kwargs: None

    def compile_run(run):
        try:
            return service._compile_twice(run, {}, candidate_gm_authority={})
        finally:
            if run["run_id"] == "second":
                second_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(compile_run, runs[0])
        assert first_inside.wait(10)
        second = pool.submit(compile_run, runs[1])
        results = [first.result(timeout=20), second.result(timeout=20)]

    for run, result in zip(runs, results):
        assert result["deterministic"] is True
        assert result["independent_compilations"] == 2
        assert result["artifacts"]["projection"]["created_at"] == run["created_at"]
        assert result["artifacts"]["projection"]["issued_monotonic_ns"] == int(
            sha256_bytes(run["request"]["request_sha256"].encode())[:15], 16
        )
    assert "TIANXIA_DETERMINISTIC_UTC" not in os.environ
    assert "TIANXIA_DETERMINISTIC_APPROVAL_SEED" not in os.environ


@pytest.mark.parametrize("configured", [False, True])
def test_replay_does_not_change_an_unscoped_walk_and_restores_after_failure(monkeypatch, configured):
    for key in ("TIANXIA_DETERMINISTIC_UTC", "TIANXIA_DETERMINISTIC_APPROVAL_SEED"):
        if configured:
            monkeypatch.setenv(key, "configured")
        else:
            monkeypatch.delenv(key, raising=False)
    entered, observed = Event(), Event()

    def compile_scope():
        with deterministic_replay("outer-clock", "outer-seed"):
            entered.set()
            assert observed.wait(10)
            with pytest.raises(RuntimeError, match="failed inner compile"):
                with deterministic_replay("inner-clock", "inner-seed"):
                    assert (utcnow(), deterministic_approval_seed()) == ("inner-clock", "inner-seed")
                    raise RuntimeError("failed inner compile")
            assert (utcnow(), deterministic_approval_seed()) == ("outer-clock", "outer-seed")
        return deterministic_utc(), deterministic_approval_seed()

    expected = "configured" if configured else None
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(compile_scope)
        try:
            assert entered.wait(10)
            # A walk/create on another thread keeps its ordinary clock/entropy.
            assert (deterministic_utc(), deterministic_approval_seed()) == (expected, expected)
            assert utcnow() != "outer-clock"
        finally:
            observed.set()
        assert future.result(timeout=20) == (expected, expected)
