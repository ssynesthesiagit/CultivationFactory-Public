"""The sheet's "not automated yet" lists are honest, and using an unautomated ability says so (owner 2026-09-28: "still a
bunch of stuff thats getting skipped"; "when i click them nothing happens"). combat/factory_compiler.py _sorted_skipped,
combat/typed_executor.py resolve_typed."""

from combat.factory_compiler import compile_character
from tests.test_teleport import ME
from tests.test_zones import SHEET


def _bundle(sphere: str, talents: list[str]) -> dict:
    return compile_character({**SHEET, "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}, actor_id=ME)


def test_area_shapes_and_build_choices_are_not_listed_as_skipped():
    skipped = _bundle("tianxia.sphere.dark", ["DARK_BASE_DARKNESS", "TAL_DARK_NUMBING_DARKNESS", "TAL_DARK_MELD", "TAL_DARK_SHADOW_SLICK"])["diagnostics"]["skipped"]
    assert "Numbing Darkness" not in skipped["passive"]           # the fight runs it as a shape of Darkness
    assert "Meld" not in skipped["outside"]                       # Meld is an Action now
    assert "Shadow Slick" not in skipped["passive"]               # a shape of Darkness now (its move-through check)
    athletics = _bundle("tianxia.sphere.athletics", ["ATHLETICS_BASE_ATHLETIC_TRAINING"])["diagnostics"]["skipped"]
    assert "Athletic Training" in athletics["build"] and "Athletic Training" not in athletics["passive"]


def test_using_an_unautomated_ability_posts_its_text_for_the_gm():
    from pathlib import Path

    from combat.gate2_runtime_content import AN
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate4_engine import Gate4ControllerEngine

    bundle = _bundle("tianxia.sphere.metal", ["METAL_BASE_METAL_APPRAISAL"])
    engine = Gate4ControllerEngine(Path(__file__).resolve().parents[1], match_seed="GMTEXT", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    use = next(c for c in engine.legal_candidates() if c.display_name.startswith("Metal Appraisal"))
    engine.execute_intent(ActionIntent(intent_id="appraise", decision_id=use.decision_id, candidate_id=use.candidate_id,
                                       state_version=use.state_version, actor_id=ME, target_ids=use.target_ids, destination=use.destination))
    notes = [e.payload.get("rider", "") for e in engine.events if e.event_type == "GM_RIDER"]
    assert notes and "You read the object's structure" in notes[0]  # its printed text, which the table shows on screen
