"""Fresh imports and single-copy replay of a saved synthetic fight."""
from copy import deepcopy
import subprocess
import sys

from combat.gate2_runtime_models import ActionIntent, MatchState, Position, TerminalResult
from combat.gate3_reducer import GATE3_CONDITION_KEY, canonical_state_document, canonical_state_sha256
from combat.gate3_storage import Gate3MatchStore, Gate3Persistence
from tests.auto_worker1_support import act, fight, settle


def test_fresh_module_imports():
    for name in ("combat.gate3_reducer", "combat.effect_harm", "combat.ext"):
        result = subprocess.run([sys.executable, "-c", f"import {name}"], capture_output=True, text=True)
        assert result.returncode == 0, f"{name}: {result.stderr}"


def _difference(expected, actual, path="$"):
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() | actual.keys()):
            child = f"{path}.{key}"
            if key not in expected or key not in actual:
                return child
            if expected[key] != actual[key]:
                return _difference(expected[key], actual[key], child)
    if isinstance(expected, list) and isinstance(actual, list):
        for i, (want, got) in enumerate(zip(expected, actual)):
            if want != got:
                return _difference(want, got, f"{path}[{i}]")
        if len(expected) != len(actual):
            return f"{path}[{min(len(expected), len(actual))}]"
    return path


def _assert_same(expected, actual, stage):
    assert expected == actual, f"{stage}: first differing key path {_difference(expected, actual)}"


def test_saved_fight_replay_owns_one_state_copy(tmp_path, monkeypatch):
    combat, table, match_id = fight(
        tmp_path, prepare_target="SELF",
        prepare=[
            {"type": "condition", "condition": "no_dash", "applies_to": "self", "duration": "until_removed",
             "condition_data": {"rule": {"condition_immunities": ["exhaustion"]}}},
            {"type": "zone"},
        ],
        prepare_zone_spec={"name": "Sand patch", "shape": "sphere", "size_ft": 5, "centered_on_self": True,
                           "terrain": ["deep sand terrain"], "duration": {"kind": "one_minute"}},
    )
    settle(lambda answers: act(table, match_id, "Prepare", answers))
    view = table.state(match_id)
    menu = view["menu"]
    engine = combat._load_session(match_id).engine
    move = next(c for c in engine.legal_candidates() if c.kind == "MOVE" and c.destination == Position(x=3, y=7))
    settle(lambda answers: table.act(match_id, move.candidate_id, menu["decision_id"], menu["state_version"],
                                      view["last_sequence"], answers))
    settle(lambda answers: act(table, match_id, "end", answers))

    persistence = Gate3Persistence(combat.source_root, tmp_path)
    store = Gate3MatchStore(tmp_path, match_id)
    read_journal = Gate3MatchStore.read_journal
    records, trailing = store.read_journal()
    assert not trailing
    expected_records = deepcopy(records)
    commits = [record for record in records if record["record_type"] == "COMMIT"]
    assert len(commits) >= 3, f"fixture committed only {len(commits)} actions"
    events = [event for record in commits for event in record["events"]]
    assert any(e["event_type"] == "CONDITION_APPLIED" and e["payload"][GATE3_CONDITION_KEY]["data"]
               for e in events)
    assert any(e["event_type"] == "ZONE_CREATED" for e in events)
    assert any(e["event_type"] == "TARGETS_OBSERVED" or e["payload"].get("observations_after") for e in events)

    _, genesis = persistence._load_lock_genesis(store)
    expected_events = deepcopy([list(genesis.initial_events), *(record["events"] for record in commits)])
    reference = genesis.state
    states = [canonical_state_document(reference)]
    hashes = [genesis.canonical_state_sha256]
    for record in commits:
        reference = persistence.reducer.apply_events(reference, record["events"])
        reference.state_version = record["post_state_version"]
        reference.roll_counter = record["roll_counter_end"]
        if record["terminal_result"] is not None:
            reference.terminal_result = TerminalResult.model_validate(record["terminal_result"])
        states.append(canonical_state_document(reference))
        hashes.append(canonical_state_sha256(reference))
        assert hashes[-1] == record["post_state_sha256"], (
            f"commit {record['record_sequence']}: expected {record['post_state_sha256']}, got {hashes[-1]}"
        )

    copies = 0
    model_copy = MatchState.model_copy

    def count_copy(self, *, update=None, deep=False):
        nonlocal copies
        copies += int(deep)
        return model_copy(self, update=update, deep=deep)

    reads = []

    def capture_read(self):
        records, trailing = read_journal(self)
        reads.append(records)
        return records, trailing

    with monkeypatch.context() as patch:
        patch.setattr(MatchState, "model_copy", count_copy)
        loaded = persistence.load_match(match_id)
        assert copies == 1, f"load_match made {copies} MatchState deep copies (expected 1)"
        _assert_same(expected_records, loaded._records, "after load")
        # The real zone receipt contains a list nested under Any. Detect a shared
        # list even if the next ordinary turn happens not to edit its contents.
        zone_doc = next(e["payload"]["zone"] for r in loaded._records if r["record_type"] == "COMMIT"
                        for e in r["events"] if e["event_type"] == "ZONE_CREATED")
        zone_id = zone_doc["zone_id"]
        assert loaded.engine.state.zones[zone_id].trigger_profile["terrain"] is not zone_doc["trigger_profile"]["terrain"], (
            "load shares a mutable record value at $.payload.zone.trigger_profile.terrain"
        )

        copies = 0
        patch.setattr(Gate3MatchStore, "read_journal", capture_read)
        history = persistence.history_boundaries(match_id)
        assert copies == 1, f"history_boundaries made {copies} MatchState deep copies (expected 1)"

    boundaries = history["boundaries"]
    _assert_same(expected_records, reads[0], "journal used by history")
    _assert_same(expected_records, loaded._records, "loaded records after history")
    _assert_same(expected_events, [row["events"] for row in boundaries], "history events")
    _assert_same([0, *(r["record_sequence"] for r in commits)],
                 [row["record_sequence"] for row in boundaries], "history order")
    _assert_same(["GENESIS", *("COMMIT" for _ in commits)],
                 [row["boundary_kind"] for row in boundaries], "history kinds")
    _assert_same(states, [row["state"] for row in boundaries], "history states")
    _assert_same(hashes, [row["canonical_state_sha256"] for row in boundaries], "history hashes")
    _assert_same(states[-1], canonical_state_document(loaded.engine.state), "loaded state")
    assert history["canonical_final_state_sha256"] == canonical_state_sha256(loaded.engine.state) == hashes[-1]

    end = next(c for c in loaded.engine.legal_candidates() if c.kind == "END_TURN")
    loaded.execute_intent(ActionIntent(
        intent_id="test:after-load", candidate_id=end.candidate_id, decision_id=end.decision_id,
        state_version=end.state_version, actor_id=end.actor_id,
    ))
    assert len(loaded._records) == len(expected_records) + 2 and loaded._records[-1]["record_type"] == "COMMIT"
    _assert_same(expected_records, loaded._records[:len(expected_records)], "after the next commit")
    _assert_same(expected_records, reads[0], "history journal after the next commit")
    _assert_same(expected_events, [row["events"] for row in boundaries], "history events after the next commit")
