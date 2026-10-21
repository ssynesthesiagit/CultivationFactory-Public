"""Forms and stances (combat/stances.py) and the plug-in hook layer (combat/ext) -- owner 2026-09-28, the automation push."""

from pathlib import Path

from combat import ext, stances
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.form"


def _engine(talents):
    sheet = {**SHEET, "equipment": [], "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.unmaking", "tianxia.sphere.iron_fist"],
                                                               "learned_talent_record_ids": talents}}
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="FORM", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine, bundle


def _do(engine, name, bonus=None):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    if bonus is not None:
        typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
        typed["numbers"] = {**typed["numbers"], "attack_bonus": bonus}
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))


def test_the_second_ruin_form_is_a_stance_whose_hit_rider_needs_it_active():
    engine, bundle = _engine(["TAL_IRON_FIST_IRON_FIST_TRAINING", "TAL_UNMAKING_BLACK_VEIN_PALM", "TAL_UNMAKING_SECOND_RUIN_FORM_BLACK_PALM_VESSEL"])
    form = next(row for row in bundle["action_catalog"] if row["display_name"].startswith("Second Ruin Form"))
    assert form["economy"] == "BONUS_ACTION" and form["parameters"]["typed"]["effects"][0]["type"] == "stance"
    assert not any("Second Ruin Form" in str(row.get("name")) for row in bundle["modifiers"] if row.get("status") == "applied")
    me = engine.state.actors[ME]
    _do(engine, form["display_name"])
    assert stances.active(me)
    _do(engine, "Unarmed Strike (Iron Fist)", bonus=30)
    riders = [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and "Second Ruin Form" in str((e.payload or {}).get("text"))]
    assert riders and me.turn_flags.get(f"stance_damaged:{stances.PREFIX}second_ruin_form")


def test_a_plug_in_effect_and_hook_run_and_a_failing_hook_does_not_end_the_fight():
    calls = []

    @ext.effect("test_plug_in_effect")
    def _effect(ctx, effect):
        calls.append(("effect", effect.get("value")))

    @ext.hook("turn_end")
    def _broken(engine, actor):
        raise RuntimeError("boom")

    try:
        engine, _bundle = _engine(["TAL_IRON_FIST_IRON_FIST_TRAINING"])
        from combat.typed_executor import Context, run_effects

        me = engine.state.actors[ME]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
        run_effects(Context(engine, me, action, None, {"numbers": {}}, [], None), [{"type": "test_plug_in_effect", "value": 7}])
        assert calls == [("effect", 7)]
        engine._append_event("TURN_ENDED", "test", actor_id=ME, payload={})
        assert any("failed: RuntimeError: boom" in str((e.payload or {}).get("rider")) for e in engine.events if e.event_type == "GM_RIDER")
    finally:
        ext._EFFECTS.pop("test_plug_in_effect", None)
        ext._HOOKS["turn_end"].remove(_broken)
