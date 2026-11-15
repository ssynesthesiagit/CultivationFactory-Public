"""Compare baseline AI transactions without normalizing any events, rolls or state.

Usage: python -m tests.hunt36_replay_compare MATCH PREPARE,SEQUENCES
Outputs differing JSON paths as compact evidence; each transaction starts from
its recorded baseline prestate, rather than accumulating earlier differences.
"""
import hashlib
import json
import sys
from pathlib import Path

from combat.gate2_runtime_models import ActionIntent, CombatEvent, MatchState, RollRecord
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_log1_saved_ai_replay import ROOT, canonical_bytes


def differences(old, new, path=""):
    if type(old) is not type(new):
        return [{"path": path, "old": old, "new": new}]
    if isinstance(old, dict):
        return [diff for key in sorted(old.keys() | new.keys())
                for diff in differences(old.get(key), new.get(key), f"{path}/{key}")]
    if isinstance(old, list):
        if len(old) != len(new):
            return [{"path": path, "old": old, "new": new}]
        return [diff for i, (a, b) in enumerate(zip(old, new)) for diff in differences(a, b, f"{path}/{i}")]
    return [] if old == new else [{"path": path, "old": old, "new": new}]


def compare(match: Path, sequences: list[int]) -> list[dict]:
    assert match.is_relative_to(Path("/var/tmp/auto-audit/wt-fix36/.fix36f-replay"))
    load = lambda name: json.loads((match / name).read_text())
    rows = list(map(json.loads, (match / "Journal.ndjson").read_text().splitlines()))
    genesis = load("GenesisState.json")
    results = []
    for sequence in sequences:
        prepare = next(r for r in rows if r["record_sequence"] == sequence)
        commit = next(r for r in rows if r["record_sequence"] == sequence + 1)
        state = MatchState.model_validate(genesis["state"])
        events = [CombatEvent.model_validate(e) for e in genesis["initial_events"]]
        rolls = [RollRecord.model_validate(r) for r in genesis["initial_rolls"]]
        commanded = genesis["commanded_cui_this_turn"]
        for prior in rows:
            if prior["record_sequence"] >= sequence:
                break
            if prior["record_type"] != "COMMIT":
                continue
            state = Gate3EventReducer().apply_events(state, prior["events"])
            state.state_version, state.roll_counter = prior["post_state_version"], prior["roll_counter_end"]
            events.extend(CombatEvent.model_validate(e) for e in prior["events"])
            rolls.extend(RollRecord.model_validate(r) for r in prior["rolls"])
            control = prior["events"][-1]["payload"].get("gate3_runtime_control_after") if prior["events"] else None
            if control:
                commanded = control["commanded_cui_this_turn"]
        expected = Gate3EventReducer().apply_events(state.model_copy(deep=True), commit["events"])
        expected.state_version, expected.roll_counter = commit["post_state_version"], commit["roll_counter_end"]
        engine = Gate4ControllerEngine(ROOT, match_seed=state.match_seed, maximum_rounds=state.maximum_rounds,
            typed_bundles=load("Typed_Character_Bundles.json"), battlefield=load("Arena_Battlefield.json"))
        engine.state, engine.events, engine.rolls = state, events, rolls
        engine.roller.counter = state.roll_counter
        engine._transaction_result_version = state.state_version
        engine._commanded_cui_this_turn = commanded
        engine.typed_control_modes = load("FactoryIntegration.json")["participant_control_modes"]
        start, roll_start = len(events), len(rolls)
        engine.execute_intent(ActionIntent.model_validate(prepare["intent"]))
        actual = {"events": list(enrich_committed_events(engine.events[start:], post_engine=engine)),
            "rolls": [r.model_dump(mode="json") for r in engine.rolls[roll_start:]], "state": engine.state.model_dump(mode="json")}
        old = {"events": commit["events"], "rolls": commit["rolls"], "state": expected.model_dump(mode="json")}
        results.append({"prepare": sequence, "diffs": differences(old, actual),
            "baseline_sha256": hashlib.sha256(canonical_bytes(old)).hexdigest(),
            "final_sha256": hashlib.sha256(canonical_bytes(actual)).hexdigest()})
    return results


if __name__ == "__main__":
    print(json.dumps(compare(Path(sys.argv[1]).resolve(), list(map(int, sys.argv[2].split(",")))), indent=2))
