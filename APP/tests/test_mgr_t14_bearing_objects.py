"""Native object/Asset/Anchor Pole-centre regressions with sealed body geometry."""
import pytest

from combat.ext import compass_breaking_hand as compass
from combat.gate2_runtime_models import Position
from combat.object_geometry import target_cells
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_hidden_targeting import move_to
from tests.test_lock9_passage_review import checked
from tests.test_mgr_t14_bearing_gaps import (
    OWNER, THREAD, OID, TOKEN, table, bearing, declare, select_cell, choose_object,
)


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
    assert engine.state.objects[OID].component["spiritual_profile"] == {"affectable": 1, **profile}
    data = bearing(engine).data
    frozen = dict(data)
    commit(cast_sender(service, ui, mid, "Thread the Object: move object", target=OID), select_cell(4, 4))
    engine = checked(tmp_path, mid)
    assert engine.state.objects[OID].position == Position(x=4, y=4)
    assert any(e.event_type == "OBJECT_UPDATED" and e.actor_id == OWNER and OID in e.target_ids
               and "move_object" in e.source_definition_id for e in engine.events)
    assert bearing(engine).data == frozen
    # Start -> end: centre distance 17.5 -> 12.5 ft. Anchor distances are
    # 15 -> 15 ft; the moved centre gives 17.5 -> 17.5 ft. Only the frozen centre qualifies.
    move_to(ui, mid, (2, 9))
    engine = checked(tmp_path, mid)
    assert bearing(engine).data["done"] == 1
    assert engine.state.actors[OWNER].resources[TOKEN] == 1
    # Doubled absolute coordinates: the declared centre was (5, 8, .5),
    # not the anchor (4, 6), while the live centre has moved to (5, 6, .5).
    assert bearing(engine).data["ref2"] == [10, 16, 1]
    assert all(type(n) is int for n in bearing(engine).data["ref2"])
    assert tuple(compass.pole(engine, engine.state.actors[OWNER])[1]) == (10, 12, 1)


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
