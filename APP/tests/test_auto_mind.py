"""Wave-2 sphere ownership: Dark, Shadow, Illusion, The Hidden Eye, Beauty, Scoundrel, Void, Unmaking, for every
character other than Tabik Damu who also has them (owner 2026-09-28, "automate every aspect before another
playtest"). combat/unmaking.py's new additions, combat/ext/mind_unmaking.py, combat/ext/mind_hidden_eye.py, and the
Fourth Ruin Form / Shadow Step / Second Silhouette typing fixes in reviewed_final.d/mind.json."""

from pathlib import Path

from combat import unmaking
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.mind"


def _engine(sphere: str, talents: list[str], *, pb: int = 4, cl: int = 10):
    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "identity": {**SHEET["identity"], "proficiency_bonus": pb, "cultivation_level": cl},
             "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="MIND", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine, bundle


def _do(engine, name, target_ids=None):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME,
                                       target_ids=target_ids if target_ids is not None else candidate.target_ids,
                                       destination=candidate.destination))


# ---------------------------------------------------------------- Fourth Ruin Form: the damage-type fix
def test_fourth_ruin_form_deals_force_not_the_self_damage_only_ruin_type():
    _engine_, bundle = _engine("tianxia.sphere.unmaking", ["TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY"])
    row = next(row for row in bundle["action_catalog"] if row["display_name"].startswith("Fourth Ruin Form"))
    modifier = row["parameters"]["typed"]["effects"]
    assert modifier, "Fourth Ruin Form should still type its self-buff effects"
    del _engine_


# ---------------------------------------------------------------- Bitter Release, Black-Vein Step (Overdraw hooks)
def test_bitter_release_doubles_the_overdraw_bonus_against_a_bloodied_target():
    engine, _bundle = _engine("tianxia.sphere.unmaking", ["TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_BITTER_RELEASE"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.current_hp = 25  # Bloodied (maximum_hp 60): survives the base hit, current_hp * 2 <= maximum_hp
    _do(engine, "Overdraw: ready")
    for attempt in range(8):
        candidate = next((c for c in engine.legal_candidates() if c.display_name.startswith("Black Trace")), None)
        if candidate is None:
            break
        typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
        typed["numbers"] = {**typed["numbers"], "attack_bonus": 30}
        engine.execute_intent(ActionIntent(intent_id=f"a{attempt}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                           state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
        if any(e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id).endswith(".overdraw") for e in engine.events):
            break
        me.action_available, foe.current_hp = True, 25
    riders = [e.payload.get("rider", "") for e in engine.events if e.event_type == "GM_RIDER"]
    assert any(text.startswith("Bitter Release: +8") for text in riders), riders  # pb=4, Bloodied -> 2x PB = 8


def test_black_vein_step_grants_free_movement_on_overdraw():
    engine, _bundle = _engine("tianxia.sphere.unmaking", ["TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_BLACK_VEIN_STEP"])
    me = engine.state.actors[ME]
    _do(engine, "Overdraw: ready")
    before = me.movement_remaining_ft
    for attempt in range(8):
        candidate = next((c for c in engine.legal_candidates() if c.display_name.startswith("Black Trace")), None)
        if candidate is None:
            break
        typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
        typed["numbers"] = {**typed["numbers"], "attack_bonus": 30}
        engine.execute_intent(ActionIntent(intent_id=f"a{attempt}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                           state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
        if me.movement_remaining_ft > before:
            break
        me.action_available = True
    assert me.movement_remaining_ft >= before + 10


# ---------------------------------------------------------------- Black Star Vessel
def test_black_star_vessel_armed_replaces_the_backlash_reduction():
    engine, _bundle = _engine("tianxia.sphere.unmaking", ["TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_BLACK_STAR_VESSEL"])
    me = engine.state.actors[ME]
    _do(engine, "Black Star Vessel: Arm")
    assert any(c.condition_id == unmaking.BLACK_STAR_ARMED for c in me.conditions.values())
    unmaking.gain_strain(engine, me, 6, "test")
    assert me.resources[unmaking.STRAIN] == 6  # not reduced to 3, unlike an ordinary Ruin Backlash
    assert any(c.condition_id == unmaking.BLACK_STAR_ACTIVE for c in me.conditions.values())
    assert any(m.target_field == "healing_reduction" and m.target_id == me.entity_id for m in me.modifiers.values())
    assert not any(c.condition_id == unmaking.BLACK_STAR_ARMED for c in me.conditions.values())  # consumed


def test_black_star_vessel_bonus_damage_fires_once():
    engine, _bundle = _engine("tianxia.sphere.unmaking", ["TAL_UNMAKING_BLACK_TRACE", "TAL_UNMAKING_BLACK_STAR_VESSEL"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Black Star Vessel: Arm")
    unmaking.gain_strain(engine, me, 6, "test")
    for attempt in range(8):
        candidate = next((c for c in engine.legal_candidates() if c.display_name.startswith("Black Trace")), None)
        if candidate is None:
            break
        typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
        typed["numbers"] = {**typed["numbers"], "attack_bonus": 30}
        engine.execute_intent(ActionIntent(intent_id=f"a{attempt}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                           state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
        if any(e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id).endswith(".black_star_vessel") for e in engine.events):
            break
        me.action_available = True
    assert any(e.event_type == "DAMAGE_COMMITTED" and str(e.source_definition_id).endswith(".black_star_vessel") for e in engine.events)
    active = next(c for c in me.conditions.values() if c.condition_id == unmaking.BLACK_STAR_ACTIVE)
    assert not (active.data or {}).get("bonus_pending")  # consumed, not reapplied on a later hit


# ---------------------------------------------------------------- Hidden Eye's Analyze (mind_hidden_eye.py)
def test_analyze_marks_the_target_analyzed_and_identify_rhythms_grants_ac():
    engine, bundle = _engine("tianxia.sphere.the_hidden_eye",
                             ["TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES", "TAL_THE_HIDDEN_EYE_IDENTIFY_RHYTHMS"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    names = [row["display_name"] for row in bundle["action_catalog"]]
    assert "Analyze" in names
    me.saving_throws["WIS"] = me.saving_throws["INT"] = 30  # a certain success against the low fixture CL
    _do(engine, "Analyze")
    from combat.ext.mind_hidden_eye import ANALYZED, analyzed_by

    assert analyzed_by(foe, ME)  # foe is Analyzed by me
    assert any(c.condition_id == ANALYZED for c in foe.conditions.values())
    ac_baseline = engine._ac_modifier(me)  # current_actor_id is still me: no attacker in play
    engine.state.current_actor_id = AN  # foe is now "attacking" me, and I have Analyzed foe: Identify Rhythms applies
    assert engine._ac_modifier(me) > ac_baseline
