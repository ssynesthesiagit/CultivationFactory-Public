from __future__ import annotations

import json
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.diagnostics import CombatGate1Error
from combat.gate2_runtime_content import AN, LEE, LING, BAI, CUI
from combat.gate2_runtime_models import ConditionInstance, ReactionDecision
from combat.gate3_reducer import canonical_state_sha256
from combat.gate3_storage import Gate3InjectedCrash
from combat.gate4_adapters import ManualControllerAdapter, ScriptControllerAdapter
from combat.gate4_context import build_decision_context, build_reaction_context, reject_future_roll_access
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate4_models import ReactionContext
from combat.gate4_persistence import Gate4Persistence
from combat.gate4_policy import PolicyLibrary
from combat.gate2_scripted import load_script

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "combat_gate2/scripted/Gate2_Scripted_Fight_Input.json"


def engine(seed="GATE4-TEST"):
    return Gate4ControllerEngine(ROOT, match_seed=seed)


def choose(e, actor_id):
    e.state.current_actor_id = actor_id
    policy, _ = PolicyLibrary(ROOT).for_actor(actor_id)
    context = build_decision_context(e, policy)
    return LocalDeterministicController().choose_primary_action(context), context


def selected_source(context, choice):
    return next(c.source_definition_id for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)


def test_context_is_serializable_immutable_and_hides_future_rolls():
    e = engine()
    policy, _ = PolicyLibrary(ROOT).for_actor(e.state.current_actor_id)
    context = build_decision_context(e, policy)
    payload = context.model_dump(mode="json", by_alias=True)
    encoded = json.dumps(payload, sort_keys=True)
    def all_keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from all_keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from all_keys(item)
    keys = set(all_keys(payload))
    assert "match_seed" not in keys
    assert "roll_counter" not in keys
    assert "roller" not in keys
    before = canonical_state_sha256(e.state)
    first = LocalDeterministicController().choose_primary_action(context)
    second = LocalDeterministicController().choose_primary_action(context)
    assert first == second
    assert canonical_state_sha256(e.state) == before
    with pytest.raises(CombatGate1Error) as exc:
        reject_future_roll_access()
    assert exc.value.diagnostic.code == "CONTROLLER_FUTURE_ROLL_ACCESS_REJECTED"


def test_manual_and_script_adapters_use_engine_candidates():
    e = engine("GATE4-ADAPTER")
    policy, _ = PolicyLibrary(ROOT).for_actor(e.state.current_actor_id)
    context = build_decision_context(e, policy)
    candidate = context.legal_candidates[0]
    manual = ManualControllerAdapter(lambda _: (candidate.candidate_id, ()))
    assert manual.choose_primary_action(context).intent.candidate_id == candidate.candidate_id
    script = load_script(SCRIPT)
    scripted_engine = engine("TIANXIA-GATE2-MANUAL-0001")
    policy, _ = PolicyLibrary(ROOT).for_actor(scripted_engine.state.current_actor_id)
    scripted_context = build_decision_context(scripted_engine, policy)
    adapter = ScriptControllerAdapter(script.steps)
    assert adapter.choose_primary_action(scripted_context).intent.reaction_decisions == script.steps[0].reaction_decisions


def test_an_eui_setup_then_first_arm_policy():
    e = engine("GATE4-AN-1")
    choice, context = choose(e, AN)
    assert selected_source(context, choice) == "action:an_eui.ruin_tempered_armament_quick"
    an = e.state.actors[AN]
    # Put an enemy in reach and establish the exact typed prerequisite.
    e.state.actors[BAI].position = an.position.model_copy(update={"x": an.position.x + 1})
    an.conditions["test:ruin"] = ConditionInstance(
        instance_id="test:ruin", condition_id="condition:an_eui.ruin_tempered",
        source_definition_id="action:an_eui.ruin_tempered_armament_quick",
        source_actor_id=AN, target_id=AN, applied_sequence=0,
    )
    choice, context = choose(e, AN)
    assert selected_source(context, choice) == "action:an_eui.first_arm"


def test_lee_jia_builds_then_converts_charge():
    e = engine("GATE4-LEE")
    lee = e.state.actors[LEE]
    lee.action_available = False
    choice, context = choose(e, LEE)
    assert selected_source(context, choice) == "action:lee_jia.gather_charge"
    lee.action_available = True
    lee.bonus_action_available = False
    e.state.actors[BAI].position = lee.position.model_copy(update={"x": lee.position.x + 2})
    lee.resources["resource:lee_jia.lightning_charge"] = 2
    choice, context = choose(e, LEE)
    assert selected_source(context, choice) == "action:lee_jia.lightning_lash"


def test_ling_qi_control_and_support_policy():
    e = engine("GATE4-LING")
    ling = e.state.actors[LING]
    e.state.actors[AN].position = ling.position.model_copy(update={"x": ling.position.x - 2})
    e.state.actors[LEE].position = ling.position.model_copy(update={"x": ling.position.x - 3})
    ling.bonus_action_available = False
    choice, context = choose(e, LING)
    assert selected_source(context, choice) == "action:ling_qi.forgotten_vale_nocturne"
    ling.action_available = False
    ling.bonus_action_available = True
    e.state.actors[BAI].current_hp = 10
    choice, context = choose(e, LING)
    assert selected_source(context, choice) == "action:ling_qi.keep_the_measure"


