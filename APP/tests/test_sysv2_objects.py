"""Destructible objects and structures on the map (owner 2026-09-29, task O): placed on the map, attackable, worked out per
D&D 5.5e (AC by material, HP by size, Damage Threshold, Immunity), and used by the abilities whose text damages objects.

Engine-level: a real character is compiled and the real actions run on a Gate4 engine whose battlefield carries the map's
objects (combat/ext/objects.py). The attack die is forced (13-19: a hit that is not a critical; 2: a miss) so a test does not
wait on luck; damage dice are the roller's own, read back from engine.rolls."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from combat import object_rules
from combat.ext import objects as objects_ext
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate3_reducer import Gate3EventReducer
from combat.gate4_engine import Gate4ControllerEngine
from combat.history_feed import format_history_feed
from combat.tabletop import battlefield_as_map, normalize_map, to_battlefield
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.tabik"
FU = {"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}
FOCUS = "resource:core.martial_focus"
DTD = "tianxia.subpath.qi.dust_cultivator.feature.dust_to_dust"
YARD = [{"id": 1, "kind": "door", "x": 4, "y": 6}, {"id": 2, "kind": "crate", "x": 3, "y": 7},
        {"id": 3, "kind": "wall_section", "x": 9, "y": 6, "threshold": 10}, {"id": 4, "kind": "barrel", "x": 4, "y": 5, "threshold": 8}]


def build(sphere, talents, axe=False, path=(), base=()):
    kit = {"items": [*KIT["items"], *([FU] if axe else [])]}
    sheet = {**SHEET, "equipment": [{"starting_kit": kit}],
             "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [], "automatic_sphere_component_record_ids": list(base),
                                     "learned_talent_record_ids": list(talents)}}
    if path:
        sheet["path_and_subpath"] = {"path_feature_record_ids": list(path)}
    return compile_character(sheet, actor_id=ME)


def fight(bundle, objects=YARD, seed="OBJ1", foe=(14, 6)):
    document = normalize_map({"display_name": "Yard", "width_squares": 20, "height_squares": 14, "objects": objects,
                              "starts": {"team1": [[3, 6]], "team2": [list(foe)]}})
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,), battlefield=to_battlefield(document),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe[0], "y": foe[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def force_d20(engine, low, high):
    """Every d20 lands in low..high (rerolled from the seeded stream until it does)."""
    original = getattr(engine.roller, "_real_d20", None) or engine.roller.d20  # forcing again replaces, never stacks
    engine.roller._real_d20 = original

    def d20(**kwargs):
        while True:
            roll = original(**kwargs)
            if low <= int(roll.natural_result) <= high:
                return roll

    engine.roller.d20 = d20


def candidates(engine, name=None, target=None):
    rows = []
    for candidate in engine.legal_candidates():
        label = getattr(engine.action_catalog.get(candidate.source_definition_id), "display_name", "")
        if (name is None or label == name) and (target is None or target in candidate.target_ids):
            rows.append((label, candidate))
    return rows


def use(engine, name, target=None, at=None):
    """Run the named action (exact display name) against an object, or at a square; returns the events it made."""
    engine.state.actors[ME].action_available = True
    for label, candidate in candidates(engine, name, target):
        if at is not None and not (candidate.destination and (candidate.destination.x, candidate.destination.y) == at):
            continue
        before = len(engine.events)
        engine.execute_intent(ActionIntent(intent_id="x", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                           state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                           destination=candidate.destination, option_ids=candidate.option_ids))
        return engine.events[before:]
    raise AssertionError(f"{name!r} was not offered against {target or at}: {sorted({label for label, _ in candidates(engine)})}")


def updates(events):
    return [event for event in events if event.event_type == "OBJECT_UPDATED"]


def lost(engine, object_id, events):
    """Hit points the object lost to these events."""
    rows = updates(events)
    return sum(int((row.payload.get("damage") or {}).get("taken", 0)) for row in rows if row.payload["object"]["object_id"] == object_id)


def damage_dice(engine, events_from):
    return sum(int(roll.total) for roll in engine.rolls[events_from:] if str(roll.reason).startswith("DAMAGE"))


def proficiency_bonus(engine, feature_id):
    """The Proficiency Bonus the character's own row for this talent carries (the sheet's, not a guess)."""
    return next(int(row["pb"]) for row in objects_ext._rows(engine, ME, "attack") if row["feature_id"] == feature_id)


def names(bundle):
    return {row["display_name"] for row in bundle["action_catalog"]}


# ------------------------------------------------------------------------------------------------ the rules of an object
def stand_in(hp=20, threshold=None, immune=("POISON", "PSYCHIC"), vulnerable=(), resist=()):
    return SimpleNamespace(current_hp=hp, damage_threshold=threshold, damage_immunities=tuple(immune),
                           component={"vulnerable": list(vulnerable), "resist": list(resist)})


def test_damage_threshold_immunity_resistance_and_double_apply_in_the_owners_order():
    """Body Refining R8 / Compendium glossary: threshold on the whole instance, then immunity, then resistance and
    vulnerability, then "double" once."""
    wall = stand_in(threshold=10)
    assert object_rules.work_out([(6, "SLASHING"), (3, "FIRE")], wall)["total"] == 0  # 9 is under 10: no effect at all
    assert object_rules.work_out([(6, "SLASHING"), (4, "FIRE")], wall)["total"] == 10  # the instance, not each packet, meets it
    assert object_rules.work_out([(9, "SLASHING")], wall, reduce_threshold=2)["total"] == 9  # threshold 8 for this attack
    assert object_rules.work_out([(1, "SLASHING")], wall, ignore_threshold=True)["total"] == 1
    assert object_rules.work_out([(8, "POISON"), (5, "PSYCHIC"), (4, "FORCE")], stand_in())["total"] == 4  # every object
    assert object_rules.work_out([(9, "FIRE")], stand_in(resist=["FIRE"]))["total"] == 4  # half, rounded down
    assert object_rules.work_out([(9, "FIRE")], stand_in(resist=["FIRE"]), ignore_resistance=True)["total"] == 9
    assert object_rules.work_out([(5, "FIRE")], stand_in(vulnerable=["FIRE"]))["total"] == 10
    doubled = object_rules.work_out([(7, "SLASHING")], wall, multiplier=2)
    assert doubled["total"] == 0  # 7 never meets the threshold, so there is nothing to double
    assert object_rules.work_out([(11, "SLASHING")], wall, multiplier=2, reduce_threshold=1)["total"] == 22
    resisted = object_rules.work_out([(9, "FIRE")], stand_in(resist=["FIRE"]), multiplier=2)
    assert resisted["total"] == 8  # halved (4) then doubled once, never doubled first (9 x 2 // 2 would be 9)


def test_materials_and_sizes_set_ac_and_hit_points_and_every_object_is_immune_to_poison_and_psychic():
    door, crate, wall = (object_rules.stats({"kind": kind}) for kind in ("door", "crate", "wall_section"))
    assert (door["ac"], door["hp"]) == (15, 18) and door["blocks"]  # wood, medium, resilient (2024 DMG)
    assert (crate["ac"], crate["hp"]) == (15, 3) and not crate["blocks"]  # wood, small, fragile
    assert (wall["ac"], wall["hp"]) == (17, 27)  # stone, large, resilient
    assert object_rules.stats({"kind": "custom", "material": "adamantine", "ac": 0})["ac"] == 23
    assert object_rules.stats({"kind": "door", "hp": 40, "ac": 12, "threshold": 5})["hp"] == 40  # the placement's own numbers win
    assert set(door["immune"]) == {"POISON", "PSYCHIC"} and object_rules.stats({"kind": "ice_block"})["vulnerable"] == ("FIRE",)


# ------------------------------------------------------------------------------------------------ the map
def test_a_map_keeps_valid_objects_only_and_the_arena_gives_them_back():
    document = normalize_map({"display_name": "Yard", "width_squares": 10, "height_squares": 8, "objects": [
        {"id": 1, "kind": "door", "x": 2, "y": 3, "hp": 40, "threshold": 5, "immune": ["fire"]},
        {"id": 1, "kind": "crate", "x": 3, "y": 3},  # a repeated id is renumbered
        {"id": 9, "kind": "dragon", "x": 1, "y": 1},  # not a known kind
        {"id": 10, "kind": "barrel", "x": 30, "y": 1},  # off the map
        {"id": 11, "kind": "chest", "x": "a", "y": 1}]})
    rows = document["objects"]
    assert [(row["kind"], row["x"], row["y"]) for row in rows] == [("door", 2, 3), ("crate", 3, 3)]
    assert rows[0]["hp"] == 40 and rows[0]["threshold"] == 5 and rows[0]["immune"] == ["FIRE"] and rows[1]["id"] != rows[0]["id"]
    assert to_battlefield(document)["map_objects"] == rows
    assert battlefield_as_map(to_battlefield(document))["objects"] == rows
    assert normalize_map({"display_name": "Bare", "width_squares": 6, "height_squares": 6})["objects"] == []


def test_objects_are_real_at_the_first_decision_and_a_standing_door_blocks_its_square():
    engine = fight(build(None, []))
    door = engine.state.objects["object:map.1"]
    assert (door.ac, door.current_hp, door.maximum_hp, door.object_kind) == (15, 18, 18, "door")
    assert set(door.damage_immunities) == {"POISON", "PSYCHIC"} and engine.state.objects["object:map.3"].damage_threshold == 10
    assert (4, 6) in engine.grid.blocked and (3, 7) not in engine.grid.blocked  # a door fills its square, a crate does not
    assert [obj.object_id for obj in engine.state.objects.values()].count("object:map.1") == 1


# ------------------------------------------------------------------------------------------------ Attack an object
AXE_ATTACK = "Attack an object: Fu (Short Axe)"


def history(engine):
    """The fight feed the table shows, in its own words."""
    rows = format_history_feed([event.model_dump(mode="json") for event in engine.events], [], pre_state=None,
                               post_state=engine.state.model_dump(mode="json"), actor_names={ME: "Tabik", AN: "Foe"},
                               definition_names={aid: row.display_name for aid, row in engine.action_catalog.items()})
    return [row["summary"] for row in rows]


def test_attack_an_object_hits_misses_and_a_destroyed_door_opens_its_square():
    engine = fight(build(None, [], axe=True))
    force_d20(engine, 2, 2)
    events = use(engine, AXE_ATTACK, "object:map.1")
    assert not updates(events) and engine.state.objects["object:map.1"].current_hp == 18
    miss = next(event for event in events if event.event_type == "ATTACK_ROLLED")
    assert miss.payload["target_ac"] == 15 and miss.payload["provisional_hit"] is False
    force_d20(engine, 13, 19)
    for _ in range(30):
        rolls_before = len(engine.rolls)
        hp = engine.state.objects["object:map.1"].current_hp
        events = use(engine, AXE_ATTACK, "object:map.1")
        taken = lost(engine, "object:map.1", events)
        assert taken == damage_dice(engine, rolls_before)  # no talent: the axe's own die, nothing added
        assert hp - engine.state.objects["object:map.1"].current_hp == min(hp, taken)
        if engine.state.objects["object:map.1"].destroyed:
            break
    door = engine.state.objects["object:map.1"]
    assert door.destroyed and door.current_hp == 0 and (4, 6) not in engine.grid.blocked
    assert not any("object:map.1" in c.target_ids for _, c in candidates(engine, AXE_ATTACK))  # nothing left to swing at
    lines = history(engine)
    assert any("dealt" in line and "damage to Wooden door" in line and "hit points left" in line for line in lines)
    assert any("Wooden door is destroyed and its square is open" in line for line in lines)
    assert not any("Not automated" in line for line in lines)


def test_a_saved_fight_replays_object_damage_from_the_events():
    engine = fight(build(None, [], axe=True))
    before = engine.state.model_copy(deep=True)
    first = len(engine.events)
    force_d20(engine, 13, 19)
    for _ in range(4):
        use(engine, AXE_ATTACK, "object:map.2")
        if engine.state.objects["object:map.2"].destroyed:
            break
    crate = engine.state.objects["object:map.2"]
    assert crate.current_hp < crate.maximum_hp
    reducer = Gate3EventReducer()
    for event in engine.events[first:]:
        reducer.apply_event(before, event)
    assert before.objects["object:map.2"].model_dump(mode="json") == crate.model_dump(mode="json")


# ------------------------------------------------------------------------------------------------ axe and fist talents
def one_hit(engine, name, target, tries=40):
    """Run the action until it lands; returns (hit points lost, damage dice rolled)."""
    for _ in range(tries):
        rolls_before = len(engine.rolls)
        events = use(engine, name, target)
        if any(event.payload.get("provisional_hit") for event in events if event.event_type == "ATTACK_ROLLED"):
            return lost(engine, target, events), damage_dice(engine, rolls_before), events
    raise AssertionError("no hit")


def test_work_axe_eye_adds_proficiency_bonus_to_an_axe_against_unattended_wood_only():
    engine = fight(build("tianxia.sphere.axes", ["TAL_AXES_CAST_AXE", "TAL_AXES_WORK_AXE_EYE"], axe=True),
                   objects=[{"id": 1, "kind": "door", "x": 4, "y": 6, "hp": 999}, {"id": 2, "kind": "wall_section", "x": 4, "y": 5, "hp": 999}])
    force_d20(engine, 13, 19)
    taken, rolled, _events = one_hit(engine, AXE_ATTACK, "object:map.1")
    pb = proficiency_bonus(engine, "TAL_AXES_WORK_AXE_EYE")
    assert pb >= 2 and taken == rolled + pb  # proficiency bonus: the door is unattended and wooden
    taken, rolled, _events = one_hit(engine, AXE_ATTACK, "object:map.2")
    assert taken == rolled  # stone: no bonus


def test_gate_splitting_blow_is_paid_three_ways_and_cuts_the_threshold_by_proficiency_bonus():
    bundle = build("tianxia.sphere.axes", ["TAL_AXES_CAST_AXE", "TAL_AXES_GATE_SPLITTING_BLOW"], axe=True)
    variants = {name for name in names(bundle) if name.startswith(AXE_ATTACK + " + Gate-Splitting Blow")}
    assert variants == {AXE_ATTACK + f" + Gate-Splitting Blow (1 {way})" for way in ("qi", "stamina", "martial focus")}
    engine = fight(bundle, objects=[{"id": 1, "kind": "barrel", "x": 4, "y": 6, "threshold": 8, "hp": 999}])
    force_d20(engine, 13, 19)
    # a plain axe blow (1d6 + 2d8 never in it) under a threshold of 8 does nothing whenever it is under 8 ...
    plain = [one_hit(engine, AXE_ATTACK, "object:map.1")[:2] for _ in range(10)]
    assert all((taken == 0) == (rolled < 8) for taken, rolled in plain)
    assert any(taken == 0 for taken, _rolled in plain)
    # ... Gate-Splitting Blow adds 2d8 slashing to the same instance and cuts the threshold by the Proficiency Bonus
    pb = proficiency_bonus(engine, "TAL_AXES_GATE_SPLITTING_BLOW")
    spent_before = dict(engine.state.actors[ME].resources)
    for _ in range(10):
        taken, rolled, events = one_hit(engine, AXE_ATTACK + " + Gate-Splitting Blow (1 qi)", "object:map.1")
        assert rolled >= 3 and (taken == 0) == (rolled < 8 - pb)
        if taken:
            assert taken == rolled
            break
    assert engine.state.actors[ME].resources != spent_before  # the Qi was paid


def test_great_destroyer_doubles_a_melee_weapon_only_while_martial_focus_is_held():
    engine = fight(build("tianxia.sphere.berserker", ["TAL_BERSERKER_GREAT_DESTROYER"], axe=True),
                   objects=[{"id": 1, "kind": "door", "x": 4, "y": 6, "hp": 999}])
    force_d20(engine, 13, 19)
    engine.state.actors[ME].resources[FOCUS] = 0
    taken, rolled, _events = one_hit(engine, AXE_ATTACK, "object:map.1")
    assert taken == rolled
    engine.state.actors[ME].resources[FOCUS] = 1
    taken, rolled, events = one_hit(engine, AXE_ATTACK, "object:map.1")
    assert taken == rolled * 2
    assert "double damage" in updates(events)[0].payload["damage"]["notes"]


def test_iron_fist_unarmed_strike_adds_proficiency_bonus_and_world_tempering_ignores_the_threshold():
    bundle = build("tianxia.sphere.iron_fist", ["TAL_IRON_FIST_IRON_MERIDIAN_BODY", "TAL_IRON_FIST_WORLD_TEMPERING_BODY"])
    assert "Attack an object: Unarmed Strike" in names(bundle)
    engine = fight(bundle, objects=[{"id": 1, "kind": "door", "x": 4, "y": 6, "hp": 999, "threshold": 30}])
    force_d20(engine, 13, 19)
    engine.state.actors[ME].resources[FOCUS] = 0
    taken, _rolled, _events = one_hit(engine, "Attack an object: Unarmed Strike", "object:map.1")
    assert taken == 0  # a threshold of 30 stops an unarmed strike
    engine.state.actors[ME].resources[FOCUS] = 1
    taken, rolled, events = one_hit(engine, "Attack an object: Unarmed Strike", "object:map.1")
    assert taken == rolled + proficiency_bonus(engine, "TAL_IRON_FIST_IRON_MERIDIAN_BODY") and taken > 0  # threshold ignored; Iron Meridian Body's PB on top
    assert any("Damage Threshold of 30" in note for note in updates(events)[0].payload["damage"]["notes"])


def test_passive_object_talents_are_not_listed_as_not_automated():
    for sphere, talents in (("tianxia.sphere.axes", ["TAL_AXES_CAST_AXE", "TAL_AXES_WORK_AXE_EYE", "TAL_AXES_GATE_SPLITTING_BLOW"]),
                            ("tianxia.sphere.iron_fist", ["TAL_IRON_FIST_IRON_MERIDIAN_BODY", "TAL_IRON_FIST_WORLD_TEMPERING_BODY"]),
                            ("tianxia.sphere.berserker", ["TAL_BERSERKER_GREAT_DESTROYER"])):
        skipped = build(sphere, talents, axe=True)["diagnostics"]["skipped"]
        assert not [name for kind in ("passive", "reaction", "not_typed") for name in skipped.get(kind) or []]


# ------------------------------------------------------------------------------------------------ direct attacks
def test_unmake_barrier_and_the_lance_attack_an_object_and_ignore_its_threshold_but_still_hit_creatures():
    bundle = build("tianxia.sphere.void", ["TAL_VOID_UNMAKE_BARRIER", "TAL_VOID_HEAVEN_EMPTYING_LANCE"])
    assert {"Unmake Barrier", "Heaven-Emptying Lance"} <= names(bundle)  # the feature block must not swallow the action
    for action in ("Unmake Barrier", "Heaven-Emptying Lance"):
        engine = fight(bundle, objects=[{"id": 3, "kind": "wall_section", "x": 8, "y": 3, "threshold": 30, "hp": 999}], foe=(8, 8))
        force_d20(engine, 15, 19)
        assert candidates(engine, action, AN)  # still aimed at a creature as before
        events = use(engine, action, "object:map.3")
        hit = next(event for event in events if event.event_type == "ATTACK_ROLLED")
        assert hit.payload["target_ac"] == 17 and hit.payload["provisional_hit"]
        assert lost(engine, "object:map.3", events) > 0  # a threshold of 30 did not stop it
        assert any("ignored its Damage Threshold of 30" in note for note in updates(events)[0].payload["damage"]["notes"])


# ------------------------------------------------------------------------------------------------ area techniques
def test_falling_star_hits_every_object_in_its_area_for_double_even_with_no_creature_inside():
    bundle = build("tianxia.sphere.stars", ["STARS_TAL_FALLING_STAR"])
    objects = [{"id": 1, "kind": "door", "x": 8, "y": 6, "hp": 999}, {"id": 2, "kind": "crate", "x": 9, "y": 6, "hp": 999},
               {"id": 3, "kind": "wall_section", "x": 12, "y": 2, "hp": 999, "threshold": 200}]
    engine = fight(bundle, objects=objects)
    rolls_before = len(engine.rolls)
    events = use(engine, "Falling Star (at an object)", at=(8, 6))
    rolled = damage_dice(engine, rolls_before)
    assert rolled > 0
    assert lost(engine, "object:map.1", events) == 2 * rolled and lost(engine, "object:map.2", events) == 2 * rolled  # "double" once
    assert not lost(engine, "object:map.3", events)  # outside the area
    assert not any("Structures and unattended objects take double damage" in str(event.payload) for event in events)  # no rider left
    riders = [line for row in bundle["action_catalog"] if "FALLING_STAR" in row["source_definition_id"]
              for line in row["parameters"]["typed"].get("riders") or []]
    assert not any("take double damage" in line for line in riders)


def test_resonant_shatter_can_be_aimed_at_a_door_between_you_and_the_foe_and_adds_a_die_against_it():
    bundle = build("tianxia.sphere.sound", ["TAL_SOUND_RESONANT_SHATTER"])
    assert {"Resonant Shatter", "Resonant Shatter (at an object)"} <= names(bundle)
    engine = fight(bundle, objects=[{"id": 1, "kind": "door", "x": 6, "y": 6, "hp": 999}, {"id": 2, "kind": "statue", "x": 8, "y": 6, "hp": 999}],
                   foe=(11, 6))
    # The door blocks creature delivery. Main permits empty-area aims, while
    # the object-target sibling can aim directly at the blocking door.
    assert all(not c.metadata.get("hostiles_in_area") for _,c in candidates(engine, "Resonant Shatter"))
    aims = {(c.destination.x, c.destination.y) for _, c in candidates(engine, "Resonant Shatter (at an object)")}
    assert (6, 6) in aims and not any(y > 12 for _x, y in aims)
    assert not any(pos == (3, 1) for pos in aims)  # a square whose line reaches nothing is not offered
    rolls_before = len(engine.rolls)
    events = use(engine, "Resonant Shatter (at an object)", at=(6, 6))
    taken = lost(engine, "object:map.1", events)
    assert taken > 0 and taken == damage_dice(engine, rolls_before)  # its dice plus one more die of the same size: the door is a structure
    assert not lost(engine, "object:map.2", events)  # the statue stands behind the door: the door stops the line
    assert engine.state.actors[AN].current_hp == engine.state.actors[AN].maximum_hp


# ------------------------------------------------------------------------------------------------ Dust to Dust
def test_dust_to_dust_crumbles_and_reduces_placed_objects_and_never_offers_itself_against_creatures_or_artifacts():
    bundle = build(None, [], path=[DTD])
    objects = [{"id": 1, "kind": "door", "x": 5, "y": 6, "hp": 200, "threshold": 30},
               {"id": 2, "kind": "statue", "x": 5, "y": 8, "hp": 500},
               {"id": 3, "kind": "barricade", "x": 5, "y": 3, "material": "adamantine", "hp": 200},
               {"id": 4, "kind": "chest", "x": 5, "y": 4, "artifact": True, "hp": 200},
               # Keep the eligibility probe in clear sight. Finite barricade
               # geometry now occludes the old (5, 2) location; it is tested below.
               {"id": 5, "kind": "crate", "x": 3, "y": 2, "unattended": False, "hp": 200}]
    engine = fight(bundle, objects=objects, foe=(6, 6))
    crumble, reduce = "Dust to Dust: Crumble Matter", "Dust to Dust: Reduce Structure"
    offered = {c.target_ids for label, c in candidates(engine) if label in (crumble, reduce) and c.target_ids}
    assert ("object:map.1",) in offered and ("object:map.2",) in offered
    assert not any(ids == (AN,) for ids in offered)  # never a creature
    assert not candidates(engine, crumble, "object:map.5")  # "not an object being worn or carried"
    assert candidates(engine, reduce, "object:map.5")  # Reduce Structure names objects and structures without that limit
    assert not [c for label, c in candidates(engine, crumble, "object:map.3")] and not [c for label, c in candidates(engine, crumble, "object:map.4")]
    events = use(engine, crumble, "object:map.1")
    assert lost(engine, "object:map.1", events) == 40  # a flat 40, threshold 30 treated as 0
    rolls_before = len(engine.rolls)
    events = use(engine, reduce, "object:map.2")
    taken = lost(engine, "object:map.2", events)
    assert taken == damage_dice(engine, rolls_before) and 6 <= taken <= 48  # 6d8 at this Cultivation Level


def test_finite_barricade_sight_is_separate_from_attended_object_eligibility():
    bundle = build(None, [], path=[DTD])
    engine = fight(bundle, objects=[
        {"id": 1, "kind": "door", "x": 5, "y": 6, "hp": 200, "threshold": 30},
        {"id": 2, "kind": "statue", "x": 5, "y": 8, "hp": 500},
        {"id": 3, "kind": "barricade", "x": 5, "y": 3, "material": "adamantine", "hp": 200},
        {"id": 4, "kind": "chest", "x": 5, "y": 4, "artifact": True, "hp": 200},
        {"id": 5, "kind": "crate", "x": 3, "y": 2, "unattended": False, "hp": 200},
        {"id": 6, "kind": "crate", "x": 5, "y": 2, "unattended": False, "hp": 200},
    ])
    actor = engine.state.actors[ME]
    reduce = "Dust to Dust: Reduce Structure"
    assert engine.state.objects["object:map.3"].height_ft == 5
    assert engine._line_of_sight_actor_to_cell(actor, engine.state.objects["object:map.5"].position)
    assert candidates(engine, reduce, "object:map.5"), "Reduce Structure still permits a visible attended object"
    assert not candidates(engine, "Dust to Dust: Crumble Matter", "object:map.5")
    assert not engine._line_of_sight_actor_to_cell(actor, engine.state.objects["object:map.6"].position)
    assert not candidates(engine, reduce, "object:map.6"), "an eligible object behind the finite barricade is not visible"


# ------------------------------------------------------------------------------------------------ the service and the table
def test_the_table_state_lists_placed_objects_with_their_facts(tmp_path):
    from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_factory_live_match import _install
    from tests.test_tabletop import MAP

    _install(tmp_path, "left")
    _install(tmp_path, "right")
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({**MAP, "objects": [{"id": 1, "kind": "door", "x": 3, "y": 4}, {"id": 2, "kind": "wall_section", "x": 4, "y": 2, "threshold": 10}]})
    table = TabletopService(combat, tmp_path)
    view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
                                       control_modes={FACTORY_ACTOR_PREFIX + "left": "MANUAL"}, arena_id="battlefield:map.courtyard", match_seed="OBJ-TABLE")
    state = table.state(view["match_id"])
    after = state["last_sequence"]
    for _ in range(12):  # the AI side acts until it is the human's turn
        if state["menu"] and state["menu"].get("manual"):
            break
        result = table.auto_step(view["match_id"], after)
        after, state = result["events"]["last_sequence"], result["state"]
    menu = state["menu"]
    # Objects are placed in the fight's own record by the first thing that happens in it (combat/ext/objects.py seed): the
    # human's first move does it, and the table then lists them.
    table.act(view["match_id"], menu["moves"][0]["candidate_id"], menu["decision_id"], menu["state_version"], after)
    state = table.state(view["match_id"])
    shown = {row["name"]: row for row in state["objects"]}
    assert {"Wooden door", "Stone wall section"} <= set(shown)
    assert shown["Wooden door"]["hp"] == 18 and shown["Wooden door"]["blocks"] and "AC 15" in shown["Wooden door"]["detail"]
    assert "Damage Threshold 10" in shown["Stone wall section"]["detail"] and "immune to poison, psychic" in shown["Stone wall section"]["detail"]
    table.delete_match(view["match_id"])
