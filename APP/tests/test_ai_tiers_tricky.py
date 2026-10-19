"""Public, offline AIUP1 regressions; native table fights and small planner frames."""
import json
import zipfile

import pytest

from combat.ai_tiers import tier_for_power_band, tier_for_sheet
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_models import LocalControllerPolicy
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from factory_authoring.sphere_dao import character_dao, controller_policy
from tests.h1_support import ROOT, sheet

OWNER, FOE = ("actor:factory.00000000-0000-4000-8000-00000000a101",
              "actor:factory.00000000-0000-4000-8000-00000000a102")


def fight(tmp_path, talents=(), *, band=None, flight=False, foe_at=None, equal=False,
          seed="AIUP1", arena_id="battlefield:factory_pillar_arena", start_turn=True, bench_starts=False):
    docs = [sheet(list(talents), cl=10, name="Planner"), sheet(list(talents) if equal else [], cl=10, name="Opponent")]
    if band is not None:
        docs[0]["advancement_history"] = {"all_owner_locks": [{"field": "power_band", "value": band}]}
    bundles = []
    for aid, doc in zip((OWNER, FOE), docs):
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid)
        if flight:
            bundle["actor_template"].update(fly_speed_ft=30, hover=True)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    arena = combat.factory_arenas(include_retired=True)[arena_id]
    positions = {OWNER: {"x": 3, "y": 6}, FOE: foe_at or {"x": 9, "y": 5}}
    if bench_starts:
        starts = list(arena["starting_positions"].values())
        positions = {OWNER: min(starts, key=lambda p: (p["x"], p["y"])),
                     FOE: max(starts, key=lambda p: (p["x"], p["y"]))}
    mid = combat._finish_factory_match(bundles, [OWNER, FOE], {OWNER: "team:a", FOE: "team:b"},
        positions, arena, [OWNER, FOE], [],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, match_seed=seed, display_name="Tactics",
        maximum_rounds=8)["match_id"]
    session = combat._load_session(mid)
    if start_turn and session.engine.state.current_actor_id != OWNER:
        end = next(c for c in session.engine.legal_candidates() if c.kind == "END_TURN")
        session.submit_intent(ActionIntent(intent_id="aiup1:end", decision_id=end.decision_id,
            candidate_id=end.candidate_id, state_version=end.state_version, actor_id=end.actor_id),
            primary_decision_record=None, reaction_provider=None)
    return combat, mid, combat._load_session(mid)


def context_for(combat, session):
    policy, _ = combat.policies.for_actor(OWNER)
    return build_decision_context(session.engine, policy, for_ai=True)


def selected(context):
    choice = LocalDeterministicController().choose_primary_action(context)
    candidate = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
    return choice, candidate


@pytest.mark.parametrize("band,tier", [(None, "TRICKY"), ("", "TRICKY"), ("supporting", "TRICKY"),
                                       ("heroic", "TRICKY"), ("rival/boss", "MASTERMIND"), ("unknown", "TRICKY")])
def test_tier_mapping(band, tier):
    assert tier_for_power_band(band) == tier
    assert tier_for_sheet({"advancement_history": {"all_owner_locks": [{"field": "power_band", "value": band}]}}) == tier


