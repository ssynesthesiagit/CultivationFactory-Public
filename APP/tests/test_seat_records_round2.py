"""Seat decision records: profile labels, timed-out answers, rotation under concurrency, and backfill schema."""
import json
import multiprocessing

from agent_seats import decision_records
from agent_seats.runner import SeatRunner
from agent_seats.providers import ProviderRegistry
from combat.gate4_controller import LocalDeterministicController
from tests.test_agent_seats import FakeProvider, raw_state
from tests.test_hunt5_player_choices import fixture, FOE
from tools.seat_records_export import backfill_row, export, training_row


def _records(data_dir):
    return [json.loads(line) for line in (data_dir / "seat_decisions.jsonl").read_text(encoding="utf-8").splitlines()]


def _runner_with_profile(tmp_path, table, provider, profile):
    registry = tmp_path / "providers.json"
    registry.write_text(json.dumps({"providers": [{"id": "fake", "kind": "local", "model": "offline",
        "base_url": "http://127.0.0.1:1/v1", "timeout_s": 1, "prompt_profile": profile}]}))
    return SeatRunner(table, registry=ProviderRegistry(registry), provider=provider, background=False)


def test_full_compact_tiny_profiles_record_a_chosen_label(tmp_path):
    for profile in ("full", "compact", "tiny"):
        data_dir = tmp_path / profile
        data_dir.mkdir()
        combat, table, mid, *_ = fixture(data_dir, "AIR_BASE_GATHER_CURRENT")
        combat.controller = LocalDeterministicController()
        runner = _runner_with_profile(data_dir, table, FakeProvider(attack=True), profile)
        runner.set_seat(mid, FOE, "MODEL", "fake")
        assert runner.drive(mid, max_steps=1) == 1
        [record] = _records(data_dir)
        [saved] = [r for r in runner.decisions(mid) if r["kind"] == "TURN"]
        assert record["prompt_profile"] == profile
        assert record["chosen_id"] is not None
        assert record["answers"][record["chosen_id"]]["plan"][0] == runner.decisions(mid)[0]["chosen"][0]
        # Use the real persisted runner row: TURN chosen is a list of legal IDs,
        # and the teacher is the built-in legal ID, not a fabricated letter.
        assert isinstance(saved["chosen"], list)
        assert saved["chosen"] and all(key in record["answers"] for key in saved["chosen"])
        assert saved["built_in_pick"] in record["answers"]
        assert training_row(record)["teacher_label"] == saved["built_in_pick"]
        # The saved row's decision_id must match the live record's, so the
        # exporter can tell they are the same decision and not double-count it.
        assert saved["decision_id"] == record["decision_id"]
        # Non-D1 saved rows do not retain a letter menu, so backfill must skip
        # them rather than inventing a teacher mapping.
        assert backfill_row(mid, saved) is None


def test_timed_out_choice_keeps_offered_answer_map(tmp_path):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()

    class Timeout(FakeProvider):
        def __call__(self, *args, **kwargs):
            raise TimeoutError("model timed out")

    runner = _runner_with_profile(tmp_path, table, Timeout(), "choices")
    runner.set_seat(mid, FOE, "MODEL", "fake")
    assert runner.drive(mid, max_steps=1) == 1
    [record] = _records(tmp_path)
    assert record["fallback"] is True
    assert record["answers"] and set(record["options"]) == set(record["answers"])
    assert record["chosen_id"] in record["answers"]


def _append_many(data_dir, start, count, start_gate, results):
    start_gate.wait()
    results.put([decision_records.append(data_dir, {"n": n, "pad": "x" * 4}, max_bytes=500)
                 for n in range(start, start + count)])


