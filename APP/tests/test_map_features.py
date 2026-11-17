"""MAPPARTIAL1 (owner 2026-11-13): map ground drawn as shapes ("features") with partial squares, and the one rule
that decides each square: it counts as a kind of terrain when MORE than half of it is that terrain.

Rule cases, Sunken Marsh (the re-authored proof), and three generic checks over every shipped map."""
import json
from pathlib import Path

import pytest

from combat import tabletop
from combat.canonical import canonical_sha256
from combat.tabletop import normalize_map, rasterize, to_battlefield

ROOT = Path(__file__).resolve().parents[1]
MAPS = sorted((ROOT / "combat/maps").glob("*.json"))
MARSH = ROOT / "combat/maps/builtin-realm-sunken-marsh.json"


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _map(features):
    return normalize_map({"map_id": "partial", "display_name": "Partial", "width_squares": 6, "height_squares": 6,
                          "features": features})


def _cells(document, kind):
    return {tuple(cell) for row in document["terrain"] if row["type"] == kind for cell in row["cells"]}


def _floor(document, style):
    return {tuple(cell) for row in document["materials"] if row["material"] == "floor:" + style for cell in row["cells"]}


def test_more_than_half_counts_and_exactly_half_does_not():
    water = {"floor": "shallows", "terrain": "DIFFICULT"}
    assert _cells(_map([{**water, "area": _box(0, 0, 0.51, 1)}]), "DIFFICULT") == {(0, 0)}
    half = _map([{**water, "area": _box(0, 0, 0.5, 1)}])
    assert _cells(half, "DIFFICULT") == set() and _floor(half, "shallows") == set()
    # A band: 1 wide along y = 2.5 from x 0.5 to 5.5 with round ends covers row 2 (each end square is 0.5 + a
    # quarter circle = 89%); the same band centred on a grid line (y = 3) covers rows 2 and 3 exactly half each.
    assert _cells(_map([{**water, "path": [[0.5, 2.5], [5.5, 2.5]], "width": 1}]), "DIFFICULT") == {(x, 2) for x in range(6)}
    assert _cells(_map([{**water, "path": [[0, 3], [6, 3]], "width": 1}]), "DIFFICULT") == set()
    assert _cells(_map([{**water, "path": [[0, 3], [6, 3]], "width": 1.2}]), "DIFFICULT") == {(x, y) for x in range(6) for y in (2, 3)}


def test_two_shapes_of_one_kind_add_up_per_kind_not_per_shape():
    water = {"floor": "shallows", "terrain": "DIFFICULT"}
    one = [{**water, "area": _box(0, 0, 0.3, 1)}]
    two = one + [{**water, "area": _box(0.6, 0, 0.9, 1)}]
    assert _cells(_map(one), "DIFFICULT") == set()
    assert _cells(_map(two), "DIFFICULT") == {(0, 0)}
    assert tabletop.map_warnings(_map(two)) == []  # together they rule the square, so neither is a drawn lie
    assert tabletop.map_warnings(_map(one))  # alone it is drawn but rules nothing


def test_a_later_boardwalk_cuts_the_water_under_it():
    water = {"floor": "shallows", "terrain": "DIFFICULT", "area": _box(0, 0, 6, 6)}
    document = _map([water, {"floor": "wood", "area": _box(0, 2, 6, 3)}, {"floor": "wood", "area": _box(0, 4, 6, 4.6)}])
    rows = {y for _, y in _cells(document, "DIFFICULT")}
    assert rows == {0, 1, 3, 5}  # row 4 is 60% boardwalk, so only 40% water
    assert _floor(document, "wood") == {(x, y) for x in range(6) for y in (2, 4)}
    assert all(row.get("from_features") for row in document["terrain"])
    # The order matters: water drawn after the boardwalk covers it again.
    assert _cells(_map([{"floor": "wood", "area": _box(0, 2, 6, 3)}, water]), "DIFFICULT") == {(x, y) for x in range(6) for y in range(6)}


