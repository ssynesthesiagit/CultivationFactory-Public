"""A1-P4a: Terraced Ascent (Earth foundation) creates the printed eight-space run.

Before this lane the reviewed record parsed the printed body into no effect at
all: `effects: []`, `area: null`, and the whole pasted source block sat in
`riders[1]`. These tests hold the repair: one lasting zone effect quoting the
printed body, eight connected 5-foot spaces (clipped, never grown), and the
printed 30-foot ascent limit recorded on the created zone's own profile.

The fight still has no elevation movement (A1-P4b): the ground grid gets no
height and the actor's movement is not repriced.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import zones
from combat.ext import terraced_ascent as ascent
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.ascent"
SOURCE = ROOT / "authority/typed_mechanics/reviewed_final.d/review_sw-earth.json"
AUTHORITY = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
BODY = ("Create stairs, ramps, terraces, footholds, or a compacted slope across a solid surface. "
        "The structure covers up to eight 5-foot spaces. It may ascend or descend up to 30 feet total, "
        "provided there is a solid surface or terrain mass to shape.")
RIDER = ("Terraced Ascent cannot create a freestanding bridge across empty air unless you also have a "
         "feature that permits raised Earth structures.")
PASTED = "### Terraced Ascent"


def _bundle():
    return compile_character({**SHEET, "equipment": [],
                              "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.earth"],
                                                      "learned_talent_record_ids": ["TAL_EARTH_TERRACED_ASCENT"]}},
                             actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="ASCENT", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _cast(engine):
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Terraced Ascent"))
    engine.execute_intent(ActionIntent(intent_id="ascent", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    return candidate


def _connected(cells) -> bool:
    """One face-connected run: every square reachable from the first by 5-foot steps."""
    seen = {(cells[0].x, cells[0].y)}
    stack = [cells[0]]
    while stack:
        cell = stack.pop()
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            step = (cell.x + dx, cell.y + dy)
            if step in {(p.x, p.y) for p in cells} and step not in seen:
                seen.add(step)
                stack.append(Position(x=step[0], y=step[1]))
    return len(seen) == len({(p.x, p.y) for p in cells})


def test_the_creation_is_one_last_duration_zone_of_eight_connected_spaces():
    engine = _engine(_bundle())
    _cast(engine)
    [zone] = zones.typed_zones(engine)
    assert zone.active and zone.duration_rounds == 100 and not zone.concentration_link  # 10 minutes
    assert len(zone.affected_cells) == 8 and _connected(zone.affected_cells)
    assert {p.z for p in zone.affected_cells} == {0}
    assert zone.trigger_profile["creation_kind"] == "ascent"
    assert zone.trigger_profile["rise_ft"] == 30


def test_the_structure_is_created_without_moving_anyone_or_repricing_the_ground():
    engine = _engine(_bundle())
    movement, blocked = engine.state.actors[ME].movement_remaining_ft, set(engine.grid.blocked)
    heights = dict(engine.grid.terrain_heights)
    _cast(engine)
    assert engine.state.actors[ME].movement_remaining_ft == movement
    assert set(engine.grid.blocked) == blocked and engine.grid.terrain_heights == heights
    assert not engine.grid.finite_heights  # no elevation was added for the run
    assert "height_ft" not in zones.typed_zones(engine)[0].trigger_profile


def test_more_than_eight_candidate_spaces_are_clipped_to_one_connected_eight():
    cells = tuple(Position(x=10 + step, y=6) for step in range(12))
    kept = ascent.contiguous(cells, Position(x=10, y=6))
    assert len(kept) == 8 and _connected(kept) and kept[0] == cells[0]


def test_a_split_candidate_keeps_one_connected_component_of_at_most_eight():
    cells = (*[Position(x=10 + step, y=6) for step in range(6)],
             *[Position(x=10 + step, y=60) for step in range(6)])
    kept = ascent.contiguous(cells, Position(x=12, y=6))
    assert len(kept) == 6 and _connected(kept)
    assert all(cell.y == 6 for cell in kept)


@pytest.mark.parametrize("declared,recorded", [(45, 30), (30, 30), (25, 25), (0, 0)])
def test_the_printed_ascent_limit_is_recorded_and_clamped_at_thirty_feet(declared, recorded):
    engine = _engine(_bundle())
    _cast(engine)
    [zone] = zones.typed_zones(engine)
    refined = ascent.terraced_ascent(zone, SimpleNamespace(typed={"effects": [
        {"type": "zone", "rise_ft": declared, "area": {"shape": "cube", "size_ft": 5, "blocks": 8}}]}))
    assert refined.trigger_profile["rise_ft"] == recorded and refined.trigger_profile["creation_kind"] == "ascent"


def test_an_area_that_names_no_ascent_stays_inert():
    engine = _engine(_bundle())
    _cast(engine)
    [zone] = zones.typed_zones(engine)
    assert ascent.terraced_ascent(zone, SimpleNamespace(typed={"effects": [{"type": "zone"}]})) is None


@pytest.mark.parametrize("path", [SOURCE, AUTHORITY])
def test_the_printed_body_is_the_record_and_the_pasted_block_is_gone(path):
    record = json.loads(path.read_text(encoding="utf-8"))["mechanics"]["TAL_EARTH_TERRACED_ASCENT"]
    [effect] = [e for e in record["effects"] if e.get("type") == "zone"]
    assert effect["evidence"] == BODY
    assert effect["area"]["blocks"] == 8 and effect["area"]["size_ft"] == 5
    assert effect["rise_ft"] == 30
    assert record["riders"] == [RIDER]
    blob = json.dumps(record)
    assert PASTED not in blob and "Action Type:" not in blob and "Prerequisite:" not in blob
