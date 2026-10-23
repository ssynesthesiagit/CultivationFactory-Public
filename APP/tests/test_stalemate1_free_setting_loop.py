"""STALEMATE1: the built-in AI must act rather than repeat free setup forever.

Calibration 2026-10-21 (main 6475f0cb): Mei Jiang vs Hua Muruo was 0 damage on all ten seeds and never reached a
terminal result in 900 decisions, all in round 1. The cause is not the fight: "Set current workpiece" is a
``setting_only`` action with no economy, so the engine offers it again immediately, and its candidate keeps
scoring above End turn (a primary-combatant target priority on its self target). The AI alternated "a carried
item" and "clear item selection" forever.

This test drives the same AI-vs-AI loop the Tricky bench uses (real CombatService match, native decisions) with a
synthetic Blacksmith sheet, so it needs no owner data or Git history. It fails without the restraint in
combat/ext/ai_restraint.py (120 decisions, round 1, no terminal result) and passes with it.
"""
import socket
from types import SimpleNamespace

import pytest

from combat import menu_rank
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.ai_tiers_native_support import fight

TALENTS = [
    "tianxia.talent.blacksmith.quench_against_the_grain",
    "tianxia.talent.blacksmith.steady_hammer_breathing",
]
SETTING = "Set current workpiece"
FLAG_PREFIX = "ai_restraint_setting:"  # per declaration; see combat/ext/ai_restraint.py


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(menu_rank, "_CLIENT", SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **kw: None))
    def denied(*a, **kw):
        raise AssertionError("No live socket or model in setting regressions")
    monkeypatch.setattr(socket.socket, "connect", denied)


def drive(combat, session, *, max_steps=120):
    engine = session.engine
    controller = LocalDeterministicController()

    def reaction(request):
        policy, _ = combat.policies.for_actor(request["reactor_id"])
        choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
        return choice.decision, choice.record.model_dump(mode="json")

    engine.set_reaction_provider(reaction)
    choices, steps = [], 0
    while engine.state.terminal_result is None and steps < max_steps:
        policy, _ = combat.policies.for_actor(engine.state.current_actor_id)
        context = build_decision_context(engine, policy, for_ai=True)
        choice = controller.choose_primary_action(context)
        picked = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
        choices.append((engine.state.round_number, engine.state.current_actor_id, picked.display_name))
        engine.execute_intent(choice.intent)
        steps += 1
    return steps, choices


def test_ai_ends_its_turn_without_repeating_free_setup(tmp_path):
    combat, _mid, session = fight(tmp_path, talents=TALENTS, maximum_rounds=3,
                                  arena_id="battlefield:factory_pillar_arena")
    steps, choices = drive(combat, session)
    engine = session.engine
    assert engine.state.terminal_result is not None, (
        f"no terminal result after {steps} decisions, still round {engine.state.round_number}: "
        f"{[name for _, _, name in choices[-6:]]}")
    assert steps < 60, f"a capped 3-round duel took {steps} decisions"
    settings = [(round_number, actor) for round_number, actor, name in choices if name.startswith(SETTING)]
    # Each declaration can be useful again after acting/moving, not merely
    # once per turn. Check each uninterrupted setup segment, not an aggregate
    # that could hide a looping turn behind turns with no settings.
    seen = set()
    for round_number, actor, name in choices:
        if not name.startswith(SETTING):
            seen.clear()
            continue
        key = (round_number, actor, name)
        assert key not in seen, f"repeated setup without acting: {choices}"
        seen.add(key)
    assert settings, "the AI never made a free setting declaration; this test no longer covers the loop"


def test_the_restraint_is_ai_only(tmp_path):
    """Both menus retain all choices; only the AI devalues repeated setup."""
    combat, _mid, session = fight(tmp_path, talents=TALENTS, maximum_rounds=3,
                                  arena_id="battlefield:factory_pillar_arena")
    engine = session.engine
    actor_id = engine.state.current_actor_id
    policy, _ = combat.policies.for_actor(actor_id)
    context = build_decision_context(engine, policy, for_ai=True)
    setting = next(c for c in context.legal_candidates if c.display_name.startswith(SETTING))
    engine.execute_intent(ActionIntent(
        intent_id="test:free-setting", decision_id=setting.decision_id, candidate_id=setting.candidate_id,
        state_version=setting.state_version, actor_id=setting.actor_id, target_ids=setting.target_ids,
        destination=setting.destination))
    assert engine.state.current_actor_id == actor_id, "the free setting must not end the turn"
    ai_context = build_decision_context(engine, policy, for_ai=True)
    person_context = build_decision_context(engine, policy, for_ai=False)
    ai_settings = {c.source_definition_id for c in ai_context.legal_candidates if c.display_name.startswith(SETTING)}
    person_settings = {c.source_definition_id for c in person_context.legal_candidates if c.display_name.startswith(SETTING)
                       and not engine.action_catalog[c.source_definition_id].parameters.get("player_only")}
    assert ai_settings == person_settings, "AI/model seats lost legal setting choices"
    repeated = next(c for c in ai_context.legal_candidates if c.source_definition_id == setting.source_definition_id)
    assert repeated.metadata.get("ai_repeated_setting") == 1
    controller = LocalDeterministicController()
    scores = {s.candidate_id: s.total for s in controller.choose_primary_action(ai_context).record.scored_alternatives}
    end_turn = next(c for c in ai_context.legal_candidates if c.kind == "END_TURN")
    assert scores[repeated.candidate_id] < scores[end_turn.candidate_id]
    assert not any(c.metadata.get("ai_repeated_setting") for c in person_context.legal_candidates)


