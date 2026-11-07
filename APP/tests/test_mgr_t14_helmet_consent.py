"""Helmet Discipline keeps the wearer's choice, including on a computer's turn.

All attacks, prompts, resource payments and cold reloads use the native table.
Only the attacker's primary action is directed; no model/server is contacted.
"""
import pytest

from tests.r1i_service_support import force_ai_candidate
from tests.test_mgr_t14_fitted_armor import ACTOR, fight, support
from tests.test_mgr_t14_armor_defenses import (
    HELMET_POOL, STRIKE, attacker_turn, critical_action, helmet_sheet,
)

CHOICE = "choice:needle.helmet_discipline"


def resolve_strike(tmp_path, monkeypatch, *, wearer_mode, attacker_mode="MANUAL", accept=False):
    combat, table, mid = fight(tmp_path, helmet_sheet(), prepare=critical_action)
    attacker_turn(combat, table, mid)
    combat.set_controller_mode(mid, actor_id=ACTOR, controller_mode=wearer_mode)
    if attacker_mode == "LOCAL_AUTO":
        candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                         if c.source_definition_id == STRIKE)
        force_ai_candidate(combat, mid, support.ATTACKER, candidate.candidate_id)

    # Observe the real transport spec: a human Ask-me probe alone would still
    # pause even if automatic_use were incorrectly enabled for that human.
    human_contexts, controller_contexts = [], []
    render = table._reaction_prompt
    choose = combat.controller.choose_reaction

    def render_prompt(match_id, context, **kwargs):
        if context["reaction_source_id"] == CHOICE:
            human_contexts.append(context)
        return render(match_id, context, **kwargs)

    def choose_reaction(context):
        if context.reaction_source_id == CHOICE:
            controller_contexts.append(context)
        return choose(context)

    monkeypatch.setattr(table, "_reaction_prompt", render_prompt)
    monkeypatch.setattr(combat.controller, "choose_reaction", choose_reaction)

    for _ in range(4):
        before = support._reload(tmp_path, mid)
        before_state = before.state.model_dump(mode="json")
        before_events = len(before.events)

        def answer(prompt):
            assert prompt["context"]["reaction_source_id"] == CHOICE
            # Previewing a question must not spend the pool or roll damage.
            paused = support._reload(tmp_path, mid)
            assert paused.state.model_dump(mode="json") == before_state
            assert paused.state.actors[ACTOR].resources[HELMET_POOL] == 1
            assert not [e for e in paused.events[before_events:]
                        if e.event_type == "DAMAGE_ROLLED"]
            assert prompt["choice"]["allow_decline"]
            assert [o["id"] for o in prompt["choice"]["options"]] == ["protected"]
            for name in ("Helmet Discipline", "Critical test strike",
                         before.state.actors[ACTOR].display_name,
                         before.state.actors[support.ATTACKER].display_name):
                assert name in str(prompt)
            return ["protected"] if accept else None

        prompts = support._commit(combat, table, mid, STRIKE, answer=answer,
                                  auto=attacker_mode == "LOCAL_AUTO")
        cold = support._reload(tmp_path, mid)
        rolls = [e for e in cold.events[before_events:]
                 if e.event_type == "DAMAGE_ROLLED" and e.source_definition_id == STRIKE]
        if rolls:
            return prompts, human_contexts, controller_contexts, cold, rolls[-1]
    raise AssertionError("The seeded attacker missed four attempts")


@pytest.mark.parametrize("wearer_mode,attacker_mode,accept", [
    ("MANUAL", "MANUAL", False),
    ("MANUAL", "MANUAL", True),
    ("MANUAL", "LOCAL_AUTO", False),
    ("MANUAL", "LOCAL_AUTO", True),
    ("SUGGESTED", "MANUAL", False),
    ("MANUAL_AI_BRIDGE", "MANUAL", False),
])
def test_human_helmet_requires_consent_and_decline_preserves_critical(
        tmp_path, monkeypatch, wearer_mode, attacker_mode, accept):
    prompts, contexts, consulted, cold, rolled = resolve_strike(
        tmp_path, monkeypatch, wearer_mode=wearer_mode,
        attacker_mode=attacker_mode, accept=accept)
    assert len(prompts) == 1
    assert contexts
    assert all(c["extension_choice"]["automatic_use"] is False for c in contexts)
    # Manual turns may also ask the controller for a display-only suggestion.
    assert all(not c.extension_choice.automatic_use for c in consulted)
    assert rolled.payload["critical"] is (not accept)
    assert len(rolled.payload["dice"]) == (1 if accept else 2)
    assert cold.state.actors[ACTOR].resources[HELMET_POOL] == int(not accept)
    conversions = [e for e in cold.events if e.event_type == "PASSIVE_TRIGGERED"
                   and e.actor_id == ACTOR and e.payload.get("critical_turned_normal")]
    assert len(conversions) == int(accept)


@pytest.mark.parametrize("wearer_mode", ["LOCAL_AUTO", "API_AUTO"])
def test_automatic_helmet_uses_known_headwear_without_a_human_prompt(
        tmp_path, monkeypatch, wearer_mode):
    prompts, human, automatic, cold, rolled = resolve_strike(
        tmp_path, monkeypatch, wearer_mode=wearer_mode)
    assert not prompts and not human
    assert automatic and all(c.extension_choice.automatic_use for c in automatic)
    assert not rolled.payload["critical"] and len(rolled.payload["dice"]) == 1
    assert cold.state.actors[ACTOR].resources[HELMET_POOL] == 0
    assert sum(bool(e.payload.get("critical_turned_normal")) for e in cold.events) == 1
