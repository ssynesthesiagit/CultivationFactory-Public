"""Public native regressions for object-centred Poles and voluntary teleport Bearings.

Portable sheets acquire the printed features. Pole, Bearing, object movement and
teleport choices use the table transport; no progress or ownership is injected.
"""
import json
import zipfile

import pytest

from combat.ext import compass_breaking_hand as compass, needle
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.object_geometry import target_cells
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_hidden_targeting import move_to
from tests.test_lock9_passage_review import checked
from tests.test_mgr_t14_ling_trad_bearing_footwork import (
    OWNER, FOE, FEATURE, MIND, POLE, BEARING, end_turn, to_actor,
)

EMPTY = "TAL_VOID_EMPTY_STEP"
THREAD = "PUPPETRY_BASE_THREAD_THE_OBJECT"
DISPLACE = "tianxia.talent.space.spatial_displacement"
OID = "object:map.1"
TOKEN = "resource:named.bearing_approach"


def table(tmp_path, *, objects=(), walls=(), start=(1, 6), foe=(10, 12), extra=(), foe_extra=()):
    for pid, ids in (("aaaaaaaa", [FEATURE, MIND, *extra]), ("ffffffff", [MIND, *foe_extra])):
        doc = sheet(ids, cl=3, primary="Resonance", key="WIS", name=pid)
        doc["identity"]["path"] = "Spirit Awakening"
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({
        "display_name": "Bearing gaps hall", "width_squares": 22, "height_squares": 14,
        "walls": list(walls), "objects": list(objects),
        "starts": {"team1": [list(start)], "team2": [list(foe)]},
    })
    mid = service.create_factory_match(
        project_ids=["aaaaaaaa"], opponent_actor_ids=[FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"},
        arena_id="battlefield:map.bearing-gaps-hall", match_seed="MGR-T14-BEARING-GAPS",
    )["match_id"]
    ui = TabletopService(service, tmp_path)
    to_actor(ui, mid, OWNER)
    return service, ui, mid


def bearing(engine):
    return next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == BEARING)


def declare(ui, mid, kind="approach"):
    end_turn(ui, mid)
    end_turn(ui, mid, bearing=kind)


def select_cell(x, y):
    wanted = needle.cell_id(Position(x=x, y=y))

    def pick(prompt):
        options = {o["id"] for o in prompt["choice"]["options"]}
        assert wanted in options, (wanted, options)
        return wanted, True
    return pick


def choose_object(service, ui, mid):
    prompts = commit(cast_sender(service, ui, mid, "Choose Pole: an object"),
                     lambda p: (OID, True))
    assert prompts and OID in {o["id"] for o in prompts[0]["choice"]["options"]}
    pole = next(c for c in checked(service.userdata_root, mid).state.actors[OWNER].conditions.values()
                if c.condition_id == POLE)
    assert pole.data["object"] == OID


@pytest.mark.parametrize("profile,rotation", [({}, 0), ({"cultivation_asset": 1}, 90),
                                                ({"external_anchor": 1}, 0)])
def test_object_pole_records_exact_center_then_freezes_it_after_real_move(tmp_path, profile, rotation):
    # Rotation changes explicit dimensions; both placements occupy 2 by 4 cells.
    obj = {"id": 1, "x": 4, "y": 6, "kind": "custom", "name": "Light practice frame",
           "material": "wood", "size": "medium", "weight_lb": 1, "blocks": False,
           "width_cells": 4 if rotation else 2, "length_cells": 2 if rotation else 4,
           "rotation": rotation, "spiritual_profile": {"affectable": 1, **profile}}
    service, ui, mid = table(tmp_path, objects=[obj], extra=[THREAD])
    choose_object(service, ui, mid)
    declare(ui, mid)
    engine = checked(tmp_path, mid)
    assert len(target_cells(engine, engine.state.objects[OID])) == 8
    data = bearing(engine).data
    # Doubled absolute cell coordinates: centre (5, 8, .5), not anchor (4, 6).
    assert data["ref2"] == [10, 16, 1]
    assert all(type(n) is int for n in data["ref2"])
    frozen = dict(data)
    commit(cast_sender(service, ui, mid, "Thread the Object: move object", target=OID), select_cell(6, 6))
    engine = checked(tmp_path, mid)
    assert engine.state.objects[OID].position == Position(x=6, y=6)
    assert any(e.event_type == "OBJECT_UPDATED" and e.actor_id == OWNER and OID in e.target_ids
               and "move_object" in e.source_definition_id for e in engine.events)
    assert bearing(engine).data == frozen
    # Start -> end: centre distance 17.5 -> 12.5 ft. Anchor distances are
    # 15 -> 15 ft; the moved centre would be 22.5 ft. Only the frozen centre qualifies.
    move_to(ui, mid, (2, 9))
    engine = checked(tmp_path, mid)
    assert bearing(engine).data["ref2"] == [10, 16, 1]
    assert bearing(engine).data["done"] == 1
    assert engine.state.actors[OWNER].resources[TOKEN] == 1


