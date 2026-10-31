"""SOL56: printed reaction economy and chains through saved Tabletop actions.

Natural dice, real compiled talents, transactional Ask-me answers, commit,
fresh-load verification and mechanical replay. AI primary-action transport
uses the supported controller interface; its reaction controller is unchanged.
"""
import pytest

from combat import typed_reactions
from tests.sol56_support import IDS, run

ARROW = "TAL_BARRAGE_ARROW_CATCHING_REVERSAL"
SHOT = "TAL_BARRAGE_INTERCEPTING_SHOT"
COUNTER = "TAL_LIGHTNING_CHARGED_COUNTERMEASURE"


def checked(result):
    assert "error" not in result, result.get("error")
    assert result["reload_equal"]
    assert result["verification"]["status"] == result["replay"]["status"] == "PASS"
    return result["events"]


def resolved(events, source, actor=None):
    return [e for e in events if e["event_type"] == "REACTION_RESOLVED"
            and e["source_definition_id"] == source and (actor is None or e["actor_id"] == actor)]


def eligible(result, step, reactor, subject):
    actors = next(s["actors"] for s in result["mechanics_states"] if s["step"] == step)
    assert actors[reactor]["reaction_available"]
    assert actors[reactor]["resources"]["resource:core.qi"] >= 1
    assert any(c["condition_id"].startswith("condition:typed.mark.charged.")
               for c in actors[subject]["conditions"].values())


@pytest.mark.parametrize("auto", [False, True])
def test_reaction_follow_up_cannot_spend_an_already_spent_reaction(tmp_path, monkeypatch, auto):
    if auto:
        monkeypatch.setenv("H56_FOCUSED_FORCE_TRIGGER", "1")
    result = run(tmp_path, "arrow", auto)
    events = checked(result)
    assert resolved(events, SHOT, IDS[0])
    assert not resolved(events, ARROW, IDS[0])
    assert not any(p["reaction"] == "Arrow-Catching Reversal" for p in result["prompts"])


@pytest.mark.parametrize("auto", [False, True])
def test_a_third_creature_can_answer_a_reaction_to_a_reaction(tmp_path, monkeypatch, auto):
    if auto:
        monkeypatch.setenv("H56_FOCUSED_FORCE_TRIGGER", "1")
    result = run(tmp_path, "chain", auto)
    events = checked(result)
    assert resolved(events, COUNTER, IDS[2])
    assert resolved(events, COUNTER, IDS[1])
    if auto:
        assert not any(p['context']['reactor_id'] == IDS[2] for p in result['prompts'])
    assert any(p["context"]["reactor_id"] == IDS[1] and p["reaction"] == "Charged Countermeasure"
               and "Attacker used Charged Countermeasure" in p.get("moment", "")
               for p in result["prompts"]), result["prompts"]
    # Within one chain nobody gets to spend the same Reaction twice.
    windows = [e for e in events if e["event_type"] == "REACTION_WINDOW_OPENED"
               and e["source_definition_id"] == COUNTER]
    assert windows


@pytest.mark.parametrize("auto", [False, True])
def test_manual_factory_opportunity_attack_can_be_answered(tmp_path, monkeypatch, auto):
    if auto:
        monkeypatch.setenv("H56_FOCUSED_FORCE_TRIGGER", "1")
    result = run(tmp_path, "chain_opportunity", auto)
    events = checked(result)
    trigger = next(p for p in result["prompts"] if p["reaction"] == "Opportunity Attack" and p["reactor"] == "Owner")
    eligible(result, trigger["step"], IDS[2], IDS[0])
    assert resolved(events, COUNTER, IDS[2])
    if auto:
        assert not any(p['context']['reactor_id'] == IDS[2] for p in result['prompts'])
    else:
        assert any(p["reaction"] == "Charged Countermeasure" for p in result["prompts"])


def test_one_manual_player_can_answer_an_ai_opportunity_attack_on_their_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("H56_FOCUSED_SEED", "F-chain-0-1-0")
    result = run(tmp_path, "chain_player")
    events = checked(result)
    counter_prompt = next(p for p in result['prompts'] if p['context']['reactor_id'] == IDS[0] and p['reaction'] == 'Charged Countermeasure')
    eligible(result, counter_prompt['step'], IDS[0], IDS[2])
    assert resolved(events, "system:combat.opportunity_attack", IDS[2])
    assert any(p["context"]["reactor_id"] == IDS[0] and p["reaction"] == "Charged Countermeasure"
               for p in result["prompts"])


