"""AUTO102 / AUTO102r1f1: Furnace Step's own printed exemptions, resolved by the table.

Furnace Step prints three things on top of its Speed increase: ignore your own Molten Terrain, ignore
ordinary rubble/ash/volcanic stone/obsidian difficult terrain, and provoke no opportunity attack from one
creature of your choice. Every case here drives a real fight through CombatService/TabletopService and
asserts what the printed rules say, at the level they show on the table: movement the mover actually makes
across ground, saves the ground actually calls for, and opportunity attacks creatures actually make.

AUTO102r1f1 narrowed the two ground hooks. The ordinary-ground clause waives movement cost on the
battlefield's own ground; it never waives a save, damage or condition, and ground some ability conjured is
not ordinary ground. Only the mover's own Molten Terrain stops dealing it hazards. The exemption is
computed per source, so another caster's lava lying on the same square keeps its own cost, and exactly one
creature loses its opportunity attack -- a second enemy keeps, and uses, its own.
"""

from __future__ import annotations

import copy
import json
import zipfile

from combat import zones, zone_subjects
from combat.canonical import canonical_sha256
from combat.ext import magma_crust
from combat.factory_compiler import compile_character
from combat.flight import step_cost
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.auto_worker1_support import LEFT, RIGHT, act, reload, settle
from tests.h1_support import ROOT, sheet
from tests.hunt15_support import turn
from tests.test_carry import KIT

F = "TAL_MAGMA_FURNACE_STEP"
MAGMA = "tianxia.sphere.magma"
NO_OA = "condition:typed.no_opportunity_attacks"
THIRD = "actor:factory.magma-third"

# combat/rules/terrain.json's Molten Terrain as a caster's own patch carries it: difficult for everyone,
# and a creature entering it or starting a turn in it makes the DEX save against the creating damage.
MOLTEN = {"shape": "sphere", "size_ft": 5, "difficult": "all", "terrain": ["molten terrain"],
          "duration": {"kind": "minutes", "amount": 1}, "name": "Molten Terrain",
          "triggers": [{"name": "Molten Terrain", "on": ["enter", "start"], "who": "any",
                        "effects": [{"type": "save", "ability": "DEX", "on_success": [],
                                     "on_fail": [{"type": "damage", "applies_to": "target", "flat": 4,
                                                  "formula": "none", "damage_types": ["fire"]}]}]}]}


def _molten(**extra):
    return {**copy.deepcopy(MOLTEN), **extra}


def _bundle(tmp_path, aid, name, talents, *, actions=(), spheres=(), attack_bonus=8, source=None, kinds=()):
    """One character sheet as a real compiled bundle, plus the setup actions this file needs.

    Setup actions are the fixtures' own ``Test setup`` style: an ordinary typed action whose zone_spec is
    the ground under test, so nothing is injected into a saved fight after the fact.
    """
    doc = sheet(list(talents), cl=15, dc=100, kit={"starting_kit": KIT}, score=14)
    doc.setdefault("spheres_and_talents", {})
    doc["spheres_and_talents"]["sphere_record_ids"] = list(spheres)
    doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
    stats = doc["ability_scores_and_statistics"]
    stats["primary_resource"]["maximum"] = 100
    stats["hit_points"]["maximum"] = 1000
    stats["armor_class"]["base_value"] = 1
    stats["technique_attack_bonus"] = attack_bonus
    doc["identity"]["display_name"] = name
    doc["identity"]["creature_types"] = list(kinds)  # printed labels, read by combat/ext/creature_kinds.py
    folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundle = compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
    for index, (label, effect, spec, target) in enumerate(actions):
        action_id = f"action:test.magma.{aid.removeprefix('actor:factory.')}.{index}"
        bundle["actor_template"]["action_ids"].append(action_id)
        bundle["action_catalog"].append({
            "source_definition_id": action_id, "display_name": label, "owner_id": aid, "economy": "NONE",
            "resolution_kind": "TYPED", "target_kind": target, "range_ft": 60, "costs": [],
            "parameters": {"typed": {"effects": [effect],
                                     **({"zone_spec": spec} if spec is not None else {}),
                                     **({"source": source} if source is not None else {}),
                                     "numbers": {"cl": 15, "pb": 4, "key_mod": 3, "save_dc": 100,
                                                 "attack_bonus": 100},
                                     "duration": {"kind": "instant"}, "riders": []}}})
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)
    return bundle


