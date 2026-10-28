"""MMX65r review fixes: the terrain a mounted pair actually walked through (hunt 83 #1).

Three review findings, all at the level the bug showed -- a real fight on the tabletop,
committed, reloaded from disk and mechanically replayed.

  * ``combat/ext/mounts.py`` ``_through`` relocated both halves of an Overrun through
    ``_relocate``: the mount with ``plan["path"]``, the rider with none. The rider's
    event fell back to ``_relocate``'s bare ``[start, destination]`` pair, so one charge
    was read two ways. A terrain covering only the last squares of the charge then charged
    the rider the whole straight hop, and a terrain lying between the ends was not read at
    all. ``_through`` now records the translated rider route.

  * The rider carried by its mount's own move (the mount-originated direction) received the
    same real route and the mover's ``forced``, and is covered here through a shove that
    moves the mount. Shattered Glass Terrain cuts at *any* distance
    (combat/rules/terrain.json ``move_through.min_ft: 0``), which is what makes the two
    tests below able to tell a real route from a collapsed one: on a two-hop charge the
    middle square alone is 10 feet walked, and a collapsed ``[start, end]`` pair that
    touches the same terrain reads 0 or 10.
"""

from __future__ import annotations

import copy
import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import fixed_dice

OWNER, FOE, SECOND = [FACTORY_ACTOR_PREFIX + "mmx65r-" + k for k in ("owner", "foe", "second")]
RIDER_PACKAGE = "BEASTMASTERY_BASE_RIDER_PACKAGE"
RUN_DOWN = "TAL_BEASTMASTERY_RUN_DOWN"
GRAVITIC_PUSH = "tianxia.talent.gravity.gravitic_push"

# The Rider Package's steed is a 2x2 Warhorse standing on the rider's square, so the
# rider and the mount start on the same anchor and the overrun's charge is the diagonal
# the plan takes past the adjacent foe: (2, 6) -> (3, 5) -> (4, 4).  Three anchors, two
# five-foot hops, and (3, 5) is the only anchor a piece of ground can cover without also
# covering where the charge began or ended.
START = {"x": 2, "y": 6}
FOE_SQUARE = {"x": 4, "y": 6}
SECOND_SQUARE = {"x": 17, "y": 12}
CHARGE = [(2, 6), (3, 5), (4, 4)]

# Gravitic Push "pushes the target up to 15 feet away from a point you can see", and the
# foe stands to the rider's right, so a failed save sends the pair left along row 6 over
# this ground.  Shattered Glass cuts at any distance, so a route that counted would cut
# here; a shoved creature's travel is not its own and must not.
PUSHED_GLASS = [(x, 6) for x in range(0, 4)]


def mounted(tmp_path, *, foe_talents=(), map_terrain=None, seed):
    """A real fight whose owner rides a Warhorse, with optional ground laid on the map.

    The ground is the table's own material (``arena["map_terrain"]``), the same path
    ``test_hunt32_edge.match`` uses, so nothing here is injected into a saved fight after
    the fact.
    """
    ids = [OWNER, FOE, SECOND]
    docs = [sheet([RUN_DOWN, RIDER_PACKAGE], cl=17, dc=50),
            sheet(list(foe_talents), cl=17), sheet([], cl=17)]
    for aid, doc in zip(ids, docs):
        doc["identity"]["display_name"] = aid.rsplit("-", 1)[-1].title()
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = 14
        if aid != OWNER:
            doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = 14
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True} if aid == OWNER else None)
               for aid, doc in zip(ids, docs)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    if map_terrain is not None:
        arena = copy.deepcopy(arena)
        arena["map_terrain"] = map_terrain
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:a", FOE: "team:b", SECOND: "team:b"},
        {OWNER: START, FOE: FOE_SQUARE, SECOND: SECOND_SQUARE},
        arena, [OWNER], [FOE, SECOND],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed=seed,
        display_name="MMX65r", maximum_rounds=6)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        assert commit(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    return combat, table, mid


def commit(table, mid, cid):
    """Take one table action, declining whatever it opens."""
    answers = []
    for _ in range(16):
        menu = table.state(mid)["menu"]
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"],
                           table.state(mid)["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "DECLINE"})
    raise AssertionError("too many prompts")


def press(table, mid, label, *, target=None):
    menu = table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if label in g["label"])
    option = next(o for o in group["options"] if target is None or target in (o.get("target_ids") or []))
    return table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                     table.state(mid)["last_sequence"], [])


