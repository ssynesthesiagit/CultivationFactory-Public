"""Large bamboo stands block sight (owner 2026-09-29: "can the large clumps block vision as well?"): every whole 3x3 block
of painted bamboo, then every whole 2x2 block, is a stand. LOSLINES3 also binds
individual sufficiently large culms in the remaining single-square clumps.
combat/tabletop.py bamboo_stands / rasterize (static/tabletop/vision.js bambooStands draws the same)."""

from combat.tabletop import BAMBOO, bamboo_stands, rasterize


def _map(cells):
    return {"width_squares": 20, "height_squares": 20, "walls": [], "trees": [], "materials": [{"material": BAMBOO, "cells": cells}]}


def test_whole_blocks_are_stands_and_block_sight():
    block3 = [[x, y] for x in range(2, 5) for y in range(2, 5)]
    block2 = [[x, y] for x in range(8, 10) for y in range(2, 4)]
    singles = [[0, 0], [12, 12]]
    document = _map(block3 + block2 + singles)
    assert bamboo_stands(document) == [(2, 2, 3), (8, 2, 2)]
    blocked, sight = rasterize(document)
    assert not blocked
    assert sight == {tuple(cell) for cell in block3 + block2 + singles}


def test_a_4x4_patch_is_one_3x3_stand_and_the_rest_single():
    patch = [[x, y] for x in range(4) for y in range(4)]
    assert bamboo_stands(_map(patch)) == [(0, 0, 3)]
