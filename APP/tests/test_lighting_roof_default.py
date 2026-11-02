"""ROOFLIGHT1 (owner ruling 2026-11-02, docs/specs/LIGHTING_SPEC.md §3.2, §4.2 E17): a roofed square with no declared
indoor level takes the level its time of day gives, and the map's or the fight's own choices still win over it.

Every level below is read from a fight saved and cold-reloaded on a real map, the same path the table uses.
"""
import pytest

from combat import lighting
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload

ROOF = [{"shape": "rect", "points": [[6, 3], [13, 9]], "blocks": "sight", "filled": False, "height_ft": 20}]
HALL = [{"shape": "rect", "points": [[4, 2], [20, 12]], "blocks": "sight", "filled": False, "height_ft": 20}]
OUT_OF_THE_WAY = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 4, "y": 2}}


def _engine(tmp_path, document):
    _, _, mid = fight(tmp_path, document, senses=[], positions=OUT_OF_THE_WAY)
    return reload(tmp_path, mid)


@pytest.mark.parametrize(("time_of_day", "under_roof"), [
    ("day", lighting.DIM), ("dawn", lighting.DARK), ("dusk", lighting.DARK),
    ("night", lighting.DARK), ("underground", lighting.DARK),
])
def test_a_roof_takes_the_level_its_time_of_day_gives_when_none_is_declared(tmp_path, time_of_day, under_roof):
    engine = _engine(tmp_path, map_document(20, 14, ambient=ambient_light(time_of_day), walls=ROOF))
    assert lighting.ambient(engine)["indoor_level"] == under_roof
    assert (9, 6) in lighting._roofed_cells(engine)
    assert lighting.base(engine, 9, 6) == under_roof       # under the roof
    assert lighting.base(engine, 3, 3) == lighting.ambient(engine)["level"]   # the open ground keeps the time's level


def test_an_explicit_indoor_level_wins_over_the_derived_one(tmp_path):
    # A night map whose roof the GM lit: the authored Bright stays, not the Dark that night would derive.
    engine = _engine(tmp_path, map_document(20, 14, ambient=ambient_light("night", indoor_level="bright"), walls=ROOF))
    assert lighting.ambient(engine)["indoor_level"] == lighting.BRIGHT
    assert lighting.base(engine, 9, 6) == lighting.BRIGHT
    assert lighting.base(engine, 3, 3) == lighting.DARK


def test_a_torch_under_a_roof_lights_its_radius_and_the_rest_of_the_roof_keeps_the_derived_level(tmp_path):
    # E17: a day map, a roofed hall with no indoor level, and a torch (B20/D40) under the roof.
    engine = _engine(tmp_path, map_document(24, 14, ambient=ambient_light("day"), walls=HALL, lights=[light(9, 6)]))
    assert lighting.base(engine, 9, 6) == lighting.BRIGHT      # the torch's own square
    assert lighting.base(engine, 13, 6) == lighting.BRIGHT     # 20 ft from the torch
    assert lighting.base(engine, 19, 6) == lighting.DIM        # beyond the torch's bright radius, under the roof
    assert lighting.base(engine, 1, 1) == lighting.BRIGHT      # open sky on a day map stays Bright


def test_an_ambient_region_paints_over_the_derived_roof_level(tmp_path):
    document = map_document(20, 14, ambient=ambient_light("day"), walls=ROOF, regions=[
        {"id": "pit", "name": "Dark pit", "level": "dark", "cells": [[9, 6]]}])
    engine = _engine(tmp_path, document)
    assert lighting.base(engine, 8, 6) == lighting.DIM         # the rest of the roof: the derived level
    assert lighting.base(engine, 9, 6) == lighting.DARK        # the region's own square wins over the roof