def test_rotation_keeps_every_record_under_concurrent_writers(tmp_path):
    # One oversized retained file forces exactly one rotation; every concurrent
    # append then fits in the live file. This catches replacement of .1 by a
    # later writer while keeping the exact retained set deterministic.
    (tmp_path / "seat_decisions.jsonl").write_text(
        json.dumps({"n": -1, "pad": "history" * 90}) + "\n", encoding="utf-8")
    ctx = multiprocessing.get_context("fork")
    gate = ctx.Event()
    results = ctx.Queue()
    workers = [ctx.Process(target=_append_many, args=(tmp_path, w * 100, 3, gate, results))
               for w in range(4)]
    for worker in workers:
        worker.start()
    gate.set()
    for worker in workers:
        worker.join()
        assert worker.exitcode == 0
    assert all(all(results.get(timeout=2)) for _ in workers)
    written = {-1, *(w * 100 + n for w in range(4) for n in range(3))}
    live = tmp_path / "seat_decisions.jsonl"
    rotated = tmp_path / "seat_decisions.jsonl.1"
    retained = [json.loads(line)["n"] for path in (rotated, live) if path.exists()
                for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(retained) == len(set(retained))
    assert set(retained) == written
    assert live.stat().st_size <= 500 and rotated.exists()


def test_backfill_keeps_a_reaction_decision_without_an_offered_id(tmp_path):
    decline = {"kind": "REACTION", "provider_id": "d1", "fallback": False,
               "chosen": {"selection": "DECLINE", "option_ids": [], "spend": 0},
               "built_in_pick": {"selection": "USE", "option_ids": ["x"], "spend": 0},
               "decision_menu": {"A": "Use Shield", "B": "Decline"},
               "decision": {"choice": "B", "probabilities": {"A": 0.1, "B": 0.9}}}
    rebuilt = backfill_row("m1", decline)
    assert rebuilt["label"] == "B"
    assert rebuilt["teacher_label"] is None
    assert rebuilt["options"] == {"A": "Use Shield", "B": "Decline"}


def test_backfill_preserves_chosen_and_built_in_pick(tmp_path):
    # The teacher letter is normally unavailable for a saved TURN row (the
    # built-in pick is an action id, not a letter in the D1 menu), but the
    # exact executed answer and the built-in's raw pick must still survive
    # backfill for training that does not need the letter translation.
    turn = {"kind": "TURN", "provider_id": "d1", "fallback": False, "decision_id": "d9",
            "chosen": ["move_1", "attack_2"], "built_in_pick": "attack_2",
            "decision_menu": {"A": "Move", "B": "Attack"},
            "decision": {"choice": "B", "probabilities": {"A": 0.2, "B": 0.8}}}
    rebuilt = backfill_row("m1", turn)
    assert rebuilt["chosen"] == ["move_1", "attack_2"]
    assert rebuilt["built_in_pick"] == "attack_2"
    # label is the model's own saved letter reply, resolved normally.
    assert rebuilt["label"] == "B"
    # teacher_label stays null: "attack_2" is an action id, not among the
    # saved menu's letter keys, so no teacher letter exists.
    assert rebuilt["teacher_label"] is None


def test_export_skips_a_backfilled_row_already_recorded_live(tmp_path):
    decision_records.append(tmp_path, {"match_id": "m1", "decision_id": "d9", "kind": "TURN",
        "provider_id": "d1", "prompt": "P", "options": {"A": "Move", "B": "Attack"}, "answers": {},
        "chosen_id": "B", "built_in_id": "B", "fallback": False, "probabilities": {"A": 0.2, "B": 0.8}})
    match_dir = tmp_path / "Combat" / "Matches" / "m1"
    match_dir.mkdir(parents=True)
    (match_dir / "Agent_Decisions.jsonl").write_text(json.dumps({
        "kind": "TURN", "provider_id": "d1", "fallback": False, "decision_id": "d9",
        "chosen": ["move_1", "attack_2"], "built_in_pick": "attack_2",
        "decision_menu": {"A": "Move", "B": "Attack"},
        "decision": {"choice": "B", "probabilities": {"A": 0.2, "B": 0.8}}}) + "\n", encoding="utf-8")
    out = tmp_path / "rows.jsonl"
    assert export(tmp_path, out, backfill=match_dir.parent) == 1
    [row] = [json.loads(line) for line in out.read_text().splitlines()]
    assert row["source"] == "live"


def test_export_keeps_a_backfilled_row_from_a_different_decision(tmp_path):
    decision_records.append(tmp_path, {"match_id": "m1", "decision_id": "d9", "kind": "TURN",
        "provider_id": "d1", "prompt": "P", "options": {"A": "Move", "B": "Attack"}, "answers": {},
        "chosen_id": "B", "built_in_id": "B", "fallback": False, "probabilities": {"A": 0.2, "B": 0.8}})
    match_dir = tmp_path / "Combat" / "Matches" / "m1"
    match_dir.mkdir(parents=True)
    (match_dir / "Agent_Decisions.jsonl").write_text(json.dumps({
        "kind": "TURN", "provider_id": "d1", "fallback": False, "decision_id": "d10",
        "chosen": ["move_3"], "built_in_pick": "move_3",
        "decision_menu": {"A": "Move", "B": "End turn"},
        "decision": {"choice": "A", "probabilities": {"A": 0.6, "B": 0.4}}}) + "\n", encoding="utf-8")
    out = tmp_path / "rows.jsonl"
    assert export(tmp_path, out, backfill=match_dir.parent) == 2
    sources = {json.loads(line)["source"] for line in out.read_text().splitlines()}
    assert sources == {"live", "backfill"}


def test_compact_export_menu_matches_the_prompt_subset(tmp_path):
    data_dir = tmp_path
    combat, table, mid, *_ = fixture(data_dir, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    runner = _runner_with_profile(data_dir, table, FakeProvider(attack=True), "compact")
    runner.set_seat(mid, FOE, "MODEL", "fake")
    assert runner.drive(mid, max_steps=1) == 1
    [record] = _records(data_dir)
    prompt_menu = json.loads(record["prompt"].split("\n", 1)[1])["legal_menu"]
    exported = export(data_dir, data_dir / "rows.jsonl")
    assert exported == 1
    [row] = [json.loads(line) for line in (data_dir / "rows.jsonl").read_text().splitlines()]
    assert set(row["options"]) == set(prompt_menu) == set(record["answers"])
    assert row["chosen"] == record["chosen"]