def table_of(tmp_path, *, left_talents=(), left_actions=(), right_actions=(), foes=2, map_terrain=None,
             positions=None, source=None, left_kinds=()):
    """A real fight: the Keeper (who may own Furnace Step) and one or two Visitors.

    Copied from ``tests.auto_worker1_support.fight`` with the two things these cases need: ground painted
    on the arena map -- ``combat/zones.py`` map_zones reads the arena document, so a reloaded fight still
    has that ground, and it has no creator, which is what "ordinary" means -- and a third creature whose
    opportunity attack Furnace Step must leave alone.
    """
    ids = [LEFT, RIGHT] + ([THIRD] if foes > 1 else [])
    names = {LEFT: "Keeper", RIGHT: "Watcher", THIRD: "Warden"}
    bundles = []
    for aid in ids:
        if aid == LEFT:
            bundles.append(_bundle(tmp_path, aid, names[aid], left_talents, actions=left_actions,
                                   spheres=[MAGMA], source=source, kinds=left_kinds))
        else:
            bundles.append(_bundle(tmp_path, aid, names[aid], (), actions=right_actions if aid == RIGHT else (),
                                   attack_bonus=100))
    combat = CombatService(ROOT, tmp_path)
    arena = copy.deepcopy(combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"])
    if map_terrain is not None:
        arena["map_terrain"] = map_terrain
    mid = combat._finish_factory_match(
        bundles, ids, {aid: "team:factory" if aid == LEFT else "team:opponents" for aid in ids},
        positions or {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 5, "y": 6}, THIRD: {"x": 5, "y": 7}},
        arena, [LEFT], [aid for aid in ids if aid != LEFT],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed="AUTO102",
        display_name="Magma ground regression", maximum_rounds=10)["match_id"]
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    return combat, table, mid


def move_to(combat, table, mid, cell):
    """A sender for one real Move candidate, by destination (the same path the table's own menu uses)."""
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind.value == "MOVE" and c.destination is not None
                     and (c.destination.x, c.destination.y) == tuple(cell))
    state = table.state(mid)
    return lambda answers=(): table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                                        state["menu"]["state_version"], state["last_sequence"], list(answers))


def zone_at(engine, cell):
    return next(z for z in zones.typed_zones(engine)
                if (cell[0], cell[1]) in {(c.x, c.y) for c in z.affected_cells})


def choose_furnace(prompt):
    """Name the Watching creature as the one whose opportunity attack is not provoked."""
    if prompt["context"]["reaction_source_id"] == "choice:needle.magma_furnace_step":
        return [RIGHT]
    return [prompt["choice"]["options"][0]["id"]]


def use_reaction(prompt):
    return [{**prompt["context"], "selection": "USE"}]


# --------------------------------------------------------------------------------------- own lava
def test_own_molten_terrain_stops_costing_and_burning_its_creator_until_the_turn_ends(tmp_path):
    """"ignore your own Molten Terrain": the mover's own lava costs nothing and deals it nothing."""
    c, t, m = table_of(tmp_path, left_talents=[F],
                       left_actions=[("Pour lava", {"type": "zone"}, _molten(centered_on_self=True), "SELF")])
    settle(lambda a: act(t, m, "Pour lava", a))
    e = reload(c, m)
    left, right = e.state.actors[LEFT], e.state.actors[RIGHT]
    mine = zone_at(e, (3, 6))
    assert mine.owner_id == LEFT
    # Before the talent the ground is difficult for everyone standing in it, and burns them on entry.
    assert (3, 6) in zones.difficult_cells(e, left)
    assert zone_subjects.allowed(e, mine, left, {"who": "any"})

    settle(lambda a: act(t, m, "Furnace Step", a), choose_furnace)
    e = reload(c, m)
    left = e.state.actors[LEFT]
    assert (3, 6) not in zones.difficult_cells(e, left), "your own Molten Terrain is not difficult for you"
    assert not zone_subjects.allowed(e, mine, left, {"who": "any"}), "your own lava deals you no hazard"
    assert zone_subjects.allowed(e, mine, e.state.actors[RIGHT], {"who": "any"}), "others still burn"

    # The receipt is the printed duration: until the end of the turn that used it.
    turn(t, m, RIGHT)
    e = reload(c, m)
    assert zone_subjects.allowed(e, zone_at(e, (3, 6)), e.state.actors[LEFT], {"who": "any"})
    assert (3, 6) in zones.difficult_cells(e, e.state.actors[LEFT])


