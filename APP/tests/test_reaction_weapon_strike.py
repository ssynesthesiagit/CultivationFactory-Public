"""A reaction that makes a weapon attack or an Unarmed Strike with no damage of its own strikes with the reactor's own
weapon (owner 2026-09-29: 38 such reactions rolled a bare 1d4)."""

from pathlib import Path

from combat import typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ME = "actor:factory.reactor"


def test_a_bare_reaction_attack_uses_the_reactors_melee_weapon():
    bundle = compile_character({**SHEET, "equipment": [{"starting_kit": KIT}]}, actor_id=ME)
    engine = Gate4ControllerEngine(Path(__file__).resolve().parents[1], match_seed="RW", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    row = {"feature_id": "x", "name": "Counter", "effects": [{"type": "attack", "attack_kind": "melee weapon", "count": 1, "on_hit": []}], "numbers": {}}
    ctx = typed_reactions._generic_context(engine, me, foe, row)
    assert ctx.typed.get("weapon") and ctx.typed["weapon"].get("damage")
    cultivation = {**row, "effects": [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "on_hit": []}]}
    assert not typed_reactions._generic_context(engine, me, foe, cultivation).typed.get("weapon")