def test_features_round_trip_and_a_map_without_them_is_unchanged():
    marsh = normalize_map(json.loads(MARSH.read_text(encoding="utf-8")))
    assert normalize_map(marsh) == marsh  # the editor saves the expanded rows back; they are made again, identically
    assert [row.get("path") or row.get("area") for row in marsh["features"]][0][0] == [21.49, 0.0]
    plain = normalize_map({"map_id": "plain", "display_name": "Plain", "width_squares": 6, "height_squares": 6,
                           "terrain": [{"type": "DIFFICULT", "cells": [[1, 1]]}],
                           "materials": [{"material": "floor:wood", "cells": [[2, 2]]}]})
    assert "features" not in plain
    assert plain["terrain"][0]["cells"] == [[1, 1]] and "from_features" not in plain["terrain"][0]
    assert plain["materials"] == [{"material": "floor:wood", "cells": [[2, 2]]}]
    section = to_battlefield(marsh)["tabletop"]
    assert all(isinstance(v, int) for f in section["features"] for p in f.get("path") or f["area"] for v in p)
    canonical_sha256(to_battlefield(marsh))  # a sealed arena holds no floats


def test_sunken_marsh_has_no_dry_crossing_except_on_the_boardwalks():
    marsh = normalize_map(json.loads(MARSH.read_text(encoding="utf-8")))
    width, height = marsh["width_squares"], marsh["height_squares"]
    blocked, _ = rasterize(marsh)
    water = _cells(marsh, "DIFFICULT")
    boardwalk = {tuple(c) for row in marsh["materials"] if row["material"] == "floor:wood" and row.get("from_features")
                 for c in row["cells"]}
    channel = next(f for f in marsh["features"] if "path" in f)
    assert channel["terrain"] == "DIFFICULT" and len(channel["path"]) > 20  # one winding path, not straight strips
    assert len([f for f in marsh["features"] if "area" in f and f.get("terrain") == "DIFFICULT"]) == 4  # ponds

    def reaches_east(closed):
        seen = {(0, y) for y in range(height) if (0, y) not in closed}
        pending = list(seen)
        while pending:
            x, y = pending.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):  # diagonal steps too: no corner-to-corner gap at a bend
                    cell = (x + dx, y + dy)
                    if 0 <= cell[0] < width and 0 <= cell[1] < height and cell not in closed and cell not in seen:
                        seen.add(cell)
                        pending.append(cell)
        return any(x == width - 1 for x, _ in seen)

    assert not reaches_east(blocked | water | boardwalk), "a dry way across the channel that is not a boardwalk"
    assert reaches_east(blocked | water), "the boardwalks cross the channel"
    for y0 in (3, 14, 27):  # each of the three boardwalks alone is a dry crossing
        others = {cell for cell in boardwalk if not y0 <= cell[1] <= y0 + 1}
        assert reaches_east(blocked | water | others), f"the boardwalk at row {y0} crosses"
    assert not water & blocked


@pytest.mark.parametrize("path", MAPS, ids=lambda path: path.stem)
def test_every_shipped_map_passes_the_generic_checks(path):
    """Every feature counts for at least one square; no wall covers no square; no terrain or zone square is on a
    blocked square (MAPSURVEY1 #5, #6). The editor shows the same warnings; a map with them still loads."""
    document = normalize_map(json.loads(path.read_text(encoding="utf-8")))
    assert tabletop.map_warnings(document) == []


def test_the_generic_checks_catch_each_problem():
    document = normalize_map({
        "map_id": "bad", "display_name": "Bad", "width_squares": 6, "height_squares": 6,
        "walls": [{"id": "pebble", "shape": "circle", "points": [[2, 2], [2.6, 2]]},
                  {"id": "block", "shape": "rect", "points": [[4, 4], [5, 5]]}],
        "terrain": [{"type": "DIFFICULT", "cells": [[4, 4]]}],
        "features": [{"floor": "shallows", "terrain": "DIFFICULT", "area": _box(0, 0, 0.4, 1)}]})
    warnings = " ".join(tabletop.map_warnings(document))
    assert "Feature 1" in warnings and "Wall pebble covers no square" in warnings and "DIFFICULT lies on 1 blocked" in warnings