def test_conjured_ash_and_obsidian_are_not_ordinary_ground(tmp_path):
    """"ordinary" means ground, not a patch some ability conjured: created ground keeps its cost.

    The waived clause is ordinary rubble, ash, volcanic stone and obsidian -- the battlefield's own
    ground. An Obsidian patch an ability cooled out of lava is that ability's magic and still slows.
    """
    obsidian = {"shape": "sphere", "size_ft": 5, "centered_on_self": True, "difficult": "all",
                "terrain": ["obsidian terrain"], "duration": {"kind": "minutes", "amount": 1},
                "name": "Obsidian Terrain"}
    c, t, m = table_of(tmp_path, left_talents=[F],
                       left_actions=[("Pour lava", {"type": "zone"}, _molten(centered_on_self=True), "SELF"),
                                     ("Cool it", {"type": "zone"}, obsidian, "SELF")])
    settle(lambda a: act(t, m, "Pour lava", a))
    settle(lambda a: act(t, m, "Cool it", a))
    e = reload(c, m)
    assert zone_at(e, (3, 6)).owner_id == LEFT
    assert (3, 6) in zones.difficult_cells(e, e.state.actors[LEFT])

    settle(lambda a: act(t, m, "Furnace Step", a), choose_furnace)
    e = reload(c, m)
    left = e.state.actors[LEFT]
    assert (3, 6) in zones.difficult_cells(e, left), \
        "a conjured Obsidian patch is not ordinary ground, so it still costs the mover movement"
    cooled = next(z for z in zones.typed_zones(e)
                  if "obsidian terrain" in (z.trigger_profile.get("terrain") or []))
    assert zone_subjects.allowed(e, cooled, left, {"who": "any"}), \
        "only your own Molten Terrain stops dealing you hazards"


# --------------------------------------------------------------- overlapping, nonexempt ground
def test_own_lava_lying_inside_a_rival_casters_lava_keeps_its_cost(tmp_path):
    """Two sources on one square: only the mover's own lava is waived, and the rival's still counts.

    combat/zones.py unions every area's squares and subtracts the exemption afterwards, so an exemption
    that named squares rather than sources would hand this creature free movement over hostile lava.
    """
    c, t, m = table_of(tmp_path, left_talents=[F],
                       left_actions=[("Pour lava", {"type": "zone"}, _molten(centered_on_self=True), "SELF")],
                       right_actions=[("Spit lava", {"type": "zone"}, _molten(), "HOSTILE_ENTITY")])
    settle(lambda a: act(t, m, "Pour lava", a))
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, "Spit lava", a, target_id=LEFT))
    turn(t, m, LEFT)
    e = reload(c, m)
    left = e.state.actors[LEFT]
    owners = {z.owner_id for z in zones.typed_zones(e)
              if (3, 6) in {(c_.x, c_.y) for c_ in z.affected_cells}}
    assert owners == {LEFT, RIGHT}, "both casters' lava is on the square under test"
    assert (3, 6) in zones.difficult_cells(e, left), "a rival caster's lava is still difficult terrain"

    settle(lambda a: act(t, m, "Furnace Step", a), choose_furnace)
    e = reload(c, m)  # the service commit and reload keep both patches and the receipt
    left = e.state.actors[LEFT]
    assert (3, 6) in zones.difficult_cells(e, left), \
        "waiving your own lava must not waive the other caster's lava on the same square"
    assert zone_subjects.allowed(e, next(z for z in zones.typed_zones(e) if z.owner_id == RIGHT), left,
                                 {"who": "any"}), "rival lava still deals this creature its hazard"
    # Actual movement: one step into that square costs double movement, waived or not.
    difficult = zones.difficult_cells(e, left)
    uphill = Position(x=3, y=7)
    assert step_cost(e, left, left.position, uphill, difficult=difficult) > \
        e.grid.distance_ft(left.position, uphill)


