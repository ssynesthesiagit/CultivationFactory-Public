"""Opt-in re-execution of AI transactions from a task-owned copied fight.

Set LOG1_SAVED_AI_MATCH to a copied match directory and LOG1_AI_PREPARES to
comma-separated PREPARE record sequences. No saved files are written, and no
private fixture is checked into Git. This checks execution of recorded AI
choices, not whether the current controller would select the same choice.
"""
import json
import os
from pathlib import Path

import pytest

from combat.gate2_runtime_models import ActionIntent, CombatEvent, MatchState, RollRecord
from combat.gate3_reducer import Gate3EventReducer, canonical_state_sha256, enrich_committed_events
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@pytest.mark.skipif(not os.environ.get("LOG1_SAVED_AI_MATCH"), reason="requires opt-in copied fight")
def test_saved_ai_transactions_remain_byte_identical():
    match = Path(os.environ["LOG1_SAVED_AI_MATCH"]).resolve()
    # A mistaken opt-in must never point at the live service's state tree.
    assert not match.is_relative_to(Path.home() / ".local/state/cultivation-factory")
    sequences = [int(n) for n in os.environ["LOG1_AI_PREPARES"].split(",")]
    assert sequences
    rows = [json.loads(line) for line in (match / "Journal.ndjson").read_text().splitlines()]
    genesis = json.loads((match / "GenesisState.json").read_text())
    controller = [json.loads(line) for line in (match / "ControllerJournal.ndjson").read_text().splitlines()]
    bundles = json.loads((match / "Typed_Character_Bundles.json").read_text())
    battlefield = json.loads((match / "Arena_Battlefield.json").read_text())
    modes = json.loads((match / "FactoryIntegration.json").read_text())["participant_control_modes"]

    for sequence in sequences:
        prepare = next(r for r in rows if r["record_sequence"] == sequence)
        expected = next(r for r in rows if r["record_sequence"] == sequence + 1)
        assert prepare["record_type"] == "PREPARE" and expected["record_type"] == "COMMIT"
        assert expected["transaction_id"] == prepare["transaction_id"]
        decision = next(r["primary_decision_record"] for r in controller
                        if r.get("intent_id") == prepare["intent"]["intent_id"])
        assert decision["controller_id"] == "controller:local_deterministic.gate4"
        assert decision["selected_candidate_id"] == prepare["intent"]["candidate_id"]
        assert decision["actor_id"] == prepare["intent"]["actor_id"]

        state = MatchState.model_validate(genesis["state"])
        events = [CombatEvent.model_validate(e) for e in genesis["initial_events"]]
        rolls = [RollRecord.model_validate(r) for r in genesis["initial_rolls"]]
        commanded = genesis["commanded_cui_this_turn"]
        for commit in rows:
            if commit["record_sequence"] >= sequence:
                break
            if commit["record_type"] != "COMMIT":
                continue
            state = Gate3EventReducer().apply_events(state, commit["events"])
            state.state_version = commit["post_state_version"]
            state.roll_counter = commit["roll_counter_end"]
            events.extend(CombatEvent.model_validate(e) for e in commit["events"])
            rolls.extend(RollRecord.model_validate(r) for r in commit["rolls"])
            if commit["events"]:
                control = commit["events"][-1]["payload"].get("gate3_runtime_control_after")
                if control:
                    commanded = control["commanded_cui_this_turn"]
        assert canonical_state_sha256(state) == prepare["pre_state_sha256"], sequence
        assert state.roll_counter == prepare["roll_counter_start"]
        expected_state = Gate3EventReducer().apply_events(state.model_copy(deep=True), expected["events"])
        expected_state.state_version = expected["post_state_version"]
        expected_state.roll_counter = expected["roll_counter_end"]
        assert canonical_state_sha256(expected_state) == expected["post_state_sha256"]

        engine = Gate4ControllerEngine(ROOT, match_seed=state.match_seed, maximum_rounds=state.maximum_rounds,
                                      typed_bundles=bundles, battlefield=battlefield)
        engine.state, engine.events, engine.rolls = state, events, rolls
        engine.roller.counter = state.roll_counter
        engine._transaction_result_version = state.state_version
        engine._commanded_cui_this_turn = commanded
        engine.typed_control_modes = dict(modes)
        event_start, roll_start = len(events), len(rolls)
        engine.execute_intent(ActionIntent.model_validate(prepare["intent"]))
        actual_events = list(enrich_committed_events(engine.events[event_start:], post_engine=engine))
        actual_rolls = [r.model_dump(mode="json") for r in engine.rolls[roll_start:]]
        # Include all provenance/runtime fields; do not normalize away a difference.
        from tests.replay_assertions import assert_replay_equal
        assert_replay_equal(canonical_bytes(actual_events), canonical_bytes(expected["events"]), sequence)
        assert_replay_equal(canonical_bytes(actual_rolls), canonical_bytes(expected["rolls"]), sequence)
        assert_replay_equal(canonical_bytes(engine.state.model_dump(mode="json")), canonical_bytes(expected_state.model_dump(mode="json")), sequence)
        assert canonical_state_sha256(engine.state) == expected["post_state_sha256"], sequence