@pytest.mark.parametrize("use", [True, False], ids=["use", "decline"])
def test_bloodletting_on_saved_factory_opportunity_hit(tmp_path, monkeypatch, use):
    """Any melee hit qualifies, including a Reaction; no Countermeasure owner required."""
    # Natural dice: Owner hits, then Attacker fails the Bloodletting save.
    monkeypatch.setenv("H56_FOCUSED_SEED", "SOL56-BLOOD-OPPORTUNITY-5")
    result = run(tmp_path, "blood_opportunity", use=use)
    events = checked(result)
    hit = [e for e in events if e["event_type"] == "ATTACK_ROLLED" and e["actor_id"] == IDS[0]]
    assert len(hit) == 1 and hit[0]["payload"]["provisional_hit"]
    prompts = [p for p in result["prompts"] if p["reaction"] == "Bloodletting Strike"]
    assert len(prompts) == 1, result["prompts"]
    prompt = prompts[0]
    assert prompt["context"]["reactor_id"] == IDS[0]
    assert "Attacker" in prompt["moment"]
    assert "Opportunity Attack" in prompt["moment"]
    assert any(s["step"] == prompt["step"] and s["status"] == "COMMITTED" for s in result["steps"])
    assert resolved(events, "system:combat.opportunity_attack", IDS[0])
    before = next(s["actors"] for s in result["mechanics_states"] if s["step"] == prompt["step"])
    after = result["final"]["actors"]
    assert before[IDS[0]]["resources"]["resource:core.qi"] - after[IDS[0]]["resources"]["resource:core.qi"] == int(use)
    paid = [e for e in events if e["event_type"] == "RESOURCE_SPENT"
            and e["source_definition_id"] == "tianxia.talent.blood.bloodletting_strike"]
    assert len(paid) == int(use)
    if use:
        assert paid[0]["payload"]["amount"] == 1
    damage = [e for e in events if e["event_type"] == "DAMAGE_COMMITTED"
              and e["actor_id"] == IDS[0] and IDS[2] in e["target_ids"]]
    necrotic = [e for e in damage if e["payload"].get("damage_type") == "NECROTIC"]
    assert len(necrotic) == int(use)
    if use:
        assert 1 <= necrotic[0]["payload"]["hp_damage"] <= 6
    saves = [e for e in events if e["event_type"] == "SAVE_ROLLED" and e["actor_id"] == IDS[2]]
    assert len(saves) == int(use)
    bleeding = [c for c in after[IDS[2]]["conditions"].values()
                if c["condition_id"] == "condition:typed.bloodletting"]
    assert len(bleeding) == int(use)
    if use:
        assert not saves[0]["payload"]["success"]
        assert bleeding[0]["source_actor_id"] == IDS[0]
        assert bleeding[0]["data"]["burn"] == 4
        assert bleeding[0]["expires_on"] == "END_OF_HOLDER_NEXT_TURN"
    # Skipping the rider consumes fewer dice, so Ally's later opportunity roll
    # can also hit. Account for all damage without misattributing it to Owner.
    total_damage = sum(e["payload"]["hp_damage"] for e in events
                       if e["event_type"] == "DAMAGE_COMMITTED" and IDS[2] in e["target_ids"])
    assert before[IDS[2]]["current_hp"] - after[IDS[2]]["current_hp"] == total_damage
    assert any(e["payload"]["damage_type"] == "SLASHING" and e["payload"]["hp_damage"] > 0 for e in damage)
    assert after[IDS[2]]["current_hp"] < before[IDS[2]]["current_hp"]  # base hit survives either choice
    assert not after[IDS[0]]["reaction_available"]


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_available_compiled_follow_up_asks_and_only_use_spends(selection):
    """General dispatch contract with a real compiled row; no simulated trigger claim."""
    from combat.factory_compiler import compile_character
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision
    from tests.h1_support import ROOT, sheet

    bundle = compile_character(sheet([ARROW]), actor_id=IDS[0], reaction_plan={"ask": True})
    foe = compile_character(sheet([]), actor_id=IDS[2])
    engine = Gate4ControllerEngine(ROOT, match_seed="SOL56-FOLLOW-UP", typed_bundles=(bundle, foe),
        roster_setup={"primary_actor_ids": [IDS[0], IDS[2]], "team_by_actor": {IDS[0]: "team:a", IDS[2]: "team:b"},
                      "starting_positions": {IDS[0]: {"x": 1, "y": 1}, IDS[2]: {"x": 2, "y": 1}}})
    actor = engine.state.actors[IDS[0]]
    row = next(r for r in engine.typed_reaction_rows[IDS[0]] if r["feature_id"] == ARROW)
    assert row["kind"] == "own_ability" and row.get("ask") and not row["free"]
    actor.reaction_available = False
    assert not typed_reactions._can_trigger(engine, actor, row)
    actor.reaction_available = True
    assert typed_reactions._can_trigger(engine, actor, row)
    engine.typed_ask_reactors = (IDS[0],)
    engine._active_intent = ActionIntent(intent_id="sol56", decision_id="sol56", candidate_id="sol56",
                                        actor_id=IDS[0], state_version=engine.state.state_version)
    asked = []

    def provider(request):
        from combat.reaction_trigger import contextual_request
        asked.append(contextual_request(engine, request))
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
            reaction_source_id=request["reaction_source_id"], selection=selection), None

    engine.set_reaction_provider(provider)
    typed_reactions.on_own_event(engine, actor, None, "own_ability")
    assert len(asked) == 1
    assert asked[0]["choice_trigger"]["action_name"] == "Intercepting Shot"
    assert actor.reaction_available == (selection == "DECLINE")