# --------------------------------------------------- ground whose policy does not reach the mover
def test_a_policy_that_does_not_reach_the_mover_leaves_the_waiver_standing(tmp_path):
    """A conditional area that does not apply to this creature must not cancel the printed waiver.

    Consecrated Boundary charges difficult terrain only to Unclean creatures. It overlaps ordinary
    rubble on the battlefield, which Furnace Step waives, so a creature the boundary never touches still
    crosses that rubble as level ground; a creature it does charge keeps the extra movement. Both sides
    are asserted in the same shape of fight, so the difference is the recipient and nothing else.
    """
    boundary = {"shape": "sphere", "size_ft": 15, "centered_on_self": True,
                "difficult": {"who": "any", "requires_kind": ["unclean"]},
                "duration": {"kind": "minutes", "amount": 1}, "name": "Consecrated Boundary",
                "triggers": []}
    rubble = [{"terrain": "loose rubble", "cells": [[3, 7]]}]
    ahead = Position(x=3, y=7)

    # The mover bears no printed label, so the boundary's Unclean clause never reaches it.
    c, t, m = table_of(tmp_path / "plain", left_talents=[F],
                       left_actions=[("Consecrate", {"type": "zone"}, boundary, "SELF")],
                       map_terrain=rubble)
    settle(lambda a: act(t, m, "Consecrate", a))
    e = reload(c, m)
    assert (3, 7) in zones.difficult_cells(e, e.state.actors[LEFT]), \
        "rubble is difficult terrain before the talent"

    settle(lambda a: act(t, m, "Furnace Step", a), choose_furnace)
    e = reload(c, m)  # commit and reload: the receipt and the overlapping ground both survive
    left = e.state.actors[LEFT]
    assert not zones.zone_is_difficult(e, zone_at(e, (3, 7)), left), \
        "the boundary's Unclean clause does not reach this creature, so it charges nothing here"
    assert (3, 7) not in zones.difficult_cells(e, left), \
        "ground that costs this creature nothing must not be re-charged by a policy that skips it"
    assert (3, 7) in zones.difficult_cells(e, e.state.actors[RIGHT]), "and only for the creature that moved"
    assert step_cost(e, left, left.position, ahead, difficult=zones.difficult_cells(e, left)) == \
        e.grid.distance_ft(left.position, ahead), "one step into that ground costs what level ground costs"

    # The same fight with the mover printed Undead: now the boundary really does charge it, so the
    # surcharge Furnace Step never printed stays.
    c, t, m = table_of(tmp_path / "undead", left_talents=[F], left_kinds=["Undead"],
                       left_actions=[("Consecrate", {"type": "zone"}, boundary, "SELF")],
                       map_terrain=rubble)
    settle(lambda a: act(t, m, "Consecrate", a))
    settle(lambda a: act(t, m, "Furnace Step", a), choose_furnace)
    e = reload(c, m)
    left = e.state.actors[LEFT]
    assert zones.zone_is_difficult(e, zone_at(e, (3, 7)), left), \
        "an Unclean creature is charged by the boundary the mover laid"
    assert (3, 7) in zones.difficult_cells(e, left), \
        "a recipient of another area's surcharge keeps it: the waiver named rubble, not the boundary"
    assert step_cost(e, left, left.position, ahead, difficult=zones.difficult_cells(e, left)) > \
        e.grid.distance_ft(left.position, ahead)


