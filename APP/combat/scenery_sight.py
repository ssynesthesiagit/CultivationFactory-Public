"""Physical plant layout used by map compilation and scenery-sight.js/art.

The shared JSON defines integer hundredths of a square. Plant sight blocking
requires height >= 5 ft and diameter >= 1 ft (radius >= 10 hundredths). Leaves,
tiny shoots and look-only decor are not opaque. Movement footprints stay in
tabletop.py; a sight cross never adds a movement block.
Ordinary trees retain the existing trunk-footprint cross width; a great tree
has one cross at its actual centre rather than four misplaced small crosses.
"""
import json
from pathlib import Path
from .map_heights import DEFAULTS

POLICY = json.loads((Path(__file__).resolve().parents[1] /
                     'static/tabletop/scenery-sight.json').read_text())


def bamboo_groups(cells):
    ordered = sorted(set(map(tuple, cells)), key=lambda c: (c[1], c[0]))
    have, used, groups = set(ordered), set(), []
    for size in (3, 2, 1):
        for x, y in ordered:
            block = [(x+dx, y+dy) for dy in range(size) for dx in range(size)]
            if not set(block) <= have or set(block) & used:
                continue
            used.update(block)
            groups.append({'x': x, 'y': y, 'size': size, 'cells': block})
    return groups


def bamboo_culms(x=0, y=0, size=1, clump=False, rotation=0):
    out = []
    for cx, cy, radius in POLICY['bamboo_clump_culms' if clump else 'bamboo_culms']:
        for _ in range(rotation // 90):
            cx, cy = 100-cy, cx
        out.append({'x': x*100+cx*size, 'y': y*100+cy*size, 'r': radius*size})
    return out


def plant_blocks_sight(plant, height):
    return height >= POLICY['plant_min_height_ft'] and plant['r'] >= POLICY['plant_min_radius']


def terrain_blocks_sight(row):
    """Tall physical cover/solid looks; ground texture/depth is not a wall."""
    return row['height_ft'] >= POLICY['plant_min_height_ft'] and (
        row['type'] == 'SIMPLE_COVER' or DEFAULTS['terrain_ft'].get(row.get('look'),0) >= 5)


# Painted scenery blocks sight through one invisible centre plus per square (owner 2026-10-23: "plus symbols
# should be default for most objects so you can see what the object is and it still blocks the sight"): the art
# stays readable and the cross hides what is behind it. Only looks that really fill their square keep full-square
# sight -- a low wall is a wall run seen from above, a palisade is a wall of upright logs, and a crag or cliff edge
# is a solid rock face that is the square. Both the map editor and a fight read this one list.
SQUARE_FILLING_LOOKS = frozenset({'low_wall', 'palisade', 'crag', 'cliff_edge'})


def terrain_occluder(row):
    """The sight shape of one painted scenery square: 'cell' or 'centerline'."""
    return 'cell' if row.get('look') in SQUARE_FILLING_LOOKS else 'centerline'


def trunk_cross(plant):
    x, y, r = plant['x'], plant['y'], plant['r']
    return [[[x-r, y], [x+r, y]], [[x, y-r], [x, y+r]]]


def tree_trunks(tree):
    size = tree['size']
    if tree.get('look') in {'bamboo_stand', 'golden_bamboo'}:
        return bamboo_culms(tree['x'], tree['y'], size)
    return [{'x': tree['x']*100+size*50, 'y': tree['y']*100+size*50,
             'r': POLICY['tree_radius']*size}]


def plant_segments(plants, height):
    return {'scale': POLICY['scale'], 'segments': [segment for p in plants
            if plant_blocks_sight(p, height) for segment in trunk_cross(p)]}