def turn_to(table, mid, actor_id):
    for _ in range(30):
        if table.state(mid)["menu"]["actor_id"] == actor_id:
            return
        assert commit(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    raise AssertionError(f"{actor_id} never got a turn")


def reload(combat, tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


def pair(engine):
    from combat.ext import mounts

    rider = engine.state.actors[OWNER]
    return rider, mounts.mount_of(engine, rider)


def charges(engine, since):
    """Every Overrun commit, as ``(actor_id, [(x, y), ...], forced)``."""
    return [(e.actor_id, [(p["x"], p["y"]) for p in e.payload["path"]], e.payload.get("forced"))
            for e in engine.events
            if e.sequence > since and e.event_type == "MOVEMENT_COMMITTED" and e.payload.get("overrun")]


def carried(engine, since, who):
    """The ``carried_by`` commits made for one creature, with the route they recorded."""
    return [e for e in engine.events
            if e.sequence > since and e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == who
            and e.payload.get("carried_by")]


def moved(engine, since, who):
    """Every commit that placed one creature, carried or not."""
    return [e for e in engine.events
            if e.sequence > since and e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == who]


def move_through(engine, since, who):
    """Terrain reads a route and fires; the creature is the subject."""
    return [e for e in engine.events if e.sequence > since and e.event_type == "PASSIVE_TRIGGERED"
            and e.payload.get("moment") == "move_through" and who in (e.target_ids or ())]


def glass(cells):
    return {"terrain": "shattered glass terrain", "cells": [list(cell) for cell in cells], "pb": 4}


def test_an_overrun_carries_its_rider_over_the_whole_route_the_mount_walked(tmp_path, monkeypatch):
    """A charge's two halves are one walk.  The rider is recorded on the route the mount
    actually took, so ground that only the middle of that route covers is ground the rider
    walked through -- not the straight hop between the ends, and not nothing at all."""
    combat, table, mid = mounted(tmp_path, map_terrain=[glass([CHARGE[1]])],
                                 seed="MMX65R-OVERRUN-ROUTE")
    since = combat._load_session(mid).engine.state.event_sequence
    fixed_dice(monkeypatch, [19, 1])  # the mount's Athletics against the foe's
    assert press(table, mid, "Mount: Overrun (Action)", target=FOE)["status"] == "COMMITTED"

    reloaded = reload(combat, tmp_path, mid)
    engine = reloaded.engine
    rider, mount = pair(engine)
    assert mount is not None, "the pair is still together"
    booked = dict((actor, route) for actor, route, _ in charges(engine, since))
    assert booked.get(mount.entity_id) == CHARGE, \
        f"the mount walked the charge square by square: {booked.get(mount.entity_id)}"
    assert booked.get(rider.entity_id) == CHARGE, \
        ("the rider was booked on the same charge, square by square; a collapsed "
         f"start-to-end pair is the bug this fixes: {booked.get(rider.entity_id)}")
    # The route really is the mount's, shifted onto the rider's own squares.
    offset = (rider.position.x - mount.position.x, rider.position.y - mount.position.y)
    assert offset == (0, 0) or all(
        (x + offset[0], y + offset[1]) in CHARGE for x, y in booked[mount.entity_id])

    assert move_through(engine, since, mount.entity_id), \
        "the mount's own charge crossed the glass, so the ground is on the route"
    assert move_through(engine, since, OWNER), \
        ("the rider was carried over the same glass and never resolved it: without the "
         "translated route the rider's event was one hop between the ends, which touches no "
         "glass at all")
    assert all(forced is not True for _, _, forced in charges(engine, since)), \
        "an Overrun is movement the rider chose"

    reloaded.engine._assert_invariants()
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_a_mount_pushed_over_ground_carries_its_rider_on_that_route_without_charging_the_ground(tmp_path, monkeypatch):
    """The other carry direction, and the exclusion that goes with it.

    A shove moves the mount, so the mount is the mover of record and the rider is the one
    carried: its event takes the mount's route and the mount's ``forced``.  Shattered Glass
    cuts at any distance, so a carried route that counted would cut; a pushed creature's
    travel is not its own and must not (combat/zones.py
    ``_movement_distance_through_zone`` keeps ``forced`` and ``teleport``).
    """
    combat, table, mid = mounted(tmp_path, foe_talents=[GRAVITIC_PUSH],
                                 map_terrain=[glass(PUSHED_GLASS)],
                                 seed="MMX65R-FORCED-CARRY")
    rider, mount = pair(combat._load_session(mid).engine)
    mount_id = mount.entity_id
    turn_to(table, mid, FOE)
    since = combat._load_session(mid).engine.state.event_sequence
    fixed_dice(monkeypatch, [1, 20])  # the mount fails the push (15 feet), the rider passes the fall save
    assert press(table, mid, "Gravitic Push", target=mount_id)["status"] == "COMMITTED"

    reloaded = reload(combat, tmp_path, mid)
    engine = reloaded.engine
    rider, mount = pair(engine)
    assert mount is not None, "the pair is still together after the push"
    moved_mount = [e for e in moved(engine, since, mount_id) if e.payload.get("forced")]
    assert moved_mount, \
        f"the mount was pushed: {[e.payload for e in moved(engine, since, mount_id)]}"
    pushed = moved_mount[0].payload
    assert pushed.get("forced") is True, "a shove is movement against the mount's will"
    rides = carried(engine, since, OWNER)
    assert rides, "the rider was carried by its mount's own move"
    ride = rides[0].payload
    route = [(p["x"], p["y"]) for p in ride["path"]]
    pushed_route = [(p["x"], p["y"]) for p in pushed["path"]]
    assert len(pushed_route) >= 3, \
        f"the shove has to cover more than one step to tell a route from a hop: {pushed_route}"
    assert route == pushed_route, \
        f"the rider is booked on the route the mount was pushed along, not one hop: {route}"
    assert any(cell in PUSHED_GLASS for cell in route), \
        f"the shove really did carry the pair across the glass, so the exclusion below bites: {route}"
    assert ride.get("forced") is True, \
        "the rider inherits the mover's forced: it did not choose to be shoved either"

    assert (rider.position.x, rider.position.y) in PUSHED_GLASS, \
        ("the pair came to rest inside the glass, so the ground below was really under them "
         f"and not merely near the shove: {(rider.position.x, rider.position.y)}")
    assert not move_through(engine, since, OWNER), \
        ("a shoved rider's travel is involuntary, so it never charges a ground it was "
         "pushed across -- it still enters what it lands in")
    assert not move_through(engine, since, mount_id), \
        "and the same is true of the mount that was pushed"
    engine._assert_invariants()
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"
