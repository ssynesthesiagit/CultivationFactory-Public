"""Ask me answers bind to the exact reaction moment they were asked about (owner playtest 2026-09-30,
match:e9f24e69, Tabik Damu on manual control with Ask me reactions).

An AI turn runs the AI's action on a throwaway copy first (combat/gate5_service.py _ask_during_ai_step); the first Ask me
reaction it reaches pauses the copy and the table asks. The pause used to be a RuntimeError, so the "a bad reaction row
must never end a fight" guard around Flowing Response (typed_reactions.on_attacked) swallowed it and logged a GM note:
Flowing Response was never asked, and the copy ran one event ahead of the real action, so the Stamina Guard prompt was
keyed TYPED:DAMAGE_APPLICATION@544 while the real Bone Strike asked at @543. The player's Use never matched, the AI
declined Stamina Guard for them, and the prompt seemed to belong to the Golden Sea Pulse gained just after.
"""

from pathlib import Path
from types import SimpleNamespace

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_context import build_reaction_context
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService, _AnsweringController
from combat.tabletop_service import TabletopService
from tests.test_carry import KIT
from tests.test_pressure import FOUNDATION, PULSE
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.ask_binding"
FOE = "actor:factory.ask_binding_foe"
RESPONSE = "reaction:typed.TAL_FLOWING_RIVER_FLOWING_RESPONSE"
GUARD = "reaction:typed.tianxia.path.body_refining.feature.stamina_guard"