def test_a_mark_policy_that_does_not_reach_the_mover_leaves_the_waiver_standing(tmp_path):
    """The same case for a mark-keyed policy: only the marked creature is charged difficult terrain.

    Aura of Unapproachable Elegance makes its area difficult for the creatures bearing the mark its
    creator placed. Lying over the mover's own Molten Terrain, that aura charges a bearer and skips
    everyone else, so an unmarked mover still steps through its own lava for free.
    """
    aura = {"shape": "sphere", "size_ft": 15, "difficult": "marked:Beauty Mark",
            "duration": {"kind": "minutes", "amount": 1}, "name": "Elegance Aura", "triggers": []}
    mark = {"type": "mark", "applies_to": "target", "mark": "Beauty Mark",
            "duration": {"kind": "until_end_of_your_next_turn"}}
    ahead = Position(x=3, y=7)

    def fight(root, *, marked):
        c, t, m = table_of(root, left_talents=[F],
                           left_actions=[("Pour lava", {"type": "zone"}, _molten(size_ft=15, centered_on_self=True), "SELF")],
                           right_actions=[("Mark them", mark, None, "HOSTILE_ENTITY"),
                                          ("Shine", {"type": "zone"}, aura, "HOSTILE_ENTITY")])
        settle(lambda a: act(t, m, "Pour lava", a))
        turn(t, m, RIGHT)
        if marked:
            settle(lambda a: act(t, m, "Mark them", a, target_id=LEFT))
        settle(lambda a: act(t, m, "Shine", a, target_id=LEFT))
        turn(t, m, LEFT)
        return c, t, m

    c, t, m = fight(tmp_path / "unmarked", marked=False)
    settle(lambda a: act(t, m, "Furnace Step", a), choose_furnace)
    e = reload(c, m)
    left = e.state.actors[LEFT]
    assert not [row for row in left.conditions.values()
                if str(row.condition_id).startswith("condition:typed.mark.")], "nothing marked this creature"
    assert (3, 7) not in zones.difficult_cells(e, left), \
        "an area that is difficult only for marked creatures leaves the waiver standing for the rest"
    assert step_cost(e, left, left.position, ahead, difficult=zones.difficult_cells(e, left)) == \
        e.grid.distance_ft(left.position, ahead)

    c, t, m = fight(tmp_path / "marked", marked=True)
    settle(lambda a: act(t, m, "Furnace Step", a), choose_furnace)
    e = reload(c, m)
    left = e.state.actors[LEFT]
    assert [row for row in left.conditions.values()
            if str(row.condition_id).startswith("condition:typed.mark.")], "the mark the aura keys off is on it"
    assert (3, 7) in zones.difficult_cells(e, left), \
        "a creature bearing the mark keeps the aura's surcharge over its own lava"
    assert step_cost(e, left, left.position, ahead, difficult=zones.difficult_cells(e, left)) > \
        e.grid.distance_ft(left.position, ahead)


# ----------------------------------------------------------------- burning ground is no ground
def test_ordinary_ground_is_waived_but_a_burning_hazard_still_saves_and_burns(tmp_path):
    """Rubble on the map costs nothing; Fire Terrain on the same board still saves, burns and kindles.

    Fire Terrain is a hazard, not ordinary ground, so the printed clause -- which waives movement cost --
    never touched it. The mover walks into it after the receipt exists and takes what it prints.
    """
    rubble = [{"terrain": "loose rubble", "cells": [[2, 6], [3, 5]]},
              {"terrain": "fire terrain", "cells": [[4, 6]], "save_dc": 30, "pb": 4}]
    c, t, m = table_of(tmp_path, left_talents=[F], map_terrain=rubble)
    e = reload(c, m)
    left, right = e.state.actors[LEFT], e.state.actors[RIGHT]
    fire = next(z for z in zones.typed_zones(e) if "fire terrain" in (z.trigger_profile.get("terrain") or []))
    assert (2, 6) in zones.difficult_cells(e, left), "rubble on the map is difficult terrain before the talent"

    settle(lambda a: act(t, m, "Furnace Step", a), choose_furnace)
    e = reload(c, m)
    left = e.state.actors[LEFT]
    assert (2, 6) not in zones.difficult_cells(e, left), "ordinary ground costs the mover nothing extra"
    assert (2, 6) in zones.difficult_cells(e, e.state.actors[RIGHT]), "and only for the creature that moved"
    assert zone_subjects.allowed(e, fire, left, {"who": "hostile"}), "a hazard is not waived by a ground clause"

    before = left.current_hp
    settle(move_to(c, t, m, (4, 6)))
    e = reload(c, m)
    left = e.state.actors[LEFT]
    assert (left.position.x, left.position.y) == (4, 6)
    assert left.current_hp == before - 4, "Fire Terrain's Proficiency Bonus damage still lands"
    assert any(str(getattr(v, "condition_id", "")) == "condition:typed.burning"
               for v in left.conditions.values()), "Fire Terrain's Burning still applies"
    assert any(v.event_type == "PASSIVE_TRIGGERED" and v.payload.get("zone_id") == fire.zone_id
               for v in e.events), "the ground still called its save"


