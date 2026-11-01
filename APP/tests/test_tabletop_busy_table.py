"""MMX112 (round 24 live 42e43e14, HUNT110 F2): a second window on one table gets a plain "try again", never a
server error.

The table already queues a fight two ways, and both are deliberate: ``_one_at_a_time`` holds a per-fight lock so
this server cannot race its own requests, and ``_pending_writer`` takes a cross-process lock on
``.tabletop_action.lock`` so two browser windows cannot either. That second lock is taken non-blocking on
purpose, and when it could not be taken ``gate3_storage`` raised ``CombatGate1Error`` straight out of the
request. The live service answered HTTP 500 (2026-09-29T11:05:59 and 11:06:00, two client ports, one second
apart, the same match) and the player was left with a broken table and nothing to act on.

The guard was correct. Only the surfacing was wrong, and that is what these tests hold in place: a busy table
now waits briefly, then answers 409 with text a player can act on.
"""
import threading
import time
from pathlib import Path

import pytest

from combat import tabletop_service
from combat.gate3_storage import LocalMatchWriterLock
from combat.tabletop import TabletopError

from tests.r1i_service_support import FOE, OWNER, SECOND, fixture


def _table(tmp_path, monkeypatch, wait_s=0.3):
    monkeypatch.setattr(tabletop_service, "TABLE_BUSY_WAIT_S", wait_s)
    return fixture(tmp_path, [], positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}})


def _hold(combat, mid):
    """The cross-process table lock, exactly as the other window would hold it."""
    return LocalMatchWriterLock(combat._match_dir(mid) / ".tabletop_action.lock", mid)


def test_a_busy_table_answers_try_again_instead_of_a_server_error(tmp_path, monkeypatch):
    """The live symptom: this is the request that answered 500."""
    combat, table, mid, _send, _commit = _table(tmp_path, monkeypatch)
    with _hold(combat, mid):
        with pytest.raises(TabletopError) as raised:
            table.auto_step(mid, table.state(mid)["last_sequence"], [])
    assert raised.value.status_code == 409, "a busy table must be a conflict the page can recover from"
    assert raised.value.code == "TABLETOP_BUSY"


def test_the_player_is_told_what_to_do_in_plain_words(monkeypatch):
    """Owner 2026-09-30: readable for someone who knows nothing but basic D&D.

    No code names, no "MATCH_STORAGE_LOCKED", no stack jargon -- say what happened and what to do next.
    """
    message = tabletop_service.TABLE_BUSY_MESSAGE
    lowered = message.lower()
    assert "try again" in lowered, "the player is not told what to do next"
    for jargon in ("match_storage_locked", "combatgate", "gate3", "flock", "fcntl", "traceback",
                   ".tabletop_action", "state_version", "non-blocking", "409"):
        assert jargon not in lowered, f"the player is shown an internal name: {jargon!r}"
    assert " " in message and message.strip() == message


def test_a_request_that_arrives_just_after_another_one_waits_and_then_works(tmp_path, monkeypatch):
    """The ordinary case is two clicks a moment apart, and both should simply happen."""
    combat, table, mid, _send, _commit = _table(tmp_path, monkeypatch, wait_s=5.0)
    holder = threading.Event()
    released = threading.Event()

    def hold_briefly():
        with _hold(combat, mid):
            holder.set()
            released.wait(5.0)

    worker = threading.Thread(target=hold_briefly, daemon=True)
    worker.start()
    assert holder.wait(5.0), "the other window never took the table"
    threading.Timer(0.3, released.set).start()
    try:
        result = table.auto_step(mid, table.state(mid)["last_sequence"], [])
    finally:
        released.set()
        worker.join(5.0)
    # The point is that this request was SERVED, not refused: a near-simultaneous second click must queue for
    # the brief wait and then do its work. (Which status it returns depends on whose turn it was; any of the
    # table's normal answers is a pass, a TabletopError is a fail.)
    assert isinstance(result, dict) and result.get("status"), f"the queued request was not served: {result!r}"
    assert "status" in result and result["status"] != "TABLETOP_BUSY"


def test_a_wait_that_runs_out_still_answers_409_not_500(tmp_path, monkeypatch):
    """Queueing must not turn one stuck window into one hanging request."""
    combat, table, mid, _send, _commit = _table(tmp_path, monkeypatch, wait_s=0.2)
    with _hold(combat, mid):
        started = time.monotonic()
        with pytest.raises(TabletopError) as raised:
            table.auto_step(mid, table.state(mid)["last_sequence"], [])
        waited = time.monotonic() - started
    assert raised.value.status_code == 409
    assert waited < 3.0, f"the request hung for {waited:.1f}s instead of giving up cleanly"


def test_the_fight_is_untouched_by_a_refused_request(tmp_path, monkeypatch):
    """A refusal must not half-commit: the table reloads and still replays."""
    from tests.h49_fog_support import assert_roundtrip

    combat, table, mid, _send, commit = _table(tmp_path, monkeypatch)
    commit(table.state(mid)["menu"]["end_turn"])
    before = table.state(mid)["last_sequence"]
    with _hold(combat, mid):
        with pytest.raises(TabletopError):
            table.auto_step(mid, before, [])
    assert table.state(mid)["last_sequence"] == before
    assert_roundtrip(combat, tmp_path, mid)


def test_the_api_answers_a_busy_table_with_409_not_500(tmp_path, monkeypatch):
    """The reported symptom verbatim: POST /api/tabletop/matches/.../auto-step returned 500.

    Over real HTTP, through the real app, so the whole chain is covered -- the endpoint's TabletopError wrapper,
    the CSRF guard, and the status the player's browser actually sees.
    """
    from fastapi.testclient import TestClient
    from jsonschema import Draft202012Validator

    from app.api import create_app
    from app.core import Settings

    monkeypatch.setattr(tabletop_service, "TABLE_BUSY_WAIT_S", 0.2)
    combat, _table_service, mid, _send, _commit = fixture(
        tmp_path, [], positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}}
    )
    # The app validates its JSON schemas against the test-only external key context, as the browser harnesses do.
    original = Draft202012Validator.check_schema
    Draft202012Validator.check_schema = classmethod(lambda cls, schema, format_checker=None: None)
    try:
        app = create_app(Settings.from_env(Path(__file__).resolve().parents[1], tmp_path))
    finally:
        Draft202012Validator.check_schema = original
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
    body = {"after": 0, "reactions": []}

    with _hold(combat, mid):
        busy = client.post(f"/api/tabletop/matches/{mid}/auto-step", json=body, headers=headers)
    assert busy.status_code == 409, f"a busy table answered {busy.status_code}, not 409: {busy.text[:300]}"
    assert busy.json()["error"]["code"] == "TABLETOP_BUSY"
    assert tabletop_service.TABLE_BUSY_MESSAGE in busy.text, "the player is not shown a plain explanation"

    # The same request with the table free must still work, so the guard is not simply refusing everything.
    free = client.post(f"/api/tabletop/matches/{mid}/auto-step", json=body, headers=headers)
    assert free.status_code == 200, f"an idle table answered {free.status_code}: {free.text[:300]}"
