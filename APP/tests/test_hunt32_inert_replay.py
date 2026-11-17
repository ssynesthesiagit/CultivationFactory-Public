"""Bounded byte comparison of AI continuations from an immutable prior saved fight.

Compare every decision, event, roll and final state with these two new plug-ins
enabled versus absent. The fixture itself is never rewritten. This proves the
sample's inertness, not byte equality for every historical fight.
"""
import json

from combat import ext
from combat.gate2_runtime_models import CombatEvent, MatchState, RollRecord
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate4_policy import PolicyLibrary
from tests.h1_support import ROOT


def _capture():
    fixture = json.loads((ROOT / "tests/fixtures/lock6_prior_save.json").read_text())
    genesis = json.loads(fixture["files"]["GenesisState.json"])
    state = MatchState.model_validate(genesis["state"])
    engine = Gate4ControllerEngine(ROOT, match_seed=state.match_seed, maximum_rounds=state.maximum_rounds)
    engine.state = state
    engine.events = [CombatEvent.model_validate(e) for e in genesis["initial_events"]]
    engine.rolls = [RollRecord.model_validate(r) for r in genesis["initial_rolls"]]
    engine.roller.counter = state.roll_counter
    engine._transaction_result_version = state.state_version
    engine._commanded_cui_this_turn = genesis["commanded_cui_this_turn"]
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
    decisions = []
    for _ in range(12):
        if engine.state.terminal_result is not None:
            break
        policy, _ = policies.for_actor(engine.state.current_actor_id)
        context = build_decision_context(engine, policy, for_ai=True)
        choice = controller.choose_primary_action(context)
        decisions.append(choice.model_dump(mode="json"))
        engine.execute_intent(choice.intent)
    return json.dumps({"decisions": decisions, "state": engine.state.model_dump(mode="json"),
                       "events": [e.model_dump(mode="json") for e in engine.events],
                       "rolls": [r.model_dump(mode="json") for r in engine.rolls]},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_prior_save_ai_continuation_is_byte_identical_without_owned_abilities(monkeypatch):
    enabled = _capture()
    # Test-only registration isolation; no engine/core class or function is patched.
    for point, callbacks in list(ext._HOOKS.items()):
        monkeypatch.setitem(ext._HOOKS, point, [f for f in callbacks if f.__module__ not in
                                              {"combat.ext.space_prison", "combat.ext.borrowed_second",
                                               "combat.ext.qi_path"}])
    from tests.replay_assertions import assert_replay_equal
    assert_replay_equal(_capture(), enabled)
