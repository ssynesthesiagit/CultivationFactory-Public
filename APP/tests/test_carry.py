"""Items in a fight and a load that follows them (owner 2026-09-27: "we should have a tab for items and equipment.
Dropping things should also be an option"; "we should have encumberance update with the state of the time").
combat/carry.py, combat/factory_compiler.py _carrying / _leave_behind, the Drop / Pick up actions."""

from pathlib import Path

from combat import carry
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.porter"
KIT = {"items": [{"item_id": "tianxia.mortal.armor.lacquered_lamellar", "name": "Lacquered Lamellar", "quantity": 1},
                 {"item_id": "tianxia.mortal.gear.explorer_s_pack", "name": "Explorer's Pack", "quantity": 1},
                 {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}


def _sheet() -> dict:
    stats = dict(SHEET["ability_scores_and_statistics"])
    stats["abilities"] = [{**row, "score": 6, "modifier": -2} if row["ability"] == "STR" else row for row in stats["abilities"]]
    return {**SHEET, "ability_scores_and_statistics": stats, "equipment": [{"starting_kit": KIT}]}


def _fight(bundle) -> Gate4ControllerEngine:
    engine = Gate4ControllerEngine(ROOT, match_seed="CARRY", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _do(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))


def test_dropping_lightens_the_load_and_speed_follows_it():
    bundle = compile_character(_sheet(), actor_id=ME)
    assert bundle["carrying"]["over"] and bundle["carrying"]["template_speed_ft"] == 5 and bundle["carrying"]["speed_ft"] == 30
    engine = _fight(bundle)
    me = engine.state.actors[ME]
    assert engine._effective_speed(me) == 5
    assert "Drop Lacquered Lamellar" not in [c.display_name for c in engine.legal_candidates()]  # worn armour stays on
    _do(engine, "Drop Explorer's Pack")  # 101 lb -> 46 lb, capacity 90
    assert not carry.status(engine, me)["over"] and engine._effective_speed(me) == 30
    names = [c.display_name for c in engine.legal_candidates()]
    assert "Pick up Explorer's Pack" in names and "Drop Explorer's Pack" not in names
    _do(engine, "Pick up Explorer's Pack")
    assert carry.status(engine, me)["over"] and engine._effective_speed(me) == 5


def test_a_dropped_weapon_cannot_attack_until_it_is_picked_up():
    engine = _fight(compile_character(_sheet(), actor_id=ME))
    _do(engine, "Drop Bi Shou (Dagger)")
    names = [c.display_name for c in engine.legal_candidates()]
    assert not any(name.startswith("Bi Shou (Dagger) attack") for name in names) and "Pick up Bi Shou (Dagger)" in names


def test_leaving_things_behind_starts_the_fight_lighter_and_without_their_attacks():
    bundle = compile_character(_sheet(), actor_id=ME, left_behind=["tianxia.mortal.gear.explorer_s_pack", "tianxia.mortal.weapon.bi_shou"])
    assert not bundle["carrying"]["over"] and bundle["carrying"]["template_speed_ft"] == 30
    rows = bundle["action_catalog"].values() if isinstance(bundle["action_catalog"], dict) else bundle["action_catalog"]
    assert not any(".weapon.bi_shou" in (row if isinstance(row, dict) else row.model_dump())["source_definition_id"] for row in rows)
