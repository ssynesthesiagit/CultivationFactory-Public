"""Wave-2 sphere ownership: Brute, Berserker, Wrestling, Equipment, Gravity, Hunger, Sand, Protection, Iron Fist,
Blacksmith, Smoke, Athletics, Flowing River, Music, and the Body Refining path (owner 2026-09-28, "automate every
aspect before another playtest"; the docket peer's follow-up merge on 2026-09-29 reported Berserker regressions to
fix at the same time). See combat/ext/body_iron_fist.py, combat/ext/body_berserker.py, combat/ext/gu_berserker.py and
combat/ext/flowing_river.py for what the printed rules say and why each shortcut was taken.

These tests cover the four named "known gap" fixes (Falling Leaf Sweep, Meridian Lock, the Berserker Exertion/Adrenaline
regressions are covered in tests/test_auto_gu.py) plus Berserk's Adrenaline gating this file adds."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import bears_mark
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.body_test"


def _bundle(talents, spheres=("tianxia.sphere.iron_fist",)):
    sheet = {**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": talents}}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, positions):
    actor_ids = list(positions)
    engine = Gate4ControllerEngine(ROOT, match_seed="BODY", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": actor_ids,
                                                 "team_by_actor": {actor_id: ("team:a" if actor_id == ME else "team:b") for actor_id in actor_ids},
                                                 "starting_positions": positions})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _guaranteed_hit(engine, candidate):
    """Force a candidate's attack/save numbers so it lands and any nested save fails (tests/test_unmaking.py's trick)."""
    typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
    typed["numbers"] = {**typed["numbers"], "attack_bonus": 30, "save_dc": 30}


def _use(engine, display_name, target_ids):
    candidate = next((c for c in engine.legal_candidates() if c.display_name == display_name and c.target_ids == target_ids), None)
    assert candidate is not None, f"{display_name!r} against {target_ids} was not a legal candidate"
    _guaranteed_hit(engine, candidate)
    engine.execute_intent(ActionIntent(intent_id=display_name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
    return candidate


# ---------------------------------------------------------------- Falling Leaf Sweep (Iron Fist)

def test_falling_leaf_sweep_knocks_down_a_different_nearby_creature_not_the_shove_target():
    """The previous typing put Falling Leaf Sweep's Dexterity save on the SAME creature Unarmed Strike's Shove option
    had already downed. LEE stands within 5 feet of AN; Shove: Prone against AN should also fell LEE."""
    bundle = _bundle(["TAL_IRON_FIST_IRON_FIST_TRAINING", "TAL_IRON_FIST_FALLING_LEAF_SWEEP"])
    engine = _engine(bundle, {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, LEE: {"x": 3, "y": 5}})
    an, lee = engine.state.actors[AN], engine.state.actors[LEE]
    _use(engine, "Shove: Prone", (AN,))
    assert any("prone" in c.condition_id for c in an.conditions.values()), "the Shove option itself should have knocked AN prone"
    assert any("prone" in c.condition_id for c in lee.conditions.values()), "Falling Leaf Sweep should have knocked LEE prone too"


# ---------------------------------------------------------------- Meridian Lock (Iron Fist)

def test_meridian_lock_adds_a_second_seal_when_meridian_sealing_palm_hits_an_opened_creature():
    """Meridian Lock cannot target Meridian-Sealing Palm through the generic named-modifier system (it is a
    modifier-derived variant of Unarmed Strike, not a standalone built action). combat/ext/body_iron_fist.py's
    after_save hook adds the second (Breath) seal directly when both talents are owned."""
    bundle = _bundle(["TAL_IRON_FIST_IRON_FIST_TRAINING", "TAL_IRON_FIST_MERIDIAN_SEALING_PALM", "TAL_IRON_FIST_MERIDIAN_LOCK"])
    engine = _engine(bundle, {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}})
    me, an = engine.state.actors[ME], engine.state.actors[AN]
    # Meridian-Sealing Palm only triggers on an already-Opened creature: Shove it first (a failed save Opens the attacker's target).
    _use(engine, "Shove: Prone", (AN,))
    assert bears_mark(an, ME, "Opened"), "a failed Shove save should Open the target"
    engine.state.current_actor_id = ME
    me.action_available = True
    palm = next((c for c in engine.legal_candidates() if c.display_name.endswith("+ Meridian-Sealing Palm") and c.target_ids == (AN,)), None)
    assert palm is not None, "Meridian-Sealing Palm should be offered against an Opened creature"
    _guaranteed_hit(engine, palm)
    engine.execute_intent(ActionIntent(intent_id="palm", decision_id=palm.decision_id, candidate_id=palm.candidate_id,
                                       state_version=palm.state_version, actor_id=ME, target_ids=palm.target_ids))
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in an.conditions.values()), \
        "Meridian Lock's Breath Seal (cannot take Reactions) should have landed alongside Meridian-Sealing Palm's own Leg Seal"


# ---------------------------------------------------------------- Berserk's Adrenaline gating

def test_berserk_damage_reduction_only_applies_while_adrenaline_is_chosen():
    """Berserk's -PB-to-all-damage was typed unconditional; the printed rule requires actively entering Adrenaline
    (a -2 AC penalty, one Adrenaline talent active at a time) -- a base rule missing from the typed authority
    entirely (combat/ext/body_berserker.py supplies it)."""
    from combat import typed_reactions

    bundle = _bundle(["TAL_BERSERKER_BERSERK"], spheres=("tianxia.sphere.berserker",))
    engine = _engine(bundle, {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}})
    me = engine.state.actors[ME]
    base_ac = me.armor_class + engine._ac_modifier(me)
    assert typed_reactions.defend(engine, me, 10, "FIRE", None, None) == 10, "no reduction before choosing Adrenaline"
    choice = next(c for c in engine.legal_candidates() if c.display_name == "Adrenaline: Berserk")
    engine.execute_intent(ActionIntent(intent_id="adrenaline", decision_id=choice.decision_id, candidate_id=choice.candidate_id,
                                       state_version=choice.state_version, actor_id=ME, target_ids=choice.target_ids))
    assert me.armor_class + engine._ac_modifier(me) == base_ac - 2, "Adrenaline should cost -2 AC while active"
    reduced = typed_reactions.defend(engine, me, 10, "FIRE", None, None)
    assert reduced == 10 - SHEET["identity"]["proficiency_bonus"], "Berserk should reduce damage by Proficiency Bonus once Adrenaline (Berserk) is chosen"
    off = next(c for c in engine.legal_candidates() if c.display_name == "Adrenaline: none (no Adrenaline talent, no -2 AC penalty)")
    engine.execute_intent(ActionIntent(intent_id="off", decision_id=off.decision_id, candidate_id=off.candidate_id,
                                       state_version=off.state_version, actor_id=ME, target_ids=off.target_ids))
    assert typed_reactions.defend(engine, me, 10, "FIRE", None, None) == 10, "ending Adrenaline should drop the reduction again"