def test_dispatch_depth_is_bounded_and_restored(monkeypatch):
    from types import SimpleNamespace

    engine = SimpleNamespace()
    actor = SimpleNamespace(entity_id="test:actor")
    visits = []

    def refund_chain(engine, actor, kind):
        visits.append(engine._typed_reaction_used_depth)
        typed_reactions.publish_reaction_used(engine, actor, {"feature_id": f"test:{len(visits)}"})

    monkeypatch.setattr(typed_reactions, "on_creature_event", refund_chain)
    typed_reactions.publish_reaction_used(engine, actor, {"feature_id": "test:root"})
    assert visits == list(range(1, typed_reactions.MAX_REACTION_USED_DEPTH + 1))
    assert engine._typed_reaction_used_depth == 0
    assert engine._typed_answered_reaction is None


def test_nested_answer_and_penalty_frames_restore_even_when_preview_pauses(monkeypatch):
    from types import SimpleNamespace
    from combat.ext import ControllerPause

    engine = SimpleNamespace()
    outer, inner = SimpleNamespace(entity_id="outer"), SimpleNamespace(entity_id="inner")

    def answer(engine, actor, kind):
        frame = engine._typed_answered_reaction
        if actor is outer:
            typed_reactions.publish_reaction_used(engine, inner, {"feature_id": "inner"})
            assert engine._typed_answered_reaction is frame
            frame["penalty"] = {"actor_id": "outer", "feature_id": "outer"}
        else:
            frame["penalty"] = {"actor_id": "inner", "feature_id": "inner"}

    monkeypatch.setattr(typed_reactions, "on_creature_event", answer)
    typed_reactions.publish_reaction_used(engine, outer, {"feature_id": "outer"})
    assert typed_reactions.reaction_penalty(engine, "outer", "outer")["actor_id"] == "outer"
    assert typed_reactions.reaction_penalty(engine, "inner", "inner")["actor_id"] == "inner"
    assert typed_reactions.reaction_penalty(engine, "outer", "inner") is None

    def same_reaction(engine, actor, kind):
        frame = engine._typed_answered_reaction
        depth = engine._typed_reaction_used_depth
        if depth == 1:
            typed_reactions.publish_reaction_used(engine, actor, {"feature_id": "outer"})
            assert engine._typed_answered_reaction is frame
        frame["penalty"] = {"actor_id": "outer", "feature_id": "outer", "depth": depth}

    monkeypatch.setattr(typed_reactions, "on_creature_event", same_reaction)
    typed_reactions.publish_reaction_used(engine, outer, {"feature_id": "outer"})
    assert typed_reactions.reaction_penalty(engine, "outer", "outer")["depth"] == 1

    def pause(*args):
        raise ControllerPause("preview paused")

    monkeypatch.setattr(typed_reactions, "on_creature_event", pause)
    with pytest.raises(ControllerPause, match="preview paused"):
        typed_reactions.publish_reaction_used(engine, outer, {"feature_id": "outer"})
    assert engine._typed_answered_reaction is None
    assert engine._typed_reaction_used_depth == 0
    assert typed_reactions.reaction_penalty(engine, "outer", "outer") is None
