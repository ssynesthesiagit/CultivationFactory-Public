"""Offline runner records bind each ranked reply to its own offered frame."""
import json

import pytest

from agent_seats.choices import decision_payload
from tests.test_agent_seats import runner_for
from tests.test_hunt5_player_choices import fixture, FOE
from tests.test_seat_choices import configure
from tests.test_seat_compact import large_fight
from tools.seat_records_export import export


@pytest.mark.parametrize("profile", ["choices", "d1", "compact", "full"])
def test_cross_page_active_then_end_retains_truthful_training_frames(tmp_path, monkeypatch, profile):
    monkeypatch.setenv("CF_EMBED_MENU", "1")
    monkeypatch.setenv("FACTORY_SEAT_RECORDS", "1")
    _, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    view, original = large_fight()
    legal = {"hit": original["hit"], "rare": dict(original["hit"], action="Rare attack"),
             "end": original["end"]}
    calls = []

    def model(config, prompt, png):
        index = len(calls)
        if profile in {"choices", "d1"}:
            reply = ("L", "B", "A")[index]
            offered = decision_payload(prompt)["options"]
            assert reply in offered
            used = {"decision": {"choice": reply, "probabilities": {k: int(k == reply) for k in offered}}}
        else:
            reply = ("MORE", '{"plan":["rare"]}', '{"plan":["end"]}')[index]
            used = None
        calls.append((prompt, reply, used))
        return reply, used

    runner, _ = runner_for(tmp_path, table, model, timeout=30, render_png=lambda view: None)
    configure(runner, "choices" if profile == "d1" else profile)
    config = json.loads(runner.registry.path.read_text())
    config["providers"][0]["max_options"] = 3
    runner.registry.path.write_text(json.dumps(config))
    if profile == "d1":
        providers = runner.registry.load()
        providers["fake"] = dict(providers["fake"], kind="d1")
        runner.registry.load = lambda: providers
    answer = runner._decide(mid, FOE, {"provider_id": "fake"}, view, legal, "hit", "", "TURN",
                            ["hit", "rare"], slot_ranked=True, decision_id="plan-1")
    assert answer == {"plan": ["rare", "end"], "fallback": False}, runner.decisions(mid)[-1]
    records = [json.loads(line) for line in (tmp_path / "seat_decisions.jsonl").read_text().splitlines()]
    assert len(records) == len(calls) == 3
    assert len({r["decision_id"] for r in records}) == 3
    assert [r["record_type"] for r in records] == ["navigation", "step", "step"]
    for record, (prompt, reply, used) in zip(records, calls):
        assert record["prompt"] == prompt and record["reply"] == reply
        assert record["plan_decision_id"] == "plan-1"
        assert record["assembled_plan"] == ["rare", "end"]
        assert record["plan_fallback"] is False
        assert record["chosen_id"] in record["answers"]
        assert set(record["options"]) == set(record["answers"])
        assert record["answers"][record["chosen_id"]]["plan"] == record["chosen"]
        assert record["fallback"] is False
        if used:
            assert record["probabilities"] == used["decision"]["probabilities"]
            assert record["probabilities"][record["chosen_id"]] == 1
    assert records[1]["chosen"] == ["rare"]
    assert records[2]["chosen"] == ["end"]
    saved = runner.decisions(mid)[-1]
    assert saved["chosen"] == ["rare", "end"]
    assert saved["decision_records"] == [r["decision_id"] for r in records]
    assert "decision_menu" not in saved and "decision" not in saved
    output = tmp_path / "training.jsonl"
    assert export(tmp_path, output, backfill=table.combat.userdata_root / "Combat" / "Matches") == 3
    exported = [json.loads(line) for line in output.read_text().splitlines()]
    for row, record in zip(exported, records):
        assert row["label"] == record["chosen_id"]
        assert row["state"] == record["prompt"]
        assert row["chosen"] == record["chosen"]
        assert row["plan_decision_id"] == "plan-1"
        assert row["record_type"] == record["record_type"]
        assert row["assembled_plan"] == ["rare", "end"]
