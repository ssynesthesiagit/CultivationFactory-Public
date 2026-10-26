"""Magma rider wiring through compiled table actions, cold load and native replay."""
import pytest

from combat import zones
from combat.ext import magma_crust
from combat.typed_executor import check_mode
from tests.auto_worker1_support import (
    LEFT, RIGHT, act, cell_send, fight, settle, turn,
)
from tests.test_a2_magma import cold

MAGMA = "tianxia.sphere.magma"
HEAT = "condition:typed.heat_pressure"
GLOB = "TAL_MAGMA_MAGMA_GLOB"


def choose_heat(mode="reactions", turn_mode="action"):
    def choose(prompt):
        source = prompt["context"]["reaction_source_id"]
        if source == "choice:needle.magma_glob_expression":
            return ["Heat Pressure"]
        if source == "choice:needle.magma_heat_pressure":
            return [mode]
        if source == "choice:needle.magma_heat_turn":
            assert prompt["context"]["reactor_id"] == RIGHT
            return [turn_mode]
        options = prompt["choice"]["options"]
        count = prompt["choice"].get("minimum", 1)
        return [o["id"] for o in options[:count]]
    return choose


CASES = [
    ("TAL_MAGMA_BOILING_ASH_SKY", "Boiling Ash Sky", "zone", False),
    ("TAL_MAGMA_VOLCANIC_SMOKE", "Volcanic Smoke", "zone", False),
    ("TAL_MAGMA_HEAVEN_FALLING_METEOR", "Heaven-Falling Meteor", "area", False),
    ("TAL_MAGMA_MAGMA_PRISON", "Magma Prison", "target", True),
    ("tianxia.talent.magma.sea_of_molten_heaven", "Sea of Molten Heaven", "zone", True),
    ("TAL_MAGMA_COURT_OF_THE_LIVING_VOLCANO", "Court of the Living Volcano", "self", False),
    ("TAL_MAGMA_FURNACE_MANTLE", "Furnace Mantle", "self", False),
    (GLOB, "Magma Glob: Heat Pressure", "target", False),
]


@pytest.mark.parametrize("source,label,delivery,success", CASES)
def test_printed_heat_uses_owned_choice_and_persists(tmp_path, source, label, delivery, success):
    c, t, m = fight(tmp_path, [source], spheres=[MAGMA], cl=17,
                    left_attack_bonus=100, left_save_dc=-100 if success else 100)
    pick = choose_heat()
    if delivery in {"zone", "area"}:
        _, prompts = settle(cell_send(t, m, label, (4, 6)), pick)
    else:
        _, prompts = settle(lambda a: act(t, m, label, a,
                                         **({"target_id": RIGHT} if delivery == "target" else {})), pick)
    if delivery in {"zone", "self"}:
        # Start-turn questions belong to their caster even on an enemy turn.
        turn(t, m, RIGHT, pick)
    c, t, e = cold(c, m)
    held = [v for v in e.state.actors[RIGHT].conditions.values()
            if v.condition_id == HEAT]
    assert len(held) == 1
    assert held[0].source_actor_id == LEFT
    assert held[0].data["mode"] == "reactions"
    assert LEFT in magma_crust.heat_choosers(e)
    assert RIGHT in magma_crust.heat_choosers(e)
    assert any(v.condition_id == "condition:typed.reaction_denied"
               for v in e.state.actors[RIGHT].conditions.values())
    assert any(v.event_type == "CONDITION_APPLIED" and RIGHT in v.target_ids
               and v.payload.get("condition_id") == HEAT for v in e.events)


@pytest.mark.parametrize("mode", ["check", "move_or_action"])
def test_glob_fourth_choice_or_next_check_is_real_not_a_rider(tmp_path, mode):
    c, t, m = fight(tmp_path, [GLOB], spheres=[MAGMA], left_attack_bonus=100,
                    cause=[{"type": "skill_check", "ability": "STR", "skill": "Athletics", "applies_to": "self", "dc": 1}])
    pick = choose_heat(mode)
    settle(lambda a: act(t, m, "Magma Glob: Heat Pressure", a, target_id=RIGHT), pick)
    c, t, e = cold(c, m)
    target = e.state.actors[RIGHT]
    heat, = [v for v in target.conditions.values() if v.condition_id == HEAT]
    assert heat.data["mode"] == mode
    if mode == "check":
        assert check_mode(target, "STR", engine=e) == "DISADVANTAGE"
        assert check_mode(target, "DEX", engine=e) == "DISADVANTAGE"
        assert check_mode(target, "WIS", engine=e) == "NORMAL"
    turn(t, m, RIGHT, pick)
    c, t, e = cold(c, m)
    if mode == "move_or_action":
        heat, = [v for v in e.state.actors[RIGHT].conditions.values() if v.condition_id == HEAT]
        assert heat.data["turn_mode"] == "action"
        assert not any(v.kind.value == "MOVE" for v in e.legal_candidates())
        assert e.state.actors[RIGHT].action_available
    else:
        settle(lambda a: act(t, m, "Cause", a))
        c, t, e = cold(c, m)
        assert not any(v.condition_id == HEAT for v in e.state.actors[RIGHT].conditions.values())
        assert check_mode(e.state.actors[RIGHT], "STR", engine=e) == "NORMAL"