def test_ranking_a_persons_menu_keeps_its_setting_rows_scored(tmp_path):
    """menu_rank scores a person's menu from CombatService.menu_ranking_context. That context is the AI's
    projection, so the built-in AI's restraint used to run inside it: once the person had declared one
    setting, their own remaining setting rows vanished from the ranking context, got no score, and sorted
    below End turn (review 2026-10-21, Fix 1). The restraint applies to an AI decision only."""
    combat, _mid, session = fight(tmp_path, talents=TALENTS, maximum_rounds=3,
                                  arena_id="battlefield:factory_pillar_arena")
    engine = session.engine
    actor_id = engine.state.current_actor_id
    policy, _ = combat.policies.for_actor(actor_id)
    setting = next(c for c in build_decision_context(engine, policy, for_ai=False).legal_candidates
                   if c.display_name == f"{SETTING}: a carried item")
    engine.execute_intent(ActionIntent(
        intent_id="test:free-setting-rank", decision_id=setting.decision_id, candidate_id=setting.candidate_id,
        state_version=setting.state_version, actor_id=setting.actor_id, target_ids=setting.target_ids,
        destination=setting.destination))
    assert engine.state.current_actor_id == actor_id, "the free setting must not end the turn"
    person = build_decision_context(engine, policy, for_ai=False)
    remaining = {c.candidate_id for c in person.legal_candidates if c.display_name.startswith(SETTING)}
    end_turn = next(c for c in person.legal_candidates if c.kind == "END_TURN")
    assert remaining, "the person's own menu lost the rest of its settings"
    ranking = combat.menu_ranking_context(session)
    assert remaining <= {c.candidate_id for c in ranking.legal_candidates}, (
        "the ranking context for a person's menu dropped their own setting rows")
    known = {a.entity_id for a in ranking.actors} | {actor_id}
    scores = menu_rank.native_scores(combat, engine, known, session=session,
                                     candidate_ids=remaining | {end_turn.candidate_id})
    assert remaining | {end_turn.candidate_id} <= set(scores), (
        f"unscored rows: {remaining | {end_turn.candidate_id} - set(scores)}")
    assert min(scores[cid] for cid in remaining) > scores[end_turn.candidate_id], (
        "the person's setting rows rank below End turn")


def test_free_setting_history_survives_a_table_commit_and_clears_next_turn(tmp_path):
    """Per-declaration integer history survives commit/reload, but not the next turn."""
    combat, mid, _session = fight(tmp_path, talents=TALENTS, maximum_rounds=4)
    table = TabletopService(combat, tmp_path)
    menu = table.state(mid)["menu"]
    actor_id = menu["actor_id"]
    setting = next(option["candidate_id"] for group in menu["actions"] if SETTING in group["label"]
                   for option in group["options"]
                   if (option.get("label") or "").startswith(f"{SETTING}: a carried item"))
    committed = table.act(mid, setting, menu["decision_id"], menu["state_version"], 0, [])
    assert committed["status"] == "COMMITTED", committed
    cold = CombatService(combat.source_root, combat.userdata_root)._load_session(mid).engine
    reloaded = cold.state
    assert reloaded.current_actor_id == actor_id, "the free setting must not end the turn"
    flags = {k: v for k, v in reloaded.actors[actor_id].turn_flags.items() if k.startswith(FLAG_PREFIX)}
    assert flags and all(type(v) is int and v == 1 for v in flags.values()), (
        "the per-declaration history did not survive the table commit and cold reload")
    policy, _ = combat.policies.for_actor(actor_id)
    repeated = next(c for c in build_decision_context(cold, policy, for_ai=True).legal_candidates
                    if c.display_name == f"{SETTING}: a carried item")
    assert repeated.metadata.get("ai_repeated_setting") == 1
    for _ in range(8):
        menu = table.state(mid)["menu"]
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or engine.state.current_actor_id == actor_id:
            break
    engine = CombatService(combat.source_root, combat.userdata_root)._load_session(mid).engine
    assert engine.state.terminal_result is None, "the fixture ended before the owner's next turn"
    assert engine.state.current_actor_id == actor_id, "the round did not come back to the owner"
    assert not any(k.startswith(FLAG_PREFIX) for k in engine.state.actors[actor_id].turn_flags), (
        "the declaration history outlived its turn")
