"""SOL127 batch-review regressions through table commits and cold reloads."""
import pytest

from combat.ext import effect_durations, scoundrel_riders
from combat.gate5_service import CombatService
from combat.typed_executor import bears_mark
from tests import auto11_service_support as S
import test_qiweaving_auto12 as Q
import test_auto43r1f1_smoke_table as M


def test_ordinary_steal_cannot_use_owned_steal_equipment_armor_permission(tmp_path):
    combat, table, mid = S.fight(tmp_path, ["TAL_SCOUNDREL_STEAL", "TAL_SCOUNDREL_MASTER_THIEF",
                                          "TAL_SCOUNDREL_STEAL_EQUIPMENT"], victim_kit=S.ARMORED)
    focus = S.engine(combat, mid).state.actors[S.THIEF].resources[S.FOCUS]
    result, prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=S.VICTIM), answer="nothing")
    assert result["status"] == "COMMITTED"
    offered = next(p["choice"]["options"] for p in prompts
                   if p["context"]["reaction_source_id"].endswith("steal_objects"))
    assert not any(S.ARMOR_KEY in p["id"] for p in offered)
    loaded = CombatService(S.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[S.THIEF].resources[S.FOCUS] == focus
    assert not S.records(loaded.engine, S.ARMOR_KEY)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ai_turn", [False, True], ids=["manual_turn", "ai_turn"])
@pytest.mark.parametrize("accept", [False, True], ids=["decline", "accept"])
def test_blacken_can_protect_its_owner_and_pays_only_on_acceptance(tmp_path, monkeypatch, ai_turn, accept):
    combat, table, mid = M._fire_fight(tmp_path, owner_ask=False, self_target=True)
    bearer = M._veil_and_trace(table, mid)
    # The Trace is on the attacker, legal for either target. Setup is a real table action.
    assert bearer == M.ATTACKER
    before = combat._load_session(mid).engine.state.actors[M.OWNER].current_hp
    if ai_turn:
        result = M._ai_fire(combat, table, mid, monkeypatch, target=M.OWNER)
    else:
        combat.set_controller_mode(mid, actor_id=M.ATTACKER, controller_mode="MANUAL")
        engine = combat._load_session(mid).engine
        candidate = next(c.candidate_id for c in engine.legal_candidates()
                         if "Burn Through" in c.display_name and M.OWNER in c.target_ids)
        state = table.state(mid)
        result = table.act(mid, candidate, state["menu"]["decision_id"], state["menu"]["state_version"],
                           state["last_sequence"])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = M._soot_prompt(result)
    assert prompt and prompt["context"]["reactor_id"] == M.OWNER
    assert "Owner" in prompt["moment"] and "Burn Through" in prompt["moment"]
    parked = combat._load_session(mid).engine
    assert parked.state.actors[M.OWNER].current_hp == before
    assert parked.state.actors[M.OWNER].reaction_available
    assert bears_mark(parked.state.actors[bearer], M.OWNER, "Smoke Trace")
    answer = M._use(prompt) if accept else {**prompt["context"], "selection": "DECLINE"}
    if ai_turn:
        result = table.auto_step(mid, table.state(mid)["last_sequence"], [answer])
    else:
        state = table.state(mid)
        result = table.act(mid, candidate, state["menu"]["decision_id"], state["menu"]["state_version"],
                           state["last_sequence"], [answer])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(M.ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert engine.state.actors[M.OWNER].current_hp < before
    assert engine.state.actors[M.OWNER].reaction_available is (not accept)
    assert bears_mark(engine.state.actors[bearer], M.OWNER, "Smoke Trace") is (not accept)
    assert bool([r for r in engine.rolls if r.reason == "DAMAGE_REDUCED"]) is accept
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_two_throttles_stop_at_refusal_without_spending_refunded_points(tmp_path):
    combat, table, mid = Q._table(tmp_path, talents=(Q.BOND, Q.THROTTLE), second_qiweaver=True)
    for caster in (Q.t.ME, Q.ALLY):
        Q._advance(combat, table, mid, caster)
        assert Q._send(table, mid, Q._pick(combat, mid, "Qi Bond", Q.sw.FOE))["status"] == "COMMITTED"
        Q._end_turn(table, mid)
    Q._advance(combat, table, mid, Q.sw.FOE)
    Q._end_turn(table, mid)
    # The two casters act between this target turn and its next, in their natural initiative order.
    for _ in range(2):
        assert combat._load_session(mid).engine.state.current_actor_id in (Q.t.ME, Q.ALLY)
        assert Q._send(table, mid, Q._pick(combat, mid, "Throttle Current", Q.sw.FOE))["status"] == "COMMITTED"
        Q._end_turn(table, mid)
    before = combat._load_session(mid).engine.state.actors[Q.sw.FOE]
    assert len([c for c in before.conditions.values() if c.condition_id == Q.THROTTLED]) == 2
    balance = before.resources[Q.STAMINA]
    asked = []

    def answer(prompt):
        asked.append(prompt)
        # Refuse the first restriction. A second prompt would accept and reproduce the refunded-pool spend.
        pick = "refuse" if len(asked) == 1 else "pay"
        return [{**prompt["context"], "selection": "USE", "option_ids": [pick]}]

    result = Q._answer_prompts(table, mid, Q._pick(combat, mid, "Force Mantle"), answer)
    assert result["status"] == "COMMITTED"
    assert len(asked) == 1
    loaded = CombatService(Q.ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[Q.sw.FOE]
    assert target.resources[Q.STAMINA] == balance
    assert not target.bonus_action_available  # Force Mantle spends a Bonus Action
    assert target.concentration is None
    assert not [c for c in target.conditions.values() if c.condition_id == Q.THROTTLED]
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("seed,order", [("AUTO11F1-SVC", [S.VICTIM, S.THIEF]),
                                       ("SOL127-FILTHY-2", [S.THIEF, S.VICTIM])])
def test_filthy_distraction_uses_thief_turn_through_commit_reload(tmp_path, seed, order):
    combat, table, mid = S.fight(tmp_path, ["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_FILTHY_DISTRACTION",
                                          "DARK_BASE_DARKNESS"], seed=seed,
                                thief_skills=[{"skill": "Sleight of Hand", "bonus": 30}])
    # Conceal the thief with printed Darkness, rather than injecting a condition.
    engine = S.engine(combat, mid)
    assert engine.state.initiative_order == order
    candidate = next(c.candidate_id for c in engine.legal_candidates()
                     if c.display_name.startswith("Darkness at")
                     and c.destination and (c.destination.x, c.destination.y) == (3, 6))
    result, _ = S.play(table, mid, candidate, answer=None)
    assert result["status"] == "COMMITTED"
    S.play(table, mid, table.state(mid)["menu"]["end_turn"])
    while S.engine(combat, mid).state.current_actor_id != S.THIEF:
        S.play(table, mid, table.state(mid)["menu"]["end_turn"])
    from combat import stealth
    engine = S.engine(combat, mid)
    assert not stealth.sees(engine, engine.state.actors[S.VICTIM], engine.state.actors[S.THIEF])
    result, _ = S.play(table, mid, S.candidate(table, mid, "DIRTY TRICK: Eyes Spoiled", target=S.VICTIM))
    assert result["status"] == "COMMITTED"
    loaded = CombatService(S.ROOT, tmp_path)._load_session(mid)
    condition = next(c for c in loaded.engine.state.actors[S.VICTIM].conditions.values()
                     if c.condition_id == scoundrel_riders.FILTHY_CONDITION)
    deadline = loaded.engine.state.actors[S.THIEF].turns_started + 1
    assert effect_durations.parse(condition.expires_on) == ("end", S.THIEF, deadline)
    assert "Thief's next turn" in condition.data["label"]
    for _ in range(6):
        engine = S.engine(combat, mid)
        ending = engine.state.current_actor_id
        turns = engine.state.actors[S.THIEF].turns_started
        S.play(table, mid, table.state(mid)["menu"]["end_turn"])
        loaded = CombatService(S.ROOT, tmp_path)._load_session(mid)
        exists = any(c.condition_id == scoundrel_riders.FILTHY_CONDITION
                     for c in loaded.engine.state.actors[S.VICTIM].conditions.values())
        assert exists is not (ending == S.THIEF and turns == deadline)
        if not exists:
            assert loaded.mechanical.replay()["status"] == "PASS"
            return
    raise AssertionError("Filthy Distraction failed to expire")
