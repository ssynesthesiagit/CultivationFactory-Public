"""Floor-region authoring for generators; never changes a running fight.

Use ``confine_floor_to_rooms`` when a material is intended as an interior
floor. Outdoor paving is an explicit authoring choice, not a renderer rule:
the board must continue to draw all of a map's deliberately painted cells.
"""

from copy import deepcopy

from combat.map_heights import DEFAULTS
from combat.roof_coverage import roof_regions
from combat.tabletop import BACKGROUND_STYLES, normalize_map, wall_cells


def confine_floor_to_rooms(document, style, exterior_style):
    """Keep a floor in authored rooms and repaint its outside cells.

    Room cells exclude walls and use the existing building detector, including
    placed wall sections and doors. No bounding rectangle is used: a room's
    walls, rather than the rectangle around its building, bound its floor.
    Both styles must be valid floor styles. The caller explicitly opts into
    this rule; courtyard paving and other maps are never changed implicitly.
    The input is not mutated. The returned document uses editor-normalized
    materials, so a generator can validate/save it through the usual pipeline.
    """
    if style not in DEFAULTS["indoor_styles"] or exterior_style not in BACKGROUND_STYLES:
        raise ValueError("Choose an indoor floor and a known exterior floor style.")
    if style == exterior_style:
        raise ValueError("The interior and exterior floor styles must differ.")
    result = normalize_map(deepcopy(document))
    rooms = roof_regions(result, wall_cells)
    inside = set().union(*(room["cells"] for room in rooms))
    outside = []
    for row in result["materials"]:
        if row["material"] == "floor:" + style:
            outside.extend(cell for cell in row["cells"] if tuple(cell) not in inside)
            row["cells"] = [cell for cell in row["cells"] if tuple(cell) in inside]
    if outside:
        result["materials"].append({"material": "floor:" + exterior_style, "cells": outside})
    return normalize_map(result)


def main():
    """Check a generated map, or emit a corrected copy to stdout."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map", type=Path)
    parser.add_argument("--floor", required=True, help="Interior floor style to confine")
    parser.add_argument("--outside", required=True, help="Floor style for cells outside rooms")
    parser.add_argument("--check", action="store_true", help="Reject outside floor cells without changing the map")
    args = parser.parse_args()
    document = json.loads(args.map.read_text())
    try:
        corrected = confine_floor_to_rooms(document, args.floor, args.outside)
    except ValueError as error:
        parser.error(str(error))
    if args.check:
        if corrected["materials"] != normalize_map(document)["materials"]:
            parser.exit(1, "The selected interior floor extends outside its rooms.\n")
    else:
        print(json.dumps(corrected, indent=1))


if __name__ == "__main__":
    main()
