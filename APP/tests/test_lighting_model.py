"""The light model on real maps through the real table: docs/specs/LIGHTING_SPEC.md §2, §4.1 and §4.2 E1-E16.

Every level below is read from the engine of a fight that was saved and cold-reloaded, so the answer comes from the map
document, the table's own start path and the model's per-pass cache -- not from a hand-built field.
"""
import pytest

from combat import lighting
from combat.tabletop import TabletopError, normalize_map
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document, payload
from tests.worker2_support import reload

DAY, NIGHT = ambient_light("day"), ambient_light("night")
DARKVISION = [{"sense": "darkvision", "range_ft": 60}]
OUT_OF_THE_WAY = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 4, "y": 2}}


def levels(engine, cells):
    return [lighting.base(engine, x, y) for x, y in cells]


def test_the_three_levels_are_the_specs_numbers():
    assert (lighting.BRIGHT, lighting.DIM, lighting.DARK) == (2, 1, 0)
    assert [lighting.level_name(level) for level in (2, 1, 0)] == ["bright", "dim", "dark"]
    assert lighting.level_name(0) == "dark" and lighting.level_name(2) == "bright"


def test_a_source_gives_bright_inside_bright_ft_and_dim_to_dim_ft():
    assert lighting.radii({"bright_ft": 20, "dim_ft": 40}) == (20, 40)
    assert lighting.radii({"radius_ft": 30, "level": "bright"}) == (30, 30)
    assert lighting.radii({"radius_ft": 30, "level": "dim"}) == (0, 30)
    assert lighting.radii({"name": "a lamp with no radius"}) == (0, 0)
    with pytest.raises(ValueError):
        lighting.LightSource("test", "Torch", frozenset({(0, 0)}), bright_ft=40, dim_ft=20)
    with pytest.raises(ValueError):
        lighting.LightSource("test", "Region", frozenset({(0, 0)}), level=7)


def test_the_map_document_refuses_a_light_it_cannot_mean():
    with pytest.raises(TabletopError) as refused:
        normalize_map({"width_squares": 10, "height_squares": 10,
                       "lights": [{"x": 1, "y": 1, "bright_ft": 40, "dim_ft": 20}]})
    assert refused.value.code == "MAP_LIGHT_INVALID"
    with pytest.raises(TabletopError):
        normalize_map({"width_squares": 10, "height_squares": 10,
                       "ambient_regions": [{"level": "twilight", "cells": [[1, 1]]}]})
    saved = normalize_map({"width_squares": 10, "height_squares": 10,
                           "ambient": {"time_of_day": "night"},
                           "lights": [{"x": 1, "y": 1, "bright_ft": 20, "dim_ft": 40}]})
    assert saved["ambient"] == {"time_of_day": "night", "level": lighting.DARK}
    assert [row["dim_ft"] for row in saved["lights"]] == [40]


def test_a_map_with_no_light_data_answers_bright_and_sends_nothing(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(12, 10, walls=[
        {"shape": "line", "points": [[5, 2], [5, 9]], "blocks": "sight"}]), senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    assert lighting.declared(engine) is False
    assert lighting.field(engine) == {}
    assert table.state(mid, fog=True)["light"] == {}      # the table sends no block at all
    assert all(lighting.base(engine, x, y) == lighting.BRIGHT for x in range(12) for y in range(10))


def test_worked_example_e1_day_on_an_open_map(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(20, 12, ambient=DAY), senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert lighting.base(engine, 10, 6) == lighting.BRIGHT
    assert lighting.seen_level(engine, owner, lighting._position_of((10, 6))) == lighting.BRIGHT
    assert lighting.perception_mode(engine, owner) == "NORMAL"
    assert lighting.obscured(engine, owner, owner.position) is False


def test_worked_examples_e2_e7_e8_e9_night_with_no_sources(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(20, 12, ambient=NIGHT), senses=[], ally_senses=DARKVISION,
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}})
    engine = reload(tmp_path, mid)
    owner, ally, foe = (engine.state.actors[i] for i in (OWNER, ALLY, FOE))
    assert levels(engine, [(9, 2), (2, 2)]) == [lighting.DARK, lighting.DARK]
    # E7: no Darkvision, 35 feet away, the foe is unseen (spec §2.5, §2.8).
    assert lighting.seen_level(engine, owner, foe.position) == lighting.DARK
    # E8: Darkvision 60 raises the same square one step, to Dim.
    assert lighting.seen_level(engine, ally, foe.position) == lighting.DIM
    # E9: the two viewers' own light answers differ on one pass, and so does the table's payload.
    owner_view, ally_view = lighting.views(engine, [owner, ally])
    assert owner_view[(9, 2)] == lighting.DARK and ally_view[(9, 2)] == lighting.DIM
    assert payload(table, mid, OWNER)["cells"] != payload(table, mid, ALLY)["cells"]