def _fight(tmp_path: Path):
    me_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}], "foundation": FOUNDATION,
                "identity": {**SHEET["identity"], "path": "Body Refining", "cultivation_level": 12},
                "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"],
                                                  "primary_resource": {"name": "Stamina", "maximum": 30}},
                "path_and_subpath": {"path_feature_record_ids": ["tianxia.path.body_refining.feature.stamina_guard"]},
                "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.flowing_river"],
                                        "learned_talent_record_ids": ["TAL_FLOWING_RIVER_FLOWING_RESPONSE"]}}
    foe_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}], "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    mine = compile_character(me_sheet, actor_id=ME, reaction_plan={"ask": True})
    theirs = compile_character(foe_sheet, actor_id=FOE)
    asks = {row["feature_id"]: row.get("ask") for row in mine["typed_reactions"]}
    assert asks["TAL_FLOWING_RIVER_FLOWING_RESPONSE"] and asks["tianxia.path.body_refining.feature.stamina_guard"]
    engine = Gate4ControllerEngine(ROOT, match_seed="ASK-BINDING", typed_bundles=(mine, theirs),
                                   roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine.typed_ask_reactors = frozenset({ME})  # a player controls ME with Ask me reactions
    _foe_turn(engine)
    return CombatService(ROOT, tmp_path), engine


def _foe_turn(engine):
    engine.state.current_slot_index = engine.state.initiative_order.index(FOE)
    engine.state.current_actor_id = FOE
    engine._system_start_turn()


def _foe_attack(engine) -> ActionIntent:
    """The foe's melee weapon attack on ME, made to hit (so there is damage to soak)."""
    attack = next(c for c in engine.legal_candidates() if c.actor_id == FOE and ".weapon." in c.source_definition_id
                  and (engine.action_catalog[c.source_definition_id].range_ft or 5) <= 5 and ME in (c.target_ids or ()))
    typed = engine.action_catalog[attack.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": 60}
    next(e for e in typed["effects"] if e.get("type") == "attack")["count"] = 1
    return ActionIntent(intent_id=f"atk{engine.state.event_sequence}", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                        state_version=attack.state_version, actor_id=FOE, target_ids=attack.target_ids)


def _ask_all(service, engine, intent, choose):
    """What the table does for an AI step: ask until every prompt is answered (``choose`` answers each)."""
    answers, asked = {}, []
    for _ in range(10):
        needed = service._ask_during_ai_step(SimpleNamespace(engine=engine), SimpleNamespace(intent=intent), answers)
        if needed is None:
            return answers, asked
        context = needed.context
        asked.append(context)
        selection = choose(context)
        answers[(context.checkpoint, context.reactor_id, context.reaction_source_id)] = ReactionDecision(
            checkpoint=context.checkpoint, reactor_id=context.reactor_id, reaction_source_id=context.reaction_source_id,
            selection=selection, option_ids=(context.extension_choice.preferred_option_ids
                if context.extension_choice and selection == "USE" else ()))
    raise AssertionError("the prompts never ended")


def _commit(service, engine, intent, answers):
    """The real action, as local_step commits it: the answered prompts through _AnsweringController, the rest AI."""
    controller = _AnsweringController(service.controller, answers)
    records = []

    def provider(request):
        policy, _ = service.policies.for_actor(str(request["reactor_id"]))
        reaction = controller.choose_reaction(build_reaction_context(engine, policy, request))
        records.append(reaction.record)
        return reaction.decision, None

    engine.set_reaction_provider(provider)
    try:
        engine.execute_intent(intent)
    finally:
        engine.set_reaction_provider(None)
    return {(r.selected_reaction.checkpoint, r.selected_reaction.reaction_source_id): (r.controller_id, r.selected_reaction.selection)
            for r in records}


def test_each_prompt_names_its_own_reaction_and_a_use_applies_to_exactly_that_damage(tmp_path):
    service, engine = _fight(tmp_path)
    me = engine.state.actors[ME]
    hp, start = me.current_hp, engine.state.event_sequence
    intent = _foe_attack(engine)
    answers, asked = _ask_all(service, engine, intent, lambda ctx: "DECLINE" if ctx.reaction_source_id == RESPONSE else "USE")
    # Flowing Response is asked when the attack is declared (it used to be swallowed), then Stamina Guard at the damage.
    assert [(ctx.checkpoint.split("@")[0], ctx.reaction_source_id) for ctx in asked] == [
        ("TYPED:ATTACK_DECLARED", RESPONSE), ("TYPED:DAMAGE_APPLICATION", GUARD)]
    records = _commit(service, engine, intent, answers)
    # Every answer bound at commit: the player's own choices, at exactly the moments asked -- none left to the AI.
    for ctx in asked:
        assert records[(ctx.checkpoint, ctx.reaction_source_id)] == ("controller:manual.adapter", answers[(ctx.checkpoint, ME, ctx.reaction_source_id)].selection)
    new = [e for e in engine.events if e.sequence > start]
    resolved = [e for e in new if e.event_type == "REACTION_RESOLVED" and e.source_definition_id.endswith("stamina_guard")]
    committed = [e for e in new if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]
    assert len(resolved) == 1 and len(committed) == 1
    guard_at = int(asked[1].checkpoint.split("@")[1])
    assert resolved[0].sequence > guard_at and resolved[0].sequence < committed[0].sequence  # on this damage, before it lands
    assert resolved[0].payload["pending_before"] == committed[0].payload["rolled_or_pending_damage"]
    assert me.current_hp == hp - committed[0].payload["hp_damage"]
    assert not any(e.event_type == "GM_RIDER" and "could not run" in str(e.payload.get("rider")) for e in new)


def test_a_decline_uses_nothing_and_old_answers_do_not_carry_to_the_next_attack(tmp_path):
    service, engine = _fight(tmp_path)
    me = engine.state.actors[ME]
    stamina = me.resources["resource:core.stamina"]
    intent = _foe_attack(engine)
    answers, asked = _ask_all(service, engine, intent, lambda _ctx: "DECLINE")
    assert [ctx.reaction_source_id for ctx in asked] == [RESPONSE, GUARD]
    records = _commit(service, engine, intent, answers)
    assert set(records.values()) == {("controller:manual.adapter", "DECLINE")}
    assert not any(e.event_type == "REACTION_RESOLVED" and e.actor_id == ME for e in engine.events)
    assert me.resources["resource:core.stamina"] == stamina and me.reaction_available
    # A passive resource gain (Golden Sea Pulse from the hostile damage) is no reaction and raises no prompt.
    assert me.resources[PULSE] == 1
    # The next attack is its own question: the answers given for the last one are not reused.
    _foe_turn(engine)
    again = _foe_attack(engine)
    needed = service._ask_during_ai_step(SimpleNamespace(engine=engine), SimpleNamespace(intent=again), answers)
    assert needed is not None and (needed.context.checkpoint, ME, needed.context.reaction_source_id) not in answers


def test_the_table_prompt_names_the_triggering_action_and_the_damage(tmp_path):
    service, engine = _fight(tmp_path)
    intent = _foe_attack(engine)
    _answers, asked = _ask_all(service, engine, intent, lambda _ctx: "DECLINE")
    table = TabletopService(service, tmp_path)
    table._names_for("match:ask-binding", engine)
    attack_name = next(engine.action_catalog[c.source_definition_id].display_name for c in engine.legal_candidates()
                       if c.candidate_id == intent.candidate_id)
    declared, damage = (table._reaction_prompt("match:ask-binding", ctx.model_dump(mode="json", by_alias=True), engine=engine) for ctx in asked)
    assert declared["reaction"] == "Flowing Response" and attack_name in declared["trigger"] and declared["action"] == attack_name
    assert damage["reaction"] == "Stamina Guard" and damage["action"] == attack_name
    assert "is about to take" in damage["trigger"] and attack_name in damage["trigger"]
    assert "is about to take damage" not in damage["trigger"]
    assert damage["context"] == {"checkpoint": asked[1].checkpoint, "reactor_id": ME, "reaction_source_id": GUARD}
