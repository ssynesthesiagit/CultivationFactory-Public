"""STALEMATE1RB1: a canceled free setting is not a declaration the owner made.

activation_end also runs when a declaration is canceled (technique_declared reply with cancel=True), so the
restraint used to record ai_restraint_setting:* for a Set-the-Workpiece the owner never stored. The AI then scored
that row as repeated (-10000) for the rest of the turn. The cancel must leave no history, and the row must be
offered again as a fresh declaration. Without the fix, the first assertion on the flag fails.

Synthetic sheets only; network access is denied and no model or embedding server is used.
"""
import socket
from types import SimpleNamespace

import pytest

from combat import ext as ext_module
from combat import menu_rank
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from tests.ai_tiers_native_support import fight

TALENTS = [
    "tianxia.talent.blacksmith.quench_against_the_grain",
    "tianxia.talent.blacksmith.steady_hammer_breathing",
]
SETTING = "Set current workpiece"
FLAG_PREFIX = "ai_restraint_setting:"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(menu_rank, "_CLIENT", SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **kw: None))

    def denied(*a, **kw):
        raise AssertionError("No live socket or model in setting regressions")
    monkeypatch.setattr(socket.socket, "connect", denied)


def _setting_row(context, name=f"{SETTING}: a carried item"):
    return next(c for c in context.legal_candidates if c.display_name == name)


def test_canceled_setting_leaves_no_history_and_is_offered_again(tmp_path, monkeypatch):
    _original_run_strict = ext_module.run_strict
    combat, _mid, session = fight(tmp_path, talents=TALENTS, maximum_rounds=3,
                                  arena_id="battlefield:factory_pillar_arena")
    engine = session.engine
    actor_id = engine.state.current_actor_id
    policy, _ = combat.policies.for_actor(actor_id)
    setting = _setting_row(build_decision_context(engine, policy, for_ai=True))
    canceled_source = setting.source_definition_id

    def cancel_this_declaration(point, *args, **kwargs):
        # The same seam a real interception source uses: a declared activation that is then canceled.
        if point == "technique_declared" and args[2].source_definition_id == canceled_source:
            return [{"source_id": "fixture:cancel_declaration", "label": "Declaration canceled",
                     "cancel": True, "spend_activation": False}]
        return _original_run_strict(point, *args, **kwargs)

    monkeypatch.setattr(ext_module, "run_strict", cancel_this_declaration)
    engine.execute_intent(ActionIntent(
        intent_id="test:canceled-setting", decision_id=setting.decision_id, candidate_id=setting.candidate_id,
        state_version=setting.state_version, actor_id=setting.actor_id, target_ids=setting.target_ids,
        destination=setting.destination))
    monkeypatch.setattr(ext_module, "run_strict", _original_run_strict)

    assert engine.state.current_actor_id == actor_id
    flags = {k: v for k, v in engine.state.actors[actor_id].turn_flags.items() if k.startswith(FLAG_PREFIX)}
    assert not flags, f"a canceled declaration was recorded as the owner's history: {flags}"

    ai_context = build_decision_context(engine, policy, for_ai=True)
    offered = _setting_row(ai_context)
    assert not offered.metadata.get("ai_repeated_setting"), "a canceled declaration was penalized on re-offer"
    scores = {s.candidate_id: s.total for s in
              LocalDeterministicController().choose_primary_action(ai_context).record.scored_alternatives}
    end_turn = next(c for c in ai_context.legal_candidates if c.kind == "END_TURN")
    assert scores.get(offered.candidate_id, 0) > scores[end_turn.candidate_id]



def test_stored_setting_records_history_and_leaves_no_activation_mark(tmp_path):
    """A stored free declaration records its history, and the engine's activation mark is cleared afterwards.

    The mark (gate2_engine._activation_stored_intent) is only meant to be visible while activation_end hooks run.
    Without the reset after the hooks, it keeps the finished intent id and a later hook could mistake it for the
    current declaration. Without the fix this test fails at the mark assertion.
    """
    combat, _mid, session = fight(tmp_path, talents=TALENTS, maximum_rounds=3,
                                  arena_id="battlefield:factory_pillar_arena")
    engine = session.engine
    actor_id = engine.state.current_actor_id
    policy, _ = combat.policies.for_actor(actor_id)
    setting = _setting_row(build_decision_context(engine, policy, for_ai=True))
    engine.execute_intent(ActionIntent(
        intent_id="test:stored-setting", decision_id=setting.decision_id, candidate_id=setting.candidate_id,
        state_version=setting.state_version, actor_id=setting.actor_id, target_ids=setting.target_ids,
        destination=setting.destination))
    flags = {k: v for k, v in engine.state.actors[actor_id].turn_flags.items() if k.startswith(FLAG_PREFIX)}
    assert flags and all(v == 1 for v in flags.values()), "a stored declaration was not recorded as history"
    assert engine._activation_stored_intent is None, "the activation mark outlived its activation"
