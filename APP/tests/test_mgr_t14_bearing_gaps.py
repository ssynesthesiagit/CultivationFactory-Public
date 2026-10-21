"""Public native regressions for object-centred Poles and voluntary teleport Bearings.

Portable sheets acquire the printed features. Pole, Bearing, object movement and
teleport choices use the table transport; no progress or ownership is injected.
"""
import json
import zipfile

import pytest

from combat import typed_executor as te
from combat.ext import compass_breaking_hand as compass, needle
from combat.factory_compiler import compile_character
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
    bundles = []
    for pid, ids in (("aaaaaaaa", [FEATURE, MIND, *extra]), ("ffffffff", [MIND, *foe_extra])):
        doc = sheet(ids, cl=3, primary="Resonance", key="WIS", name=pid)
        doc["identity"]["path"] = "Spirit Awakening"
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundles.append(compile_character(doc, actor_id="actor:factory." + pid))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({
        "display_name": "Bearing gaps hall", "width_squares": 22, "height_squares": 14,
        "walls": list(walls), "objects": list(objects),
        "starts": {"team1": [list(start)], "team2": [list(foe)]},
    })
    # The editor's legacy _objects normalizer drops explicit body dimensions
    # and spiritual profiles. The native sealed battlefield placement input
    # accepts them; seed() validates them and journals the actual objects.
    arena = {**service.factory_arenas(include_retired=True)["battlefield:map.bearing-gaps-hall"],
             "map_objects": [dict(row) for row in objects]}
    mid = service._finish_factory_match(
        bundles, [OWNER, FOE], {OWNER: "team:a", FOE: "team:b"},
        {OWNER: {"x": start[0], "y": start[1]}, FOE: {"x": foe[0], "y": foe[1]}},
        arena, [OWNER], [FOE], control_modes={OWNER: "MANUAL", FOE: "MANUAL"},
        match_seed="MGR-T14-BEARING-GAPS", display_name="Bearing gaps hall", maximum_rounds=6,
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


def test_native_pole_teleport_keeps_one_direction_band_without_revealing_its_square(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [1] * 400)
    service, ui, mid = table(tmp_path, foe=(6, 6), foe_extra=[EMPTY])
    commit(cast_sender(service, ui, mid, "Choose Pole", target=FOE))
    commit(cast_sender(service, ui, mid, "Mind Spike", target=FOE))
    end_turn(ui, mid)
    engine = checked(tmp_path, mid)
    assert te.bears_mark(engine.state.actors[FOE], OWNER, "Resonance")

    def senses(engine):
        return [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"
                and e.payload.get("log", "").startswith("Pole sense:")]

    before = len(senses(engine))
    prompts = commit(cast_sender(service, ui, mid, "Empty Step"), select_cell(10, 6))
    assert any(p["context"]["reactor_id"] == FOE for p in prompts)
    engine = checked(tmp_path, mid)
    assert engine.state.actors[FOE].position == Position(x=10, y=6)
    assert len(senses(engine)) == before + 1
    assert "30 to 60 feet away" in senses(engine)[-1].payload["log"]
    assert "10,6" not in senses(engine)[-1].payload["log"]