def test_worked_examples_e3_e4_e5_e12_e13_sources_take_the_maximum(tmp_path):
    document = map_document(42, 14, ambient=NIGHT,
                            lights=[light(6, 7),                                   # a torch: 20/40
                                    light(6, 1, bright_ft=0, dim_ft=5, name="Candle", light_id="c1"),
                                    light(8, 1, bright_ft=0, dim_ft=5, name="Candle", light_id="c2"),
                                    light(30, 7, name="Banked Ember")])            # 20/40, out of the torch's reach
    combat, table, mid = fight(tmp_path, document, senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    # E3/E4/E5: 15 ft Bright, 30 ft Dim, 45 ft Dark from the torch, and the torch's own square is lit.
    assert levels(engine, [(6, 7), (9, 7), (12, 7), (15, 7)]) == [lighting.BRIGHT, lighting.BRIGHT, lighting.DIM,
                                                                  lighting.DARK]
    # E12: two candles five feet apart: the square between them is Dim from both and never Bright.
    assert levels(engine, [(7, 1), (6, 1)]) == [lighting.DIM, lighting.DIM]
    # E13: the same rings from a second source, with no help from the first.
    assert levels(engine, [(32, 7), (36, 7), (39, 7)]) == [lighting.BRIGHT, lighting.DIM, lighting.DARK]
    assert levels(engine, [(18, 7)]) == [lighting.DARK]      # between the two: neither reaches


def test_worked_example_e14_a_carried_light_rides_its_bearer(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(24, 12, ambient=NIGHT), senses=[],
                               positions={OWNER: {"x": 2, "y": 6}, ALLY: {"x": 3, "y": 6}, FOE: {"x": 14, "y": 6}})
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, lighting.LIGHT, "test:lighting.ember", OWNER, expires_on=None,
                            data={"name": "Revealing Ember", "bright_ft": 0, "dim_ft": 5})
    assert [source.name for source in lighting.sources(engine) if source.following == FOE] == ["Revealing Ember"]
    assert levels(engine, [(14, 6), (15, 6), (16, 6)]) == [lighting.DIM, lighting.DIM, lighting.DARK]
    assert [row["name"] for row in lighting.own_light(engine, foe)] == ["Revealing Ember"]
    assert lighting.own_light(engine, engine.state.actors[OWNER]) == []


def test_worked_example_e15_a_sealed_roof_holds_its_own_level(tmp_path):
    walls = [{"shape": "rect", "points": [[6, 3], [13, 9]], "blocks": "sight", "filled": False, "height_ft": 20}]
    combat, table, mid = fight(tmp_path, map_document(20, 14, ambient=ambient_light("day", indoor_level="dark"),
                                                      walls=walls), senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    roofed = lighting._roofed_cells(engine)
    assert roofed and (9, 6) in roofed and (3, 3) not in roofed
    assert lighting.base(engine, 9, 6) == lighting.DARK      # under the roof, at noon
    assert lighting.base(engine, 3, 3) == lighting.BRIGHT    # the open sky outside it


def test_worked_example_e15_a_torch_under_a_sealed_roof_lights_its_radius(tmp_path):
    walls = [{"shape": "rect", "points": [[4, 2], [20, 12]], "blocks": "sight", "filled": False, "height_ft": 20}]
    combat, table, mid = fight(tmp_path, map_document(24, 14, ambient=ambient_light("day", indoor_level="dark"),
                                                      walls=walls, lights=[light(9, 6)]),
                               senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    roofed = lighting._roofed_cells(engine)
    assert roofed and (9, 6) in roofed and (1, 1) not in roofed
    assert lighting.base(engine, 9, 6) == lighting.BRIGHT    # a torch lights its own square under the roof
    assert lighting.base(engine, 13, 6) == lighting.BRIGHT   # its bright radius (20 ft) inside the room
    assert lighting.base(engine, 14, 6) == lighting.DIM      # then its dim radius (40 ft)
    assert lighting.base(engine, 1, 1) == lighting.BRIGHT    # the open sky outside the room


def test_worked_example_e16_an_ambient_region_paints_its_squares(tmp_path):
    document = map_document(20, 12, ambient=DAY, regions=[
        {"id": "tunnel", "name": "Dark tunnel", "level": "dark", "cells": [[6, 4], [7, 4], [8, 4]]}])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    assert levels(engine, [(6, 4), (7, 4), (8, 4), (9, 4)]) == [lighting.DARK] * 3 + [lighting.BRIGHT]