@pytest.mark.parametrize("source,label,kind,expression", [
    ("TAL_MAGMA_OBSIDIAN_SKIN", "Obsidian Skin", "slashing", None),
    ("TAL_MAGMA_MAGMA_ARMOR", "Magma Armor", "fire", "3d6+0"),
])
def test_grappler_start_damage_is_native_and_replays(tmp_path, source, label, kind, expression):
    c, t, m = fight(tmp_path, [source], spheres=[MAGMA], cl=15,
                    cause=[{"type": "condition", "condition": "grappled",
                            "applies_to": "target", "duration": "one_minute"}])
    settle(lambda a: act(t, m, label, a))
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, "Cause", a, target_id=LEFT))
    turn(t, m, LEFT)
    turn(t, m, RIGHT)
    c, t, e = cold(c, m)
    rolls = [v for v in e.events if v.event_type == "DAMAGE_ROLLED"
             and source in v.source_definition_id]
    assert len(rolls) == (1 if expression else 0)
    if expression:
        assert rolls[0].payload["expression"] == expression
    amount = rolls[0].payload["total"] if expression else 4
    assert e.state.actors[RIGHT].current_hp == 1000 - amount
    assert any(v.event_type == "DAMAGE_COMMITTED" and RIGHT in v.target_ids
               and v.payload.get("damage_type", "").lower() == kind for v in e.events)
    assert not any(v.event_type == "GM_RIDER" and source in v.source_definition_id for v in e.events)


def test_magma_armor_only_prevents_own_molten_damage_not_its_other_hazards(tmp_path):
    spec = {"shape": "sphere", "size_ft": 5, "centered_on_self": True,
            "terrain": ["molten terrain"], "difficult": "all",
            "duration": {"kind": "minutes", "amount": 1},
            "triggers": [{"on": ["start"], "who": "any", "roster": [LEFT], "effects": [
                {"type": "damage", "flat": 12, "damage_types": ["fire"]},
                {"type": "speed", "flat": -10, "duration": "until_end_of_turn"},
            ]}]}
    c, t, m = fight(tmp_path, ["TAL_MAGMA_MAGMA_ARMOR"], spheres=[MAGMA],
                    prepare=[{"type": "zone"}], prepare_target="SELF", prepare_zone_spec=spec)
    settle(lambda a: act(t, m, "Prepare", a))
    settle(lambda a: act(t, m, "Magma Armor", a))
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    c, t, e = cold(c, m)
    assert e.state.actors[LEFT].current_hp == 1000
    assert any(v.event_type == "DAMAGE_ROLLED" and LEFT in v.target_ids for v in e.events)
    assert e._effective_speed(e.state.actors[LEFT]) == 20
    assert (3, 6) in zones.difficult_cells(e, e.state.actors[LEFT])


@pytest.mark.parametrize("source,label,hazard", [
    ("TAL_MAGMA_OBSIDIAN_SKIN", "Obsidian Skin", "ordinary_extreme_heat"),
    ("TAL_MAGMA_MAGMA_ARMOR", "Magma Armor", "forced_movement"),
    ("TAL_MAGMA_MAGMA_ARMOR", "Magma Armor", "prone"),
])
def test_armor_check_clauses_use_real_scoped_rolls(tmp_path, source, label, hazard):
    c, t, m = fight(tmp_path, [source], spheres=[MAGMA], prepare=[{
        "type": "contest_against", "actor_check": {"kind": "check", "ability": "STR", "hazards": [hazard]},
        "target_check": {"kind": "dc", "dc": 1},
    }])
    settle(lambda a: act(t, m, label, a))
    c, t, _ = cold(c, m)
    settle(lambda a: act(t, m, "Prepare", a, target_id=RIGHT))
    c, t, e = cold(c, m)
    checks = [v for v in e.events if v.event_type == "CHECK_ROLLED"]
    assert checks[-1].payload["actor"]["mode"] == "ADVANTAGE"


@pytest.mark.parametrize("source,label,category", [
    ("TAL_MAGMA_OBSIDIAN_SKIN", "Obsidian Skin", "ordinary_extreme_heat"),
])
def test_armor_save_clauses_use_real_tagged_saves(tmp_path, source, label, category):
    c, t, m = fight(tmp_path, [source], spheres=[MAGMA], cause=[{
        "type": "save", "ability": "CON", "save_categories": [category],
        "on_fail": [{"type": "damage", "flat": 1, "damage_types": ["force"]}], "on_success": [],
    }])
    settle(lambda a: act(t, m, label, a))
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, "Cause", a, target_id=LEFT))
    c, t, e = cold(c, m)
    saves = [v for v in e.events if v.event_type == "SAVE_ROLLED" and v.payload.get("actor_id") == LEFT]
    assert saves[-1].payload["mode"] == "ADVANTAGE"


@pytest.mark.parametrize("mundane", [False, True])
def test_magma_armor_physical_resistance_is_nonmagical_only(tmp_path, mundane):
    def classify(bundle):
        for action in bundle["action_catalog"]:
            if action["display_name"] == "Cause":
                action["parameters"]["typed"]["mundane"] = mundane
    c, t, m = fight(tmp_path, ["TAL_MAGMA_MAGMA_ARMOR"], spheres=[MAGMA],
                    cause=[{"type": "damage", "flat": 12, "damage_types": ["bludgeoning"]}],
                    bundle_edit=classify)
    settle(lambda a: act(t, m, "Magma Armor", a))
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, "Cause", a, target_id=LEFT))
    c, t, e = cold(c, m)
    assert e.state.actors[LEFT].current_hp == 1000 - (6 if mundane else 12)


