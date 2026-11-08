"""Defensive passives (owner 2026-09-28, "automate every aspect"): Body Conditioning's +1 AC while holding Martial Focus,
Padded Layers' once-a-round reduction in armour, Tempered Flesh's Advantage on body saves. combat/typed_reactions.py
defense rows, combat/gate4_engine.py _ac_modifier, combat/pressure.py save_advantage."""

from pathlib import Path

from combat import pressure, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.guard"
FOCUS = "resource:core.martial_focus"


def _engine(talents, sphere, equipment=None):
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}
    if equipment is not None:
        sheet["equipment"] = equipment
    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="GUARD", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    return engine, bundle


def test_body_conditioning_adds_ac_only_while_holding_martial_focus():
    engine, _bundle = _engine(["TAL_IRON_FIST_BODY_CONDITIONING"], "tianxia.sphere.iron_fist", equipment=[])
    me = engine.state.actors[ME]
    base = engine._ac_modifier(me)
    me.resources[FOCUS] = 0
    assert engine._ac_modifier(me) == base - 1


def test_padded_layers_reduces_bludgeoning_once_a_round_in_armour():
    kit = {"items": [{"item_id": "tianxia.mortal.armor.lacquered_lamellar", "name": "Lacquered Lamellar", "quantity": 1}]}
    engine, _bundle = _engine(["tianxia.talent.equipment.padded_layers"], "tianxia.sphere.equipment", equipment=[{"starting_kit": kit}])
    me = engine.state.actors[ME]
    first = typed_reactions.defend(engine, me, 10, "BLUDGEONING", None, AN)
    second = typed_reactions.defend(engine, me, 10, "BLUDGEONING", None, AN)
    assert first < 10 and second == 10
    engine.state.round_number += 1
    assert typed_reactions.defend(engine, me, 10, "BLUDGEONING", None, AN) == first


def test_tempered_flesh_gives_advantage_on_constitution_saves_against_stunning():
    engine, _bundle = _engine(["tianxia.subpath.body.iron_shirt.feature.tempered_flesh"], "tianxia.sphere.iron_fist", equipment=[])
    me = engine.state.actors[ME]
    assert pressure.save_advantage(engine, me, "CON", {"stunned"})
    assert not pressure.save_advantage(engine, me, "WIS", {"stunned"})
    assert not pressure.save_advantage(engine, me, "CON", {"frightened"})