# ------------------------------------------------------------------------- one chosen creature
def test_only_the_chosen_creature_loses_its_opportunity_attack(tmp_path):
    """"one creature of your choice": the named creature cannot attack, and the other one still can.

    Two Visitors flank the Keeper, who steps past both. Only the Watching creature was chosen, so the
    Warden keeps its reaction and actually makes the attack; the Watcher is never asked.
    """
    c, t, m = table_of(tmp_path, left_talents=[F], foes=2,
                       positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}, THIRD: {"x": 4, "y": 7}})
    settle(lambda a: act(t, m, "Furnace Step", a), choose_furnace)
    e = reload(c, m)
    left, right, third = e.state.actors[LEFT], e.state.actors[RIGHT], e.state.actors[THIRD]
    denied = [row for row in right.conditions.values() if row.condition_id == NO_OA]
    assert len(denied) == 1 and denied[0].data["against"] == left.entity_id
    assert not [row for row in third.conditions.values() if row.condition_id == NO_OA], \
        "an unchosen creature keeps its own opportunity attack"

    send = move_to(c, t, m, (5, 6))
    result = send()
    prompts = []
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        prompts.append(prompt)
        result = send(use_reaction(prompt))
    assert result["status"] == "COMMITTED", result
    assert prompts, "leaving reach must still ask the unchosen creature"
    assert all(prompt["context"].get("reactor_id") != RIGHT for prompt in prompts), \
        "the chosen creature is not asked for an opportunity attack"
    assert any(prompt["context"].get("reactor_id") == THIRD for prompt in prompts), \
        "the unchosen creature is asked"

    e = reload(c, m)
    rolls = [row for row in e.events if row.event_type == "ATTACK_ROLLED" and row.target_ids == (left.entity_id,)]
    assert [row.actor_id for row in rolls] == [THIRD], \
        "the unchosen creature made its opportunity attack; the chosen one made none"
    assert any(row.event_type == "REACTION_WINDOW_OPENED" and row.actor_id == LEFT for row in e.events)

    # The denial is the printed duration: it ends with the turn that used it.
    turn(t, m, RIGHT)
    e = reload(c, m)
    assert not [row for row in e.state.actors[RIGHT].conditions.values() if row.condition_id == NO_OA]


def test_furnace_step_is_inert_without_the_talent(tmp_path):
    """No Furnace Step, no receipt: the same ground still stops a creature that does not own the row."""
    c, t, m = table_of(tmp_path, left_talents=["TAL_MAGMA_CINDERGLASS_SHARDS"],
                       left_actions=[("Pour lava", {"type": "zone"}, _molten(centered_on_self=True), "SELF")])
    settle(lambda a: act(t, m, "Pour lava", a))
    e = reload(c, m)
    left = e.state.actors[LEFT]
    assert not any(row.condition_id == magma_crust.STEP for row in left.conditions.values())
    assert (3, 6) in zones.difficult_cells(e, left)
    assert zone_subjects.allowed(e, zone_at(e, (3, 6)), left, {"who": "any"})


def _glob_attack():
    """Magma Glob's own hit effect, straight out of the rebuilt authority."""
    from pathlib import Path

    authority = Path(__file__).resolve().parents[1] / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
    return json.loads(authority.read_text())["mechanics"]["TAL_MAGMA_MAGMA_GLOB"]["effects"][0]


def test_magma_glob_patch_asks_when_the_target_stands_on_the_grid_border(tmp_path):
    """A target on the top row used to crash the patch ask: Position rejects y = -1.

    Found by an AI fight (AUTO102 seed 1021, bamboo road): Magma Glob hit a creature on the border
    row and building its eight neighbouring squares raised instead of asking for a free one.
    """
    G = "TAL_MAGMA_MAGMA_GLOB"
    border = {LEFT: {"x": 3, "y": 3}, RIGHT: {"x": 3, "y": 0}}  # the Visitor is on the very top row

    def patch(p):
        source = p["context"]["reaction_source_id"]
        if source == "choice:needle.magma_glob_expression":
            return ["Molten Terrain Patch"]
        return [p["choice"]["options"][0]["id"]]

    c, t, m = table_of(tmp_path, left_talents=[G],
                       left_actions=[("Strike", _glob_attack(), None, "HOSTILE_ENTITY")],
                       positions=border, source=G)
    _, prompts = settle(lambda a: act(t, m, "Strike", a, target_id=RIGHT), patch)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.magma_patch" for p in prompts)
    e = reload(c, m)
    zone, = magma_crust.patches(e, e.state.actors[LEFT], "molten")
    assert all(0 <= cell.x < e.grid.width and 0 <= cell.y < e.grid.height for cell in zone.affected_cells)
    assert any(cell.y == 1 for cell in zone.affected_cells), "the patch lands on the square below the border target"
