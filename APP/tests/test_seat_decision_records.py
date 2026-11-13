"""Model seat decisions leave one training record in the Factory data dir; a failed write never changes the turn."""
import json

from agent_seats import decision_records
from combat.gate4_controller import LocalDeterministicController
from tests.test_agent_seats import raw_state
from tests.test_d1_seat import endpoint, runner_for_d1  # noqa: F401  (endpoint fixture)
from tests.test_hunt5_player_choices import fixture, FOE


def _records(data_dir):
    return [json.loads(line) for line in (data_dir / "seat_decisions.jsonl").read_text(encoding="utf-8").splitlines()]


def test_fake_d1_decision_writes_one_record(endpoint, tmp_path, monkeypatch):
    # This regression asserts the legacy complete-plan prompt/binding. Ranked
    # next-step records are covered separately, including active then End.
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    model, url = endpoint
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    runner = runner_for_d1(tmp_path, table, url)
    runner.set_seat(mid, FOE, "MODEL", "d1")
    assert runner.drive(mid, max_steps=1) == 1
    [record] = _records(tmp_path)
    row = runner.decisions(mid)[0]
    assert record["match_id"] == mid and record["kind"] == "TURN" and record["provider_id"] == "d1"
    assert record["prompt"].startswith("Choose one complete plan") and "Reply A-L" in record["prompt"]
    assert set(record["options"]) == set(record["answers"]) and "A" in record["options"]
    assert record["answers"][record["chosen_id"]] == {"plan": row["chosen"]}
    assert record["built_in_id"] == record["chosen_id"] == "A"
    assert record["probabilities"] == row["decision"]["probabilities"]
    assert record["fallback"] is False and record["latency_ms"] == row["latency_ms"]


def test_failed_record_write_keeps_turn(endpoint, tmp_path):
    model, url = endpoint
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    runner = runner_for_d1(tmp_path, table, url)
    runner.set_seat(mid, FOE, "MODEL", "d1")
    (tmp_path / "seat_decisions.jsonl").mkdir()  # the append cannot open a directory
    before = raw_state(runner, mid)["last_sequence"]
    assert runner.drive(mid, max_steps=1) == 1
    assert raw_state(runner, mid)["last_sequence"] > before
    assert not runner.decisions(mid)[0]["fallback"]
    assert combat._load_session(mid).verify()["status"] == "PASS"


def test_recording_can_be_turned_off(endpoint, tmp_path, monkeypatch):
    model, url = endpoint
    monkeypatch.setenv("FACTORY_SEAT_RECORDS", "0")
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    runner = runner_for_d1(tmp_path, table, url)
    runner.set_seat(mid, FOE, "MODEL", "d1")
    assert runner.drive(mid, max_steps=1) == 1
    assert not (tmp_path / "seat_decisions.jsonl").exists()