@pytest.mark.parametrize("fixed", [False, True])
def test_single_square_and_fixed_space_poles_keep_their_reference(tmp_path, fixed):
    objects = [{"id": 1, "x": 4, "y": 6, "kind": "custom", "name": "Ordinary block"}]
    service, ui, mid = table(tmp_path, objects=objects)
    if fixed:
        commit(cast_sender(service, ui, mid, "Choose Pole: a space", at=(4, 6)))
    else:
        choose_object(service, ui, mid)
    declare(ui, mid)
    move_to(ui, mid, (3, 6))
    engine = checked(tmp_path, mid)
    assert bearing(engine).data["done"] == 1
    assert engine.state.actors[OWNER].resources[TOKEN] == 1
    if fixed:
        assert bearing(engine).data["ref"] == [4, 6]
        assert compass.pole(engine, engine.state.actors[OWNER])[1] == Position(x=4, y=6)


def test_pole_object_selection_uses_center_range_not_anchor_or_size_label(tmp_path):
    service, ui, mid = table(tmp_path, start=(0, 6), objects=[
        {"id": 1, "x": 12, "y": 6, "kind": "custom", "name": "Wide frame", "size": "tiny",
         "width_cells": 2, "length_cells": 4, "blocks": False},
        {"id": 2, "x": 12, "y": 10, "kind": "custom", "name": "Single space", "size": "large"},
    ])
    offered = []

    def pick(prompt):
        offered.extend(o["id"] for o in prompt["choice"]["options"])
        return "object:map.2", True
    commit(cast_sender(service, ui, mid, "Choose Pole: an object"), pick)
    assert offered == ["object:map.2"], "the frame's centre is 62.5 feet away; the ordinary cell is 60 feet"
    checked(tmp_path, mid)


def test_object_depart_step_is_farther_from_current_center_not_anchor(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [20] * 400)
    service, ui, mid = table(tmp_path, start=(3, 6), objects=[
        {"id": 1, "x": 4, "y": 6, "kind": "custom", "name": "Practice frame",
         "width_cells": 2, "length_cells": 4, "blocks": False, "hp": 200, "ac": 10}])
    choose_object(service, ui, mid)
    declare(ui, mid, "depart")
    move_to(ui, mid, (3, 4))  # 10 feet; completes Depart around centre (5, 8).
    move_to(ui, mid, (3, 6))  # Return to strike range after the one completion.
    commit(cast_sender(service, ui, mid, "Attack an object", target=OID), select_cell(3, 5))
    engine = checked(tmp_path, mid)
    assert engine.state.actors[OWNER].position == Position(x=3, y=5)
    assert engine.state.actors[OWNER].turn_flags["compass_strike_used"] is True
    # This step is 7.5 -> 12.5 feet from the current centre; anchor-based
    # distance stays 5 feet, which used to hide the legal step from the player.


