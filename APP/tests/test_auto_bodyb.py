"""Wave-2 follow-up (bodyb 2026-09-29): Athletics, Music, Flowing River and Smoke records the first body worker did
not reach. Covers the new mechanisms (combat/ext/bodyb_motion.py, combat/ext/rider_outcomes.py) and a sample of the
typing corrections in authority/typed_mechanics/reviewed_final.d/bodyb.json."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.bodyb"


def _bundle(talents, sphere):
    return compile_character({**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}},
                             actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="BODYB", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _use(engine, display_name, *, target_id=None):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == display_name)
    targets = (target_id,) if target_id else candidate.target_ids
    engine.execute_intent(ActionIntent(intent_id="i", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=targets))
    return candidate


# ------------------------------------------------------------------------------------------------- Athletics
def test_court_of_ten_thousand_steps_costs_focus_and_adds_20_speed_while_active():
    bundle = _bundle(["TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS"], "tianxia.sphere.athletics")
    action = next(row for row in bundle["action_catalog"] if row["display_name"] == "Court of Ten Thousand Steps")
    assert action["costs"] and action["costs"][0][0] == "resource:core.martial_focus"
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    base_speed = engine._effective_speed(me)
    _use(engine, "Court of Ten Thousand Steps")
    assert engine._effective_speed(me) == base_speed + 20


def test_unbroken_pursuit_now_costs_martial_focus():
    bundle = _bundle(["TAL_ATHLETICS_UNBROKEN_PURSUIT"], "tianxia.sphere.athletics")
    row = next(r for r in bundle["typed_reactions"] if r.get("feature_id") == "TAL_ATHLETICS_UNBROKEN_PURSUIT")
    assert row.get("cost") or row.get("costs"), "Unbroken Pursuit must cost Martial Focus (it was free before this fix)"


# ------------------------------------------------------------------------------------------------- Music
def test_battle_cadence_is_a_compiled_variant_of_keep_the_measure():
    bundle = _bundle(["MUSIC_BASE_KEEP_THE_MEASURE", "tianxia.talent.music.battle_cadence"], "tianxia.sphere.music")
    cadence = next(row for row in bundle["action_catalog"] if "Battle Cadence" in row["display_name"] and "Keep the Measure" in row["display_name"])
    effects = cadence["parameters"]["typed"]["effects"]
    assert any(e.get("type") == "speed" and e.get("applies_to") == "self" and e.get("flat") == 5 for e in effects)
    assert any(e.get("type") == "extra_damage" and e.get("once_per_turn") for e in effects)


def test_bell_of_warning_is_a_choose_one_reaction_with_a_cost():
    bundle = _bundle(["tianxia.talent.music.bell_of_warning"], "tianxia.sphere.music")
    row = next(r for r in bundle["typed_reactions"] if r.get("feature_id") == "tianxia.talent.music.bell_of_warning")
    assert row.get("costs")
    assert row.get("option_labels") == ["AC Bonus", "Move"]  # Initiative is a GM-only rider, no effect type exists for it


# ------------------------------------------------------------------------------------------------- Flowing River
def test_return_the_grip_compiles_the_failed_save_menu():
    bundle = _bundle(["TAL_FLOWING_RIVER_FLOWING_RESPONSE", "TAL_FLOWING_RIVER_RETURN_THE_GRIP"], "tianxia.sphere.flowing_river")
    engine = _engine(bundle)
    from combat import typed_reactions
    from combat.typed_executor import _walk_rows
    row = next(r for r in typed_reactions._rows(engine, ME, "generic") if r.get("feature_id") == "TAL_FLOWING_RIVER_FLOWING_RESPONSE")
    menu = next(e for e in _walk_rows(row["effects"]) if e.get("id") == "return_the_grip")
    assert [option["id"] for option in menu["options"]] == ["push", "prone", "grapple"]
    assert menu["options"][2]["effects"][0]["grappling_part"] is True


def test_smother_the_breath_reaction_compiles_with_a_save():
    bundle = _bundle(["SMOKE_BASE_SMOKE_VEIL", "SMOKE_BASE_SMOKE_TRACE", "TAL_SMOKE_SMOTHER_THE_BREATH"], "tianxia.sphere.smoke")
    row = next(r for r in bundle["typed_reactions"] if r.get("feature_id") == "TAL_SMOKE_SMOTHER_THE_BREATH")
    assert any(e.get("type") == "save" and e.get("ability") == "con" for e in row["effects"])


def test_a_response_talent_rides_the_success_not_the_declaration():
    """Fight audit 2026-09-29: Return the Grip pushed the attacker 15 feet and knocked it Prone when the attack was
    declared, before the roll and whether or not it missed; the attack then landed from 20 feet."""
    bundle = _bundle(["TAL_FLOWING_RIVER_FLOWING_RESPONSE", "TAL_FLOWING_RIVER_RETURN_THE_GRIP"], "tianxia.sphere.flowing_river")
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    from combat import typed_reactions
    from combat.ext import flowing_river

    row = next(r for r in typed_reactions._rows(engine, ME, "generic") if r.get("feature_id") == flowing_river.RESPONSE)
    riding = [e for e in row["effects"] if e.get("type") == "on_success"]
    assert [e["talent"] for e in riding] == ["TAL_FLOWING_RIVER_RETURN_THE_GRIP"]
    assert not any(e.get("type") == "save" for e in row["effects"])  # nothing rolls when the reaction is declared
    assert flowing_river._known(engine, me) == ["TAL_FLOWING_RIVER_RETURN_THE_GRIP"]
    before = [e.event_type for e in engine.events].count("SAVE_ROLLED")
    flowing_river._succeed(engine, me, foe)
    assert [e.event_type for e in engine.events].count("SAVE_ROLLED") == before + 1  # the chosen talent, on success