def test_bai_meizhen_zone_and_cui_command_policy():
    e = engine("GATE4-BAI")
    bai = e.state.actors[BAI]
    e.state.actors[AN].position = bai.position.model_copy(update={"x": bai.position.x - 2})
    e.state.actors[LEE].position = bai.position.model_copy(update={"x": bai.position.x - 3})
    bai.bonus_action_available = False
    choice, context = choose(e, BAI)
    assert selected_source(context, choice) == "action:bai_meizhen.blackwater_serpent_court"
    bai.action_available = False
    bai.bonus_action_available = True
    choice, context = choose(e, BAI)
    assert selected_source(context, choice) == "action:bai_meizhen.command_cui"


def test_reaction_policy_declines_trivial_and_uses_material_packet():
    e = engine("GATE4-REACTION")
    lib = PolicyLibrary(ROOT)
    policy, _ = lib.for_actor(AN)
    controller = LocalDeterministicController()
    base = {
        "checkpoint":"DAMAGE_APPLICATION","reactor_id":AN,
        "reaction_source_id":"reaction:core.stamina_guard",
        "protected_target_id":AN,"damaged_target_id":AN,
        "attacking_actor_id":BAI,"legal_reaction_ids":["reaction:core.stamina_guard"],
        "spend_options":[1,2,3],
    }
    trivial = controller.choose_reaction(build_reaction_context(e, policy, {**base,"pending_damage":2}))
    assert trivial.decision.selection == "DECLINE"
    material = controller.choose_reaction(build_reaction_context(e, policy, {**base,"pending_damage":16}))
    assert material.decision.selection == "USE"
    assert material.decision.spend in {1,2,3}


def test_qi_armor_reaction_uses_actual_checkpoint_context():
    e = engine("GATE4-QI-ARMOR")
    policy, _ = PolicyLibrary(ROOT).for_actor(LING)
    context = build_reaction_context(e, policy, {
        "checkpoint":"ATTACK_HIT_BEFORE_DAMAGE","reactor_id":LING,
        "reaction_source_id":"reaction:ling_qi.qi_armor",
        "protected_target_id":LING,"attacking_actor_id":LEE,
        "provisional_hit":True,"legal_reaction_ids":["reaction:ling_qi.qi_armor"],
    })
    assert LocalDeterministicController().choose_reaction(context).decision.selection == "USE"


def test_embedded_script_reaction_remains_compatibility_authority():
    e = engine("GATE4-EMBEDDED")
    calls = []
    e.set_reaction_provider(lambda req: (calls.append(req), None)[1])
    # Directly ask the seam with an embedded exact decision.
    decision = ReactionDecision(checkpoint="DAMAGE_APPLICATION", reactor_id=AN, reaction_source_id="reaction:core.stamina_guard", selection="DECLINE")
    from combat.gate2_runtime_models import ActionIntent
    intent = ActionIntent(intent_id="i",decision_id="d",candidate_id="c",state_version=0,actor_id=AN,reaction_decisions=(decision,))
    assert e._reaction_decision(intent,"DAMAGE_APPLICATION",AN,"reaction:core.stamina_guard") == decision
    assert calls == []


class CrashAfterPrepare:
    def __call__(self, stage, context):
        if stage == "after_prepare_flush":
            raise Gate3InjectedCrash(stage)


def test_incomplete_prepare_recovery_reproduces_local_choice(tmp_path):
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="GATE4-RECOVERY")
    controller = LocalDeterministicController()
    policies = PolicyLibrary(ROOT)
    actor = session.engine.legal_candidates()[0].actor_id
    policy, _ = policies.for_actor(actor)
    choice = controller.choose_primary_action(build_decision_context(session.engine, policy))
    match_id = session.match_id
    with pytest.raises(Gate3InjectedCrash):
        session.execute_controller_choice(choice, controller=controller, policy_library=policies, failure_injector=CrashAfterPrepare())
    recovered = Gate4Persistence(ROOT, tmp_path).load_match(match_id, recover=True)
    verify = recovered.verify()
    assert verify["controller_open_transactions"] == []
    assert recovered.engine.state.state_version == 1


def test_fallback_policy_is_typed_and_reports_diagnostic():
    e = engine("GATE4-FALLBACK")
    policy = PolicyLibrary(ROOT).fallback()
    context = build_decision_context(e, policy)
    record = LocalDeterministicController().choose_primary_action(context).record
    assert record.fallback_policy_used is True
    assert record.diagnostics[0]["code"] == "CONTROLLER_POLICY_MISSING_USING_FALLBACK"


def test_gate4_generated_artifacts_are_deterministic_and_source_bound(tmp_path):
    from combat.gate4_artifacts import build_gate4_artifacts
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest_one = build_gate4_artifacts(ROOT, first)
    manifest_two = build_gate4_artifacts(ROOT, second)
    assert manifest_one == manifest_two
    first_files = {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*") if path.is_file()
    }
    second_files = {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*") if path.is_file()
    }
    assert first_files == second_files
    inventory = json.loads(
        (first / "generated/Gate4_Policy_Identity_Inventory.json").read_text()
    )
    assert inventory["status"] == "PASS"
    assert inventory["bespoke_policy_count"] == 4
    assert inventory["fallback_policy_count"] == 1
    assert manifest_one["same_action_intent_authority_for_all_controllers"] is True
    assert manifest_one["full_ui_api_ai_integrations_implemented"] is False