def test_sheet_label_setup_and_fight_override_survive_commit_reload(tmp_path):
    combat, mid, session = fight(tmp_path, band="rival/boss")
    assert session.engine.state.actors[OWNER].ai_tier == "MASTERMIND"
    table = TabletopService(combat, tmp_path)
    assert table.sheet(OWNER.removeprefix("actor:factory."))["summary"]["ai_label"] == "AI: Mastermind"
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO", ai_tier="TRICKY")
    assert combat.local_step(mid)["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    loaded = fresh._load_session(mid)
    assert loaded.engine.state.actors[OWNER].ai_tier == "MASTERMIND", "creation default is not rewritten"
    assert loaded.engine.ai_tier_overrides[OWNER] == "TRICKY"
    row = next(a for a in TabletopService(fresh, tmp_path).state(mid, include_menu=False)["presentation"]["actors"]
               if a["entity_id"] == OWNER)
    assert row["ai_label"] == "AI: Tricky"
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_uses_strongest_affordable_talent_and_commits(tmp_path):
    combat, mid, session = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"], foe_at={"x": 10, "y": 5})
    context = context_for(combat, session)
    choice, candidate = selected(context)
    assert "Fireball" in candidate.display_name
    assert "Dao: Fire" in choice.record.explanation
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    result = combat.local_step(mid)
    assert result["status"] == "COMMITTED"
    assert "Fireball" in result["record"]["explanation"]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[OWNER].resources["resource:core.qi"] < session.engine.state.actors[OWNER].resources["resource:core.qi"]


def test_closes_to_best_owned_attack_not_one_square_shuffling(tmp_path):
    combat, mid, session = fight(tmp_path)
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    context = context_for(combat, session)
    choice, candidate = selected(context)
    from combat.ai_tactics import TurnPlan
    plan = TurnPlan(context)
    attacks = [(i["damage"], i["range"]) for i in plan.actions.values() if i["damage"]]
    moves = sum(c.kind == "MOVE" for c in context.legal_candidates)
    details = f"range={plan.attack_range}; foes={len(plan.foes)}; attacks={attacks}; moves={moves}"
    assert candidate.kind == "MOVE", details
    assert candidate.movement_cost_ft >= 25
    assert session.engine._distance_actor_to_actor(actor, session.engine.state.actors[FOE], actor_position=candidate.destination) <= 5
    # Every legal move remains scored, not a hash/top-N subset.
    assert {c.candidate_id for c in context.legal_candidates if c.kind == "MOVE"} <= {
        s.candidate_id for s in choice.record.scored_alternatives}
    session.engine.execute_intent(choice.intent)
    _, next_candidate = selected(context_for(combat, session))
    assert next_candidate.kind == "END_TURN", "already in range: do not pace"


def test_uses_native_flight_to_close_on_perceived_airborne_enemy(tmp_path):
    combat, _, session = fight(tmp_path, flight=True, foe_at={"x": 4, "y": 6, "z": 4})
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    context = context_for(combat, session)
    choice, candidate = selected(context)
    assert candidate.kind == "MOVE" and candidate.metadata["movement_mode"] == "fly"
    assert candidate.destination.z > 0
    session.engine.execute_intent(choice.intent)
    assert actor.position == candidate.destination


def test_two_dao_combinations_choose_different_positions_in_same_situation(tmp_path):
    combat, _, session = fight(tmp_path, ["FIRE_BASE_IGNITE"])
    actor = session.engine.state.actors[OWNER]
    actor.action_available = actor.bonus_action_available = False
    context = context_for(combat, session)
    picks = []
    for spheres in ({"tianxia.sphere.air": 42, "tianxia.sphere.berserker": 12},
                    {"tianxia.sphere.dark": 8, "tianxia.sphere.scoundrel": 5}):
        dao = character_dao(spheres)
        policy = LocalControllerPolicy.model_validate(controller_policy(dao, OWNER))
        choice, candidate = selected(context.model_copy(update={"policy": policy}))
        assert "Dao: " + dao["primary_sphere"] in choice.record.explanation
        picks.append((candidate.kind, candidate.destination))
    assert picks[0] != picks[1]


def test_hidden_truth_does_not_change_tricky_plan(tmp_path):
    combat, _, session = fight(tmp_path, ["FIRE_BASE_IGNITE"])
    engine = session.engine
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, "condition:typed.invisible", "test:concealment", FOE, expires_on=None)
    first = context_for(combat, session)
    choice, _ = selected(first)
    foe.position = Position(x=15, y=5)
    foe.current_hp = 1
    foe.armor_class = 99
    second = context_for(combat, session)
    again, _ = selected(second)
    assert first.actors == second.actors
    assert first.tactics == second.tactics
    assert choice.intent.candidate_id == again.intent.candidate_id


def test_repeated_self_buff_loses_to_followup_and_resource_budget_is_soft(tmp_path):
    from combat.ai_tactics import TurnPlan
    combat, _, session = fight(tmp_path)
    context = context_for(combat, session)
    context.tactics["actions"]["buff"] = {"damage": 0, "control": 8, "range": 5,
        "attack_bonus": None, "costs": [["resource:core.qi", 1]], "economy": "BONUS_ACTION",
        "setup": True, "conditions": []}
    context.tactics["active_sources"].append("buff")
    source = next(c for c in context.legal_candidates if c.kind == "END_TURN")
    buff = source.model_copy(update={"source_definition_id": "buff", "kind": "BONUS_ACTION"})
    legacy = LocalDeterministicController()._score_candidate(context, buff, ())
    assert TurnPlan(context).score(buff, legacy).total < 0
    plan = TurnPlan(context)
    expensive = {"costs": [["resource:core.qi", 20]]}
    assert plan.resource_price(expensive) > plan.resource_price({"costs": [["resource:core.qi", 2]]}) > 0