@pytest.mark.parametrize("feet", [10, 5])
def test_native_empty_step_counts_endpoint_distance_once_and_replays(tmp_path, monkeypatch, feet):
    fixed_dice(monkeypatch, [1] * 400)
    service, ui, mid = table(tmp_path, foe=(6, 6), extra=[EMPTY])
    commit(cast_sender(service, ui, mid, "Choose Pole", target=FOE))
    declare(ui, mid)
    end = (1 + feet // 5, 6)
    prompts = commit(cast_sender(service, ui, mid, "Empty Step"), select_cell(*end))
    assert any(p["context"]["reaction_source_id"] == "choice:needle.teleport_destination" for p in prompts)
    engine = checked(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    moves = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER]
    assert len(moves) == 1 and moves[0].payload.get("teleport") is True
    # Native teleports have just two endpoints, never intervening path cells.
    assert len(moves[0].payload["path"]) == 2 and moves[0].payload["cost_ft"] == 0
    assert engine.grid.distance_ft(Position(x=1, y=6), actor.position) == feet
    assert bearing(engine).data["moved"] == feet
    assert bearing(engine).data["done"] == int(feet >= 10)
    assert actor.resources.get(TOKEN, 0) == int(feet >= 10)
    if feet < 10:
        assert not actor.turn_flags.get("compass_strike_pending")
        return
    assert actor.turn_flags["compass_strike_pending"] == "approach"
    # The actual next Martial Strike consumes the one rider; later ordinary
    # movement cannot produce another token, completion or rider this turn.
    commit(cast_sender(service, ui, mid, "Mind Spike", target=FOE))
    move_to(ui, mid, (4, 7))
    engine = checked(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.turn_flags["compass_strike_used"] is True
    assert actor.resources[TOKEN] == 1
    assert len([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
                and e.source_definition_id == FEATURE]) == 1
    assert len([e for e in engine.events if "completes its Approach Bearing" in e.payload.get("log", "")]) == 1


def test_native_teleport_cannot_cross_source_forbidden_total_cover(tmp_path):
    service, ui, mid = table(tmp_path, foe=(6, 6), extra=[EMPTY], walls=[
        {"shape": "rect", "points": [[3, 0], [4, 14]], "filled": True}])
    # Use a perceived fixed space on our side; the wall blocks Empty Step's
    # source-required sight/Total Cover, without making the Pole dormant.
    commit(cast_sender(service, ui, mid, "Choose Pole: a space", at=(2, 6)))
    declare(ui, mid, "depart")
    offered = []

    def decline(prompt):
        offered.extend(o["id"] for o in prompt["choice"]["options"])
        return None, False
    commit(cast_sender(service, ui, mid, "Empty Step"), decline)
    assert offered and needle.cell_id(Position(x=4, y=6)) not in offered
    engine = checked(tmp_path, mid)
    assert engine.state.actors[OWNER].position == Position(x=1, y=6)
    assert bearing(engine).data["done"] == 0
    assert engine.state.actors[OWNER].resources.get(compass.TOKEN["depart"], 0) == 0
    assert not any(e.event_type == "MOVEMENT_COMMITTED" and e.payload.get("teleport") for e in engine.events)


def test_teleport_out_and_walk_back_needs_meaningful_hostile_progress(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [1] * 400)
    service, ui, mid = table(tmp_path, foe=(6, 6), extra=[EMPTY])
    commit(cast_sender(service, ui, mid, "Choose Pole", target=FOE))
    declare(ui, mid, "orbit")
    commit(cast_sender(service, ui, mid, "Empty Step"), select_cell(3, 6))
    move_to(ui, mid, (1, 6))
    engine = checked(tmp_path, mid)
    assert bearing(engine).data["moved"] == 20
    assert bearing(engine).data["done"] == 0
    assert engine.state.actors[OWNER].resources.get(compass.TOKEN["orbit"], 0) == 0
    commit(cast_sender(service, ui, mid, "Mind Spike", target=FOE),
           lambda p: (p["choice"]["options"][0]["id"], True))
    engine = checked(tmp_path, mid)
    assert bearing(engine).data["objective_advanced"] == 1
    assert bearing(engine).data["done"] == 1
    assert engine.state.actors[OWNER].resources[compass.TOKEN["orbit"]] == 1
    assert engine.state.actors[OWNER].turn_flags["compass_strike_used"] is True


def test_native_other_creatures_forced_displacement_does_not_award_a_token(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [1] * 400)
    service, ui, mid = table(tmp_path, foe=(6, 6), foe_extra=[DISPLACE])
    commit(cast_sender(service, ui, mid, "Choose Pole", target=FOE))
    declare(ui, mid)
    assert bearing(checked(tmp_path, mid)).data["done"] == 0
    end_turn(ui, mid)  # The other creature owns and chooses the forced relocation.
    commit(cast_sender(service, ui, mid, "Spatial Displacement", target=OWNER), select_cell(3, 6))
    engine = checked(tmp_path, mid)
    assert engine.state.actors[OWNER].position == Position(x=3, y=6)
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.payload.get("teleport") for e in engine.events)
    assert not any(c.condition_id == BEARING for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources.get(TOKEN, 0) == 0
